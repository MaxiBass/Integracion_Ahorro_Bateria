"""Constantes de Ahorro Solar (dominio ahorro_bateria)."""
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
# Término de potencia (para el tope de la compensación, si también la descuenta).
CONF_POTENCIA_PUNTA = "potencia_punta"
CONF_PRECIO_POTENCIA_PUNTA = "precio_potencia_punta"
CONF_POTENCIA_VALLE = "potencia_valle"
CONF_PRECIO_POTENCIA_VALLE = "precio_potencia_valle"

# Facturación (DECISIONES §13). También se cambian desde las entidades de
# configuración (switch/number), sin recargar.
CONF_MONEDERO = "monedero"
CONF_MONEDERO_ANTES_IMPUESTOS = "monedero_antes_impuestos"
CONF_TOPE_INCLUYE_POTENCIA = "tope_incluye_potencia"
CONF_DIA_FACTURACION = "dia_facturacion"
FACTURACION_POR_DEFECTO = {
    # Lo que dice la norma: lo que pasa del tope se pierde y el tope es
    # solo la energía. El monedero es cosa de cada comercializadora.
    CONF_MONEDERO: False,
    CONF_MONEDERO_ANTES_IMPUESTOS: True,
    CONF_TOPE_INCLUYE_POTENCIA: False,
    CONF_DIA_FACTURACION: 1,
}

FUENTES = (
    CONF_BATERIA,
    CONF_RED,
    CONF_PRECIO_COMPRA,
    CONF_PRECIO_VENTA,
    CONF_IVA,
    CONF_IMPUESTO_ELECTRICO,
    CONF_PERIODO,
    CONF_CONSUMO,
    CONF_POTENCIA_PUNTA,
    CONF_PRECIO_POTENCIA_PUNTA,
    CONF_POTENCIA_VALLE,
    CONF_PRECIO_POTENCIA_VALLE,
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
    CONF_POTENCIA_PUNTA: "input_number.potencia_contratada_punta",
    CONF_PRECIO_POTENCIA_PUNTA: "input_number.precio_potencia_contratada_punta",
    CONF_POTENCIA_VALLE: "input_number.potencia_contratada_valle",
    CONF_PRECIO_POTENCIA_VALLE: "input_number.precio_potencia_contratada_valle",
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
