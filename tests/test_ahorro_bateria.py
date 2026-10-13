"""Pruebas de Ahorro Batería. Se ejecutan sin pytest:

    /tmp/hav/bin/python tests/test_ahorro_bateria.py

Tres bloques: los ficheros estáticos, el cálculo puro (`calculo.py`) con
casos hechos a mano, y un Home Assistant real (el del venv) en un directorio
temporal con la integración enlazada en `custom_components/`. Las fuentes
(batería, red, precios, periodo) son estados puestos a mano y el reloj de la
integración se mueve desde la prueba, así que una hora simulada tarda
milisegundos.

Todos los precios y totales son inventados (2.0TD con un 10 % de IVA y un
0,5 % de impuesto eléctrico): este repositorio es público.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
BASE = RAIZ / "custom_components" / "ahorro_bateria"
DOMINIO = "ahorro_bateria"

fallos: list[str] = []


def comprobar(condicion: bool, etiqueta: str) -> None:
    if condicion:
        print(f"  OK    {etiqueta}")
    else:
        print(f"  FALLO {etiqueta}")
        fallos.append(etiqueta)


def casi(a: float, b: float, tolerancia: float = 1e-4) -> bool:
    return abs(a - b) <= tolerancia


# Precios del ejemplo.
PUNTA = round(0.20 * 1.005 * 1.10, 5)  # 0.2211 €/kWh con impuestos
LLANO = round(0.12 * 1.005 * 1.10, 5)
VALLE = round(0.08 * 1.005 * 1.10, 5)
EXCEDENTE = 0.05
EXCEDENTE_FINAL = 0.05 * 1.005 * 1.10  # 0.055275

ENTITY_IDS = {
    "neto_hoy": "sensor.ahorro_bateria_hoy",
    "neto_total": "sensor.ahorro_bateria_total",
    "bruto_hoy": "sensor.bateria_ahorro_bruto_hoy",
    "coste_hoy": "sensor.bateria_coste_oportunidad_hoy",
    "descarga_punta_hoy": "sensor.bateria_descarga_punta_kwh_hoy",
    "descarga_llano_hoy": "sensor.bateria_descarga_llano_kwh_hoy",
    "descarga_valle_hoy": "sensor.bateria_descarga_valle_kwh_hoy",
    "descarga_punta_total": "sensor.bateria_total_kwh_punta",
    "descarga_llano_total": "sensor.bateria_total_kwh_llano",
    "descarga_valle_total": "sensor.bateria_total_kwh_valle",
    "carga_total": "sensor.bateria_total_kwh_carga",
    "carga_hoy": "sensor.bateria_carga_kwh_hoy",
    "carga_red_hoy": "sensor.bateria_carga_red_kwh_hoy",
}


# ── Ficheros estáticos ───────────────────────────────────────────────


def test_ficheros() -> None:
    print("\nManifest, traducciones e icono")

    manifest = json.loads((BASE / "manifest.json").read_text("utf-8"))
    comprobar(
        "github.com/MaxiBass/" in manifest.get("documentation", "") and "issue_tracker" in manifest,
        "manifest apunta al repo (documentation, issue_tracker)",
    )
    comprobar(manifest.get("single_config_entry") is True, "una sola entrada por instalación")
    comprobar(manifest.get("requirements") == [], "sin dependencias externas")

    es = json.loads((BASE / "translations" / "es.json").read_text("utf-8"))
    en = json.loads((BASE / "translations" / "en.json").read_text("utf-8"))
    cadenas = json.loads((BASE / "strings.json").read_text("utf-8"))

    def claves(d: dict, prefijo: str = "") -> set[str]:
        salida = set()
        for k, v in d.items():
            salida |= claves(v, f"{prefijo}{k}.") if isinstance(v, dict) else {f"{prefijo}{k}"}
        return salida

    comprobar(claves(es) == claves(en), "es.json y en.json tienen las mismas claves")
    comprobar(es == cadenas, "strings.json coincide con es.json")
    comprobar(es != en, "en.json no es una copia de es.json")

    iconos = json.loads((BASE / "icons.json").read_text("utf-8"))
    comprobar(
        set(iconos["entity"]["sensor"]) == set(es["entity"]["sensor"]) == set(ENTITY_IDS),
        "cada sensor tiene nombre e icono",
    )

    from PIL import Image

    tamanos = {}
    for nombre in ("icon.png", "icon@2x.png"):
        ruta = BASE / "brand" / nombre
        tamanos[nombre] = Image.open(ruta).size if ruta.exists() else None
    comprobar(tamanos == {"icon.png": (256, 256), "icon@2x.png": (512, 512)},
              f"icono propio en brand/ con los tamaños de HA {tamanos}")


# ── Cálculo puro ─────────────────────────────────────────────────────


def test_calculo() -> None:
    print("\nCálculo (una hora con valores fijos)")
    from custom_components.ahorro_bateria.calculo import Acumulados, Entradas, aportacion

    def una_hora(bateria, red, compra, periodo="punta", **extra):
        return aportacion(
            Entradas(bateria, red, compra, EXCEDENTE, 10.0, 0.5, periodo, **extra), 1.0
        )

    a = una_hora(1000, 200, PUNTA)
    comprobar(casi(a["bruto"], PUNTA, 1e-9) and casi(a["descarga_punta"], 1.0, 1e-9) and a["coste"] == 0,
              f"descarga a la casa: ahorra lo que se habría comprado ({a['bruto']:.5f} €)")

    a = una_hora(1000, -300, PUNTA)
    esperado = PUNTA * 0.7 + EXCEDENTE_FINAL * 0.3
    comprobar(casi(a["bruto"], esperado, 1e-9),
              f"descarga que en parte se exporta: 0,7 kWh a precio de compra y 0,3 a excedente ({a['bruto']:.5f} €)")

    a = una_hora(-2000, -500, PUNTA)
    comprobar(casi(a["coste"], 2 * EXCEDENTE_FINAL, 1e-9) and casi(a["carga"], 2.0, 1e-9)
              and a["carga_red"] == 0 and a["bruto"] == 0,
              f"carga con sol: cuesta el excedente que no se vende, con impuestos ({a['coste']:.5f} €)")

    a = una_hora(-2000, 2300, VALLE, periodo="valle")
    comprobar(casi(a["coste"], 2 * VALLE, 1e-9) and casi(a["carga_red"], 2.0, 1e-9),
              f"carga desde la red: cuesta lo comprado ({a['coste']:.5f} €, {a['carga_red']} kWh de red)")

    a = una_hora(-2000, 500, VALLE, periodo="valle")
    comprobar(casi(a["coste"], 0.5 * VALLE + 1.5 * EXCEDENTE_FINAL, 1e-9) and casi(a["carga_red"], 0.5, 1e-9),
              f"carga mixta: 0,5 kWh de red y 1,5 de sol ({a['coste']:.5f} €)")

    a = una_hora(0, 400, PUNTA)
    comprobar(all(v == 0 for v in a.values()), "batería parada: no suma nada")

    a = aportacion(Entradas(None, 200, PUNTA, EXCEDENTE, 10.0, 0.5, "punta"), 1.0)
    comprobar(all(v == 0 for v in a.values()), "sin dato de la batería: no suma nada")

    a = aportacion(Entradas(1000, 200, PUNTA, EXCEDENTE, None, 0.5, "punta"), 1.0)
    comprobar(all(v == 0 for v in a.values()), "sin dato del IVA (configurado pero no disponible): no suma nada")

    b = aportacion(Entradas(1000, 200, PUNTA, EXCEDENTE, 10.0, 0.5, None), 1.0)
    comprobar(casi(b["bruto"], PUNTA, 1e-9) and b["descarga_punta"] == b["descarga_llano"] == b["descarga_valle"] == 0,
              "sin periodo conocido: cuenta los euros pero no reparte los kWh")

    acumulados = Acumulados.nuevos("2026-10-13", {"neto": 10.0, "descarga_punta": 5.0})
    acumulados.sumar(una_hora(1000, 200, PUNTA))
    acumulados.sumar(una_hora(-2000, -500, PUNTA))
    comprobar(casi(acumulados.neto_hoy, PUNTA - 2 * EXCEDENTE_FINAL, 1e-9),
              f"el neto del día puede ser negativo ({acumulados.neto_hoy:.5f} €), no se recorta a 0")
    comprobar(casi(acumulados.total["neto"], 10.0 + PUNTA - 2 * EXCEDENTE_FINAL, 1e-9)
              and casi(acumulados.total["descarga_punta"], 6.0, 1e-9),
              "el total parte de los valores iniciales")
    copia = Acumulados.desde_dict(json.loads(json.dumps(acumulados.a_dict())))
    comprobar(copia == acumulados, "se guarda y se lee igual (JSON)")


# ── Home Assistant real ──────────────────────────────────────────────


class _Registros(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.mensajes: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.mensajes.append(f"{record.name}: {record.getMessage()}")

    def con(self, *trozos: str) -> list[str]:
        return [m for m in self.mensajes if all(t in m for t in trozos)]


class Reloj:
    """El reloj de la integración: la prueba lo mueve a mano."""

    def __init__(self, inicio: datetime) -> None:
        self.t = inicio


async def _arrancar_hass(directorio: Path):
    from homeassistant import bootstrap, config_entries, core, loader
    from homeassistant.core_config import async_process_ha_core_config
    from homeassistant.setup import async_setup_component

    hass = core.HomeAssistant(str(directorio))
    loader.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await loader.async_get_custom_components(hass)
    assert await bootstrap.async_load_base_functionality(hass)
    for dominio in bootstrap.CORE_INTEGRATIONS:
        assert await async_setup_component(hass, dominio, {}), dominio
    await async_process_ha_core_config(hass, {"time_zone": "Europe/Madrid"})
    hass.set_state(core.CoreState.running)
    return hass


def _local(texto: str) -> datetime:
    """Hora local de Madrid (CEST en octubre: UTC+2) → UTC."""
    return datetime.fromisoformat(texto).replace(tzinfo=timezone(timedelta(hours=2))).astimezone(timezone.utc)


async def _recorrido(directorio: Path) -> None:
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    import custom_components.ahorro_bateria.contador as modulo_contador

    registros = _Registros()
    logging.getLogger().addHandler(registros)
    hass = await _arrancar_hass(directorio)
    reloj = Reloj(_local("2026-10-13T12:00:00"))
    modulo_contador._ahora = lambda: reloj.t

    def fuente(entity_id: str, valor, unidad: str | None = None) -> None:
        hass.states.async_set(entity_id, str(valor), {"unit_of_measurement": unidad} if unidad else {})

    def valor(clave: str) -> float:
        return float(hass.states.get(ENTITY_IDS[clave]).state)

    def contador():
        return hass.config_entries.async_entries(DOMINIO)[0].runtime_data

    async def avanzar(minutos: float) -> None:
        """Pasa el tiempo de minuto en minuto, como el refresco real."""
        for _ in range(round(minutos)):
            reloj.t += timedelta(minutes=1)
            contador().async_actualizar()
        await hass.async_block_till_done()

    async def potencias(bateria, red) -> None:
        fuente("sensor.deye_battery_power", bateria, "W")
        fuente("sensor.deye_grid_ct_power", red, "W")
        await hass.async_block_till_done()

    async def periodo(nombre: str, precio: float) -> None:
        fuente("sensor.periodo_tarifario", nombre)
        fuente("sensor.factura_luz", precio, "€/kWh")
        await hass.async_block_till_done()

    try:
        # Fuentes como las de casa.
        await potencias(0, 300)
        await periodo("Punta", PUNTA)
        fuente("input_number.precio_excedentes", EXCEDENTE, "EUR/kWh")
        fuente("input_number.precio_iva", 10.0, "%")
        fuente("input_number.precio_impuestos_electricidad", 0.5, "%")
        await hass.async_block_till_done()

        # ── Alta por el formulario ──
        print("\n  · alta por el formulario")
        flujo = await hass.config_entries.flow.async_init(DOMINIO, context={"source": "user"})
        sugeridos = {
            str(k): (k.description or {}).get("suggested_value")
            for k in flujo["data_schema"].schema
        }
        comprobar(sugeridos.get("bateria") == "sensor.deye_battery_power"
                  and sugeridos.get("periodo") == "sensor.periodo_tarifario",
                  "el formulario sale relleno con las entidades de casa que existen")
        fuentes = {
            "bateria": "sensor.deye_battery_power",
            "bateria_positiva_descarga": True,
            "red": "sensor.deye_grid_ct_power",
            "red_positiva_importa": True,
            "precio_compra": "sensor.factura_luz",
            "precio_venta": "input_number.precio_excedentes",
            "iva": "input_number.precio_iva",
            "impuesto_electrico": "input_number.precio_impuestos_electricidad",
            "periodo": "sensor.periodo_tarifario",
        }
        malo = await hass.config_entries.flow.async_configure(
            flujo["flow_id"], {**fuentes, "red": "sensor.deye_battery_power"}
        )
        comprobar(malo.get("errors") == {"red": "misma_entidad"}, "no deja usar la misma entidad para batería y red")
        paso = await hass.config_entries.flow.async_configure(flujo["flow_id"], fuentes)
        comprobar(paso.get("step_id") == "acumulados", "segundo paso: lo acumulado hasta hoy")
        iniciales = {"neto": 40.0, "descarga_punta": 100.0, "descarga_llano": 120.0,
                     "descarga_valle": 80.0, "carga": 400.0}
        fin = await hass.config_entries.flow.async_configure(paso["flow_id"], iniciales)
        await hass.async_block_till_done()
        comprobar(fin.get("type") == "create_entry", f"crea la entrada ({fin.get('type')})")
        entrada = hass.config_entries.async_entries(DOMINIO)[0]
        comprobar(entrada.state is ConfigEntryState.LOADED, f"la entrada carga ({entrada.state})")

        otra = await hass.config_entries.flow.async_init(DOMINIO, context={"source": "user"})
        comprobar(otra.get("reason") == "single_instance_allowed", "no deja dar de alta una segunda")

        # ── Entidades ──
        print("\n  · entidades")
        registro = er.async_get(hass)
        reales = {
            e.unique_id.removeprefix(f"{DOMINIO}_"): e.entity_id
            for e in er.async_entries_for_config_entry(registro, entrada.entry_id)
        }
        comprobar(reales == ENTITY_IDS, "los 13 sensores con los mismos entity_id que las plantillas YAML"
                  + ("" if reales == ENTITY_IDS else f" → {sorted(set(reales.values()) ^ set(ENTITY_IDS.values()))}"))
        dispositivos = dr.async_entries_for_config_entry(dr.async_get(hass), entrada.entry_id)
        comprobar(len(dispositivos) == 1 and dispositivos[0].entry_type is dr.DeviceEntryType.SERVICE,
                  "un dispositivo de tipo servicio")
        hoy = hass.states.get(ENTITY_IDS["neto_hoy"])
        comprobar(hoy.attributes.get("device_class") == "monetary"
                  and hoy.attributes.get("state_class") == "total"
                  and hoy.attributes.get("unit_of_measurement") == "€",
                  "los € son monetarios con state_class total (estadísticas a largo plazo)")
        comprobar(hoy.attributes.get("last_reset") == _local("2026-10-13T00:00:00").astimezone(
                      timezone(timedelta(hours=2))).isoformat(),
                  f"los € del día llevan last_reset a medianoche ({hoy.attributes.get('last_reset')})")
        punta = hass.states.get(ENTITY_IDS["descarga_punta_total"])
        comprobar(punta.attributes.get("state_class") == "total_increasing"
                  and punta.attributes.get("unit_of_measurement") == "kWh",
                  "los kWh son total_increasing, como las plantillas que sustituyen")
        comprobar(casi(valor("neto_total"), 40.0) and casi(valor("descarga_punta_total"), 100.0)
                  and casi(valor("carga_total"), 400.0) and valor("neto_hoy") == 0,
                  "los totales parten de los valores del alta y lo de hoy de 0")

        # ── Una hora descargando en punta ──
        print("\n  · descarga hacia la casa en punta")
        await potencias(1000, 200)
        await avanzar(60)
        comprobar(casi(valor("neto_hoy"), PUNTA) and casi(valor("bruto_hoy"), PUNTA) and valor("coste_hoy") == 0,
                  f"1 kWh en punta ahorra {PUNTA} € ({valor('neto_hoy')})")
        comprobar(casi(valor("descarga_punta_hoy"), 1.0) and casi(valor("descarga_punta_total"), 101.0),
                  "1 kWh de descarga en punta, hoy y en el total")
        comprobar(casi(valor("neto_total"), 40.0 + PUNTA), "el total sube lo mismo")

        antes = {k: valor(k) for k in ENTITY_IDS}
        fuente("sensor.factura_luz", 0.35, "€/kWh")
        await hass.async_block_till_done()
        contador().async_actualizar()
        await hass.async_block_till_done()
        comprobar({k: valor(k) for k in ENTITY_IDS} == antes,
                  "cambiar un precio no revaloriza lo ya acumulado (el YAML sí lo hacía)")
        fuente("sensor.factura_luz", PUNTA, "€/kWh")
        await hass.async_block_till_done()

        # ── Cambio a valle y carga desde la red ──
        print("\n  · cambio de periodo y carga desde la red")
        await periodo("Valle", VALLE)
        await potencias(-2000, 2300)
        await avanzar(30)
        comprobar(casi(valor("coste_hoy"), VALLE), f"1 kWh de red en valle cuesta {VALLE} € ({valor('coste_hoy')})")
        comprobar(casi(valor("carga_hoy"), 1.0) and casi(valor("carga_red_hoy"), 1.0)
                  and casi(valor("carga_total"), 401.0),
                  "1 kWh de carga, todo desde la red")
        comprobar(casi(valor("descarga_punta_hoy"), 1.0) and valor("descarga_valle_hoy") == 0,
                  "la carga no suma descarga en ningún periodo")

        # ── Fuente no disponible ──
        print("\n  · batería no disponible")
        antes = {k: valor(k) for k in ENTITY_IDS}
        fuente("sensor.deye_battery_power", "unavailable")
        await hass.async_block_till_done()
        await avanzar(30)
        comprobar({k: valor(k) for k in ENTITY_IDS} == antes, "mientras no hay dato no se cuenta nada")
        comprobar(hass.states.get(ENTITY_IDS["neto_total"]).state not in ("unavailable", "unknown"),
                  "los sensores siguen disponibles con lo acumulado")

        # ── Carga con sol ──
        print("\n  · carga con sol")
        await potencias(-2000, -500)
        await avanzar(30)
        comprobar(casi(valor("coste_hoy"), VALLE + EXCEDENTE_FINAL),
                  f"1 kWh de sol cuesta el excedente con impuestos ({EXCEDENTE_FINAL:.5f} €)")
        comprobar(casi(valor("carga_red_hoy"), 1.0) and casi(valor("carga_hoy"), 2.0), "y no cuenta como carga de red")
        neto = PUNTA - VALLE - EXCEDENTE_FINAL
        comprobar(casi(valor("neto_hoy"), neto), f"neto del día = bruto − coste ({valor('neto_hoy')})")

        # ── Valores en kW ──
        fuente("sensor.deye_battery_power", 1.5, "kW")
        await hass.async_block_till_done()
        comprobar(contador().entradas.bateria_w == 1500, "una fuente en kW se pasa a W")

        # ── Hueco largo (HA colgado o equipo suspendido) ──
        print("\n  · hueco largo")
        await potencias(1000, 0)
        antes = {k: valor(k) for k in ENTITY_IDS}
        reloj.t += timedelta(hours=3)
        contador().async_actualizar()
        await hass.async_block_till_done()
        comprobar({k: valor(k) for k in ENTITY_IDS} == antes, "un intervalo de 3 h sin refrescos no se cuenta")

        # ── Medianoche ──
        print("\n  · medianoche")
        total_antes = valor("neto_total")
        llano_antes = valor("descarga_llano_total")
        reloj.t = _local("2026-10-13T23:50:00")
        contador().async_actualizar()  # hueco largo: no cuenta
        await periodo("Llano", LLANO)
        await potencias(1200, 0)
        await avanzar(20)  # 23:50 → 00:10
        diez = 1.2 * 10 / 60
        comprobar(contador().acumulados.dia == "2026-10-14", "a medianoche cambia el día")
        comprobar(casi(valor("descarga_llano_hoy"), diez),
                  f"hoy solo cuenta lo de después de medianoche ({valor('descarga_llano_hoy')} kWh)")
        comprobar(casi(valor("descarga_llano_total"), llano_antes + 2 * diez),
                  "el total cuenta los 20 minutos")
        comprobar(casi(valor("neto_total"), total_antes + 2 * diez * LLANO), "y el neto total también")
        comprobar(valor("coste_hoy") == 0 and valor("carga_hoy") == 0, "lo de cargar del día anterior vuelve a 0")
        hoy = hass.states.get(ENTITY_IDS["neto_hoy"])
        comprobar(hoy.attributes.get("last_reset", "").startswith("2026-10-14T00:00:00"),
                  f"last_reset pasa a la nueva medianoche ({hoy.attributes.get('last_reset')})")

        await potencias(-3000, -100)
        await avanzar(60)
        comprobar(valor("neto_hoy") < 0, f"un día en que cuesta más cargar que lo ahorrado sale negativo ({valor('neto_hoy')})")

        # ── Recarga y reinicio ──
        print("\n  · recarga y reinicio")
        antes = {k: valor(k) for k in ENTITY_IDS}
        await hass.config_entries.async_reload(entrada.entry_id)
        await hass.async_block_till_done()
        comprobar({k: valor(k) for k in ENTITY_IDS} == antes, "tras recargar, todo sigue igual")
        guardado = json.loads((directorio / ".storage" / DOMINIO).read_text("utf-8"))
        comprobar(guardado["data"]["entry_id"] == entrada.entry_id
                  and casi(guardado["data"]["total"]["neto"], antes["neto_total"]),
                  "lo acumulado está en .storage/ahorro_bateria")

        await hass.config_entries.async_unload(entrada.entry_id)
        await hass.async_block_till_done()
        reloj.t += timedelta(hours=2)  # HA parado dos horas
        await hass.config_entries.async_setup(entrada.entry_id)
        await hass.async_block_till_done()
        comprobar({k: valor(k) for k in ENTITY_IDS} == antes, "el tiempo con HA parado no se cuenta")
        await avanzar(60)
        comprobar(casi(valor("carga_hoy"), antes["carga_hoy"] + 3.0), "y al volver sigue contando")

        # ── Configurar: corregir totales ──
        print("\n  · Configurar")
        menu = await hass.config_entries.options.async_init(entrada.entry_id)
        comprobar(menu.get("type") == "menu" and set(menu.get("menu_options", [])) == {"fuentes", "acumulados"},
                  "Configurar ofrece cambiar entidades o corregir totales")
        paso = await hass.config_entries.options.async_configure(menu["flow_id"], {"next_step_id": "acumulados"})
        sugeridos = {str(k): (k.description or {}).get("suggested_value") for k in paso["data_schema"].schema}
        comprobar(casi(sugeridos["neto"], valor("neto_total")), "el formulario sale con los totales actuales")
        hoy_antes = valor("neto_hoy")
        fin = await hass.config_entries.options.async_configure(
            paso["flow_id"], {**{k: sugeridos[k] for k in sugeridos}, "neto": 45.5}
        )
        await hass.async_block_till_done()
        comprobar(fin.get("type") == "create_entry" and casi(valor("neto_total"), 45.5),
                  "corregir el neto total lo cambia en el momento")
        comprobar(valor("neto_hoy") == hoy_antes, "y no toca lo de hoy")

        # ── Configurar: cambiar entidades ──
        menu = await hass.config_entries.options.async_init(entrada.entry_id)
        paso = await hass.config_entries.options.async_configure(menu["flow_id"], {"next_step_id": "fuentes"})
        sin_iva = {k: v for k, v in fuentes.items() if k not in ("iva", "impuesto_electrico")}
        antes = {k: valor(k) for k in ENTITY_IDS}
        fin = await hass.config_entries.options.async_configure(paso["flow_id"], sin_iva)
        await hass.async_block_till_done()
        comprobar(fin.get("type") == "create_entry" and "iva" not in entrada.options,
                  "se puede quitar una entidad opcional")
        comprobar({k: valor(k) for k in ENTITY_IDS} == antes, "cambiar entidades no pierde lo acumulado")
        comprobar(contador().entradas.iva == 0 and contador().entradas.completas,
                  "sin IVA configurado se calcula con 0 %")

        # ── Diagnóstico ──
        from custom_components.ahorro_bateria.diagnostics import async_get_config_entry_diagnostics

        diagnostico = await async_get_config_entry_diagnostics(hass, entrada)
        comprobar(json.dumps(diagnostico) and "acumulados" in diagnostico and "entradas" in diagnostico,
                  "el diagnóstico se genera y es JSON")

        # ── Borrar y volver a dar de alta ──
        print("\n  · borrar y volver a dar de alta")
        total = valor("neto_total")
        await hass.config_entries.async_remove(entrada.entry_id)
        await hass.async_block_till_done()
        comprobar((directorio / ".storage" / DOMINIO).exists(), "al borrar, lo acumulado se queda en disco")
        flujo = await hass.config_entries.flow.async_init(DOMINIO, context={"source": "user"})
        paso = await hass.config_entries.flow.async_configure(flujo["flow_id"], fuentes)
        sugeridos = {str(k): (k.description or {}).get("suggested_value") for k in paso["data_schema"].schema}
        comprobar(casi(sugeridos.get("neto") or 0, total), f"el alta nueva propone lo que había ({sugeridos.get('neto')})")
        await hass.config_entries.flow.async_configure(paso["flow_id"], {k: sugeridos[k] for k in sugeridos})
        await hass.async_block_till_done()
        nueva = hass.config_entries.async_entries(DOMINIO)[0]
        reales = {
            e.unique_id.removeprefix(f"{DOMINIO}_"): e.entity_id
            for e in er.async_entries_for_config_entry(er.async_get(hass), nueva.entry_id)
        }
        comprobar(reales == ENTITY_IDS, "y las entidades recuperan sus entity_id (sin _2)")
        comprobar(casi(valor("neto_total"), total), "con el total de antes")

        # ── Avisos de HA ──
        propios = [m for m in registros.mensajes
                   if DOMINIO in m and "has not been tested by Home Assistant" not in m]
        comprobar(not propios, f"ningún aviso ni error de la integración en el log {propios or ''}")
    finally:
        await hass.async_stop(force=True)
        logging.getLogger().removeHandler(registros)


def test_home_assistant() -> None:
    try:
        import homeassistant  # noqa: F401
    except ImportError:
        print("\nHome Assistant no instalado: se saltan las pruebas de integración")
        return

    print("\nIntegración en un Home Assistant real")
    directorio = Path(tempfile.mkdtemp(prefix="ahorro_bateria_"))
    try:
        (directorio / "custom_components").mkdir()
        (directorio / "custom_components" / DOMINIO).symlink_to(BASE)
        asyncio.run(_recorrido(directorio))
    finally:
        shutil.rmtree(directorio, ignore_errors=True)


if __name__ == "__main__":
    test_ficheros()
    test_calculo()
    test_home_assistant()
    print()
    if fallos:
        print(f"{len(fallos)} FALLOS:")
        for f in fallos:
            print(f"  - {f}")
    else:
        print("Todo OK")
    # os._exit y no sys.exit: con HA 2026.9/2026.10 y el Python 3.14.7 del
    # venv, el intérprete da un segfault al cerrarse si hay cualquier entrada
    # de configuración cargada (lo mismo pasa en las demás integraciones).
    sys.stdout.flush()
    sys.stderr.flush()
    import os

    os._exit(1 if fallos else 0)
