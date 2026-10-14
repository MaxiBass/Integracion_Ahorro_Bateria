"""Lleva la cuenta: escucha las fuentes, va sumando y lo guarda en disco.

Cada intervalo se cuenta con los valores que tenían las fuentes al empezar
(suma de Riemann por la izquierda, como la integración `integration` de HA
con `method: left`): cuando una fuente cambia, primero se cierra el
intervalo con los valores viejos y luego se toman los nuevos. Además, cada
minuto se cierra el intervalo en curso aunque nada cambie, para que los
sensores no se queden quietos.

No se cuenta nada mientras falte un dato (fuente no disponible o sin valor
aún), ni el tiempo que HA ha estado parado: tras arrancar, el primer
intervalo empieza en el arranque.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import date, datetime, timedelta
import logging
import math
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    EVENT_HOMEASSISTANT_STOP,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfPower,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .calculo import Acumulados, Entradas, aportacion
from .const import (
    ALIAS_PERIODO,
    CONF_BATERIA,
    CONF_BATERIA_POSITIVA_DESCARGA,
    CONF_CONSUMO,
    CONF_IMPUESTO_ELECTRICO,
    CONF_INICIALES,
    CONF_IVA,
    CONF_PERIODO,
    CONF_PRECIO_COMPRA,
    CONF_PRECIO_VENTA,
    CONF_RED,
    CONF_RED_POSITIVA_IMPORTA,
    DOMAIN,
    FUENTES,
    INTERVALO_REFRESCO,
    MAX_INTERVALO,
    RETRASO_GUARDADO,
    VERSION_ALMACEN,
)

_LOGGER = logging.getLogger(__name__)


def _ahora() -> datetime:
    """Hora actual (UTC). Aparte para que las pruebas puedan mover el reloj."""
    return dt_util.utcnow()


def _dia_local(momento: datetime) -> str:
    return dt_util.as_local(momento).date().isoformat()


# Un solo fichero (.storage/ahorro_bateria): solo hay una entrada por
# instalación, y así lo acumulado sobrevive a borrar la integración por
# error; el alta siguiente lo propone como punto de partida (config_flow).
CLAVE_ALMACEN = DOMAIN


async def async_leer_almacen(hass: HomeAssistant) -> dict[str, Any] | None:
    return await Store[dict[str, Any]](hass, VERSION_ALMACEN, CLAVE_ALMACEN).async_load()


def senal_actualizado(entry_id: str) -> str:
    return f"{DOMAIN}_{entry_id}_actualizado"


class ContadorAhorro:
    """El estado vivo de una entrada: entradas actuales y acumulados."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.opciones = dict(entry.options)
        self.almacen: Store[dict[str, Any]] = Store(hass, VERSION_ALMACEN, CLAVE_ALMACEN)
        self.acumulados = Acumulados.nuevos(_dia_local(_ahora()))
        self.entradas = Entradas()
        # Inicio del intervalo en curso (None: no hay intervalo abierto).
        self._desde: datetime | None = None
        self.ultimo_cierre: datetime | None = None
        self._quitar: list[Callable[[], None]] = []
        self._quitar_parada: Callable[[], None] | None = None

    # ── Arranque y parada ──────────────────────────────────────────────

    async def async_cargar(self) -> None:
        datos = await self.almacen.async_load()
        if datos and datos.get("entry_id") == self.entry.entry_id:
            self.acumulados = Acumulados.desde_dict(datos)
        else:
            # Primera vez de esta entrada: se parte de lo que se indicó en el
            # alta (que, si había algo guardado de una entrada anterior, el
            # formulario ya proponía).
            self.acumulados = Acumulados.nuevos(
                _dia_local(_ahora()), self.entry.data.get(CONF_INICIALES)
            )
            await self.almacen.async_save(self._datos())
        self._comprobar_dia(_ahora())

    @callback
    def async_arrancar(self) -> None:
        self.entradas = self._leer_entradas()
        self._desde = _ahora()
        fuentes = [eid for clave in FUENTES if (eid := self.opciones.get(clave))]
        self._quitar = [
            async_track_state_change_event(self.hass, fuentes, self._al_cambiar_fuente),
            async_track_time_interval(
                self.hass, self._al_refrescar, INTERVALO_REFRESCO, name=f"{DOMAIN} refresco"
            ),
            # A medianoche, para que lo de «hoy» vuelva a 0 en el momento.
            async_track_time_change(self.hass, self._al_refrescar, hour=0, minute=0, second=0),
        ]
        self._quitar_parada = self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, self._al_parar
        )

    async def async_parar(self) -> None:
        """Al descargar la entrada: cierra el intervalo y guarda ya."""
        for quitar in self._quitar:
            quitar()
        self._quitar = []
        if self._quitar_parada is not None:
            self._quitar_parada()
            self._quitar_parada = None
        self._cerrar_intervalo(_ahora())
        self._desde = None
        await self.almacen.async_save(self._datos())

    @callback
    def _al_parar(self, _event: Event) -> None:
        # Al apagar HA: el guardado retrasado se escribe en la escritura
        # final, así que basta con cerrar el intervalo. El aviso ya se ha
        # consumido: quitarlo otra vez daría un error en el log.
        self._quitar_parada = None
        self._cerrar_intervalo(_ahora())
        self._desde = None

    # ── Eventos ────────────────────────────────────────────────────────

    @callback
    def _al_cambiar_fuente(self, _event: Event[EventStateChangedData]) -> None:
        ahora = _ahora()
        self._cerrar_intervalo(ahora)
        self.entradas = self._leer_entradas()

    @callback
    def _al_refrescar(self, _now: datetime | None = None) -> None:
        self.async_actualizar()

    @callback
    def async_actualizar(self) -> None:
        """Cierra el intervalo en curso y refresca los sensores."""
        self._cerrar_intervalo(_ahora())
        async_dispatcher_send(self.hass, senal_actualizado(self.entry.entry_id))

    async def async_corregir(self, valores: dict[str, Any]) -> None:
        """Fija los totales (desde Configurar) y lo guarda en el momento."""
        self._cerrar_intervalo(_ahora())
        self.acumulados.corregir(valores)
        await self.almacen.async_save(self._datos())
        async_dispatcher_send(self.hass, senal_actualizado(self.entry.entry_id))

    # ── Cuenta ─────────────────────────────────────────────────────────

    def _cerrar_intervalo(self, ahora: datetime) -> None:
        """Suma desde el inicio del intervalo hasta `ahora` y abre otro."""
        desde, self._desde = self._desde, ahora
        if desde is None or ahora <= desde:
            self._comprobar_dia(ahora)
            return
        self.ultimo_cierre = ahora
        if ahora - desde > MAX_INTERVALO:
            _LOGGER.debug(
                "No se cuenta un intervalo de %s (de %s a %s)", ahora - desde, desde, ahora
            )
            self._comprobar_dia(ahora)
            self._guardar_luego()
            return

        # Si el intervalo cruza la medianoche, cada trozo va a su día.
        inicio = desde
        while _dia_local(inicio) != _dia_local(ahora):
            manana = date.fromisoformat(_dia_local(inicio)) + timedelta(days=1)
            medianoche = dt_util.start_of_local_day(manana)
            self._sumar(inicio, medianoche)
            self.acumulados.cambiar_de_dia(manana.isoformat())
            inicio = medianoche
        self._comprobar_dia(inicio)
        self._sumar(inicio, ahora)
        self._guardar_luego()

    def _sumar(self, desde: datetime, hasta: datetime) -> None:
        horas = (hasta - desde).total_seconds() / 3600
        self.acumulados.sumar(aportacion(self.entradas, horas))

    def _comprobar_dia(self, momento: datetime) -> None:
        dia = _dia_local(momento)
        if self.acumulados.dia != dia:
            self.acumulados.cambiar_de_dia(dia)

    def _datos(self) -> dict[str, Any]:
        return {"entry_id": self.entry.entry_id, **self.acumulados.a_dict()}

    def _guardar_luego(self) -> None:
        self.almacen.async_delay_save(self._datos, RETRASO_GUARDADO)

    # ── Lectura de las fuentes ─────────────────────────────────────────

    def _leer_entradas(self) -> Entradas:
        anterior = self.entradas
        opciones = self.opciones

        def numero(clave: str) -> float | None:
            entity_id = opciones.get(clave)
            estado = self.hass.states.get(entity_id) if entity_id else None
            if estado is None or estado.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                return None
            try:
                valor = float(estado.state)
            except ValueError:
                return None
            if not math.isfinite(valor):
                return None
            if estado.attributes.get(ATTR_UNIT_OF_MEASUREMENT) == UnitOfPower.KILO_WATT:
                valor *= 1000
            return valor

        def potencia(clave: str, positiva_normal: str) -> float | None:
            valor = numero(clave)
            if valor is None:
                return None
            return valor if opciones.get(positiva_normal, True) else -valor

        def con_respaldo(clave: str, previo: float | None) -> float | None:
            # Precios e impuestos cambian muy de vez en cuando: si la fuente
            # desaparece un momento (p. ej. al recargar plantillas), se sigue
            # con el último valor bueno. Sin fuente configurada, impuesto 0.
            if not opciones.get(clave):
                return 0.0 if clave in (CONF_IVA, CONF_IMPUESTO_ELECTRICO) else None
            valor = numero(clave)
            return previo if valor is None else valor

        periodo = None
        if entity_id := opciones.get(CONF_PERIODO):
            estado = self.hass.states.get(entity_id)
            if estado is not None:
                periodo = ALIAS_PERIODO.get(estado.state.strip().lower())

        return Entradas(
            bateria_w=potencia(CONF_BATERIA, CONF_BATERIA_POSITIVA_DESCARGA),
            red_w=potencia(CONF_RED, CONF_RED_POSITIVA_IMPORTA),
            precio_compra=con_respaldo(CONF_PRECIO_COMPRA, anterior.precio_compra),
            precio_venta=con_respaldo(CONF_PRECIO_VENTA, anterior.precio_venta),
            iva=con_respaldo(CONF_IVA, anterior.iva),
            impuesto_electrico=con_respaldo(CONF_IMPUESTO_ELECTRICO, anterior.impuesto_electrico),
            periodo=periodo,
            consumo_w=numero(CONF_CONSUMO),
        )

    # ── Diagnóstico ────────────────────────────────────────────────────

    def diagnostico(self) -> dict[str, Any]:
        return {
            "entradas": asdict(self.entradas) | {"completas": self.entradas.completas},
            "intervalo_desde": self._desde.isoformat() if self._desde else None,
            "ultimo_cierre": self.ultimo_cierre.isoformat() if self.ultimo_cierre else None,
            "acumulados": self.acumulados.a_dict(),
        }
