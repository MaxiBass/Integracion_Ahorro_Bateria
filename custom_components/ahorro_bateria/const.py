"""Constantes de Ahorro Batería."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "ahorro_bateria"

# Entidades de origen: van en las opciones de la entrada (se cambian en
# Configurar sin perder lo acumulado).
CONF_BATERIA = "bateria"
CONF_BATERIA_POSITIVA_DESCARGA = "bateria_positiva_descarga"
CONF_RED = "red"
CONF_RED_POSITIVA_IMPORTA = "red_positiva_importa"
CONF_PRECIO_COMPRA = "precio_compra"
CONF_PRECIO_VENTA = "precio_venta"
CONF_IVA = "iva"
CONF_IMPUESTO_ELECTRICO = "impuesto_electrico"
CONF_PERIODO = "periodo"
CONF_CONSUMO = "consumo"

FUENTES = (
    CONF_BATERIA,
    CONF_RED,
    CONF_PRECIO_COMPRA,
    CONF_PRECIO_VENTA,
    CONF_IVA,
    CONF_IMPUESTO_ELECTRICO,
    CONF_PERIODO,
    CONF_CONSUMO,
)

# Lo acumulado antes de instalar la integración: va en los datos de la
# entrada y solo se usa la primera vez (después manda lo guardado en disco).
CONF_INICIALES = "iniciales"

# Si existen, el formulario de alta sale relleno con estas entidades (las de
# un inversor Deye con la integración Solarman y las plantillas de casa).
SUGERIDAS = {
    CONF_BATERIA: "sensor.deye_battery_power",
    CONF_RED: "sensor.deye_grid_ct_power",
    CONF_PRECIO_COMPRA: "sensor.factura_luz",
    CONF_PRECIO_VENTA: "input_number.precio_excedentes",
    CONF_IVA: "input_number.precio_iva",
    CONF_IMPUESTO_ELECTRICO: "input_number.precio_impuestos_electricidad",
    CONF_PERIODO: "sensor.periodo_tarifario",
    CONF_CONSUMO: "sensor.deye_load_power",
}

PERIODOS = ("punta", "llano", "valle")
# Estado del sensor de periodo (en minúsculas) → periodo. Admite también la
# nomenclatura P1/P2/P3 de la tarifa 2.0TD.
ALIAS_PERIODO = {
    "punta": "punta",
    "p1": "punta",
    "llano": "llano",
    "p2": "llano",
    "valle": "valle",
    "p3": "valle",
}

# Cada cuánto se cierra el intervalo en curso y se refrescan los sensores,
# aunque las fuentes no cambien (el inversor no repite un valor que no ha
# cambiado, ver DECISIONES §4).
INTERVALO_REFRESCO = timedelta(seconds=60)
# Un intervalo más largo que esto no se cuenta: solo pasa si HA se ha
# quedado colgado o el equipo ha estado suspendido, y no hay forma de saber
# qué pasó mientras tanto.
MAX_INTERVALO = timedelta(minutes=10)
# Retraso de la escritura en disco tras cada cambio.
RETRASO_GUARDADO = 60

VERSION_ALMACEN = 1
