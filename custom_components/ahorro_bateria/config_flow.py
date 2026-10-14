"""Alta y Configurar de Ahorro Batería.

Alta en dos pasos: las entidades de origen y lo acumulado hasta hoy. En
Configurar se pueden cambiar las entidades (recarga la integración sin
perder nada) o corregir los totales.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .calculo import CLAVES_CORREGIBLES
from .const import (
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
    SUGERIDAS,
)
from .contador import ContadorAhorro, async_leer_almacen

_POTENCIA = EntitySelector(EntitySelectorConfig(domain="sensor"))
_VALOR = EntitySelector(EntitySelectorConfig(domain=["sensor", "input_number", "number"]))
_PERIODO = EntitySelector(EntitySelectorConfig(domain=["sensor", "input_select", "select"]))

ESQUEMA_FUENTES = vol.Schema(
    {
        vol.Required(CONF_BATERIA): _POTENCIA,
        vol.Required(CONF_BATERIA_POSITIVA_DESCARGA, default=True): BooleanSelector(),
        vol.Required(CONF_RED): _POTENCIA,
        vol.Required(CONF_RED_POSITIVA_IMPORTA, default=True): BooleanSelector(),
        vol.Required(CONF_PRECIO_COMPRA): _VALOR,
        vol.Required(CONF_PRECIO_VENTA): _VALOR,
        vol.Optional(CONF_IVA): _VALOR,
        vol.Optional(CONF_IMPUESTO_ELECTRICO): _VALOR,
        vol.Optional(CONF_PERIODO): _PERIODO,
        # Opcional: sin él no hay ahorro de las placas.
        vol.Optional(CONF_CONSUMO): _POTENCIA,
    }
)


def _numero(unidad: str, minimo: float | None = 0) -> NumberSelector:
    config = NumberSelectorConfig(step="any", mode=NumberSelectorMode.BOX, unit_of_measurement=unidad)
    if minimo is not None:
        config["min"] = minimo
    return NumberSelector(config)


ESQUEMA_ACUMULADOS = vol.Schema(
    {
        # El neto puede ser negativo (si la carga ha costado más de lo ahorrado).
        vol.Required("neto", default=0.0): _numero("€", minimo=None),
        vol.Required("placas", default=0.0): _numero("€", minimo=None),
        vol.Required("descarga_punta", default=0.0): _numero("kWh"),
        vol.Required("descarga_llano", default=0.0): _numero("kWh"),
        vol.Required("descarga_valle", default=0.0): _numero("kWh"),
        vol.Required("carga", default=0.0): _numero("kWh"),
    }
)


def _sugeridas(hass: HomeAssistant) -> dict[str, Any]:
    return {clave: eid for clave, eid in SUGERIDAS.items() if hass.states.get(eid) is not None}


def _validar_fuentes(datos: dict[str, Any]) -> dict[str, str]:
    if datos[CONF_BATERIA] == datos[CONF_RED]:
        return {CONF_RED: "misma_entidad"}
    if datos.get(CONF_CONSUMO) in (datos[CONF_BATERIA], datos[CONF_RED]):
        return {CONF_CONSUMO: "misma_entidad"}
    return {}


class AhorroBateriaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Alta de Ahorro Batería (una sola por instalación, ver manifest)."""

    VERSION = 1

    def __init__(self) -> None:
        self._fuentes: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OpcionesAhorroBateria:
        return OpcionesAhorroBateria()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errores: dict[str, str] = {}
        if user_input is not None:
            errores = _validar_fuentes(user_input)
            if not errores:
                self._fuentes = user_input
                return await self.async_step_acumulados()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                ESQUEMA_FUENTES, user_input or _sugeridas(self.hass)
            ),
            errors=errores,
        )

    async def async_step_acumulados(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="Ahorro batería",
                data={CONF_INICIALES: {k: user_input[k] for k in CLAVES_CORREGIBLES}},
                options=self._fuentes,
            )

        # Si se borró la integración, lo que tenía acumulado sigue en disco:
        # se propone para no empezar de cero.
        anteriores = (await async_leer_almacen(self.hass) or {}).get("total", {})
        return self.async_show_form(
            step_id="acumulados",
            data_schema=self.add_suggested_values_to_schema(
                ESQUEMA_ACUMULADOS,
                {k: round(anteriores[k], 4) for k in CLAVES_CORREGIBLES if k in anteriores},
            ),
        )


class OpcionesAhorroBateria(OptionsFlowWithReload):
    """Configurar: cambiar las entidades o corregir los totales."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["fuentes", "acumulados"])

    async def async_step_fuentes(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errores: dict[str, str] = {}
        if user_input is not None:
            errores = _validar_fuentes(user_input)
            if not errores:
                # Se guarda tal cual: un campo opcional vaciado desaparece.
                return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="fuentes",
            data_schema=self.add_suggested_values_to_schema(
                ESQUEMA_FUENTES, user_input or dict(self.config_entry.options)
            ),
            errors=errores,
        )

    async def async_step_acumulados(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        contador: ContadorAhorro | None = getattr(self.config_entry, "runtime_data", None)
        if contador is None:
            return self.async_abort(reason="no_cargada")

        if user_input is not None:
            await contador.async_corregir(user_input)
            # Las opciones no cambian, así que no se recarga nada.
            return self.async_create_entry(data=dict(self.config_entry.options))

        total = contador.acumulados.total
        return self.async_show_form(
            step_id="acumulados",
            data_schema=self.add_suggested_values_to_schema(
                ESQUEMA_ACUMULADOS, {k: round(total[k], 4) for k in CLAVES_CORREGIBLES}
            ),
        )
