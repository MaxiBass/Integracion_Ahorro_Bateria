"""Cálculo del ahorro de la batería y de las placas. No depende de Home Assistant.

Se compara, instante a instante, lo que cuesta la red en tres escenarios,
con el precio de ese instante:

1. Real: la red marca `g` W (positivo al importar).
2. Con placas y sin batería: si la batería entrega `b` W (positivo al
   descargar), sin ella la red habría marcado `g + b`: lo que dio la batería
   habría salido de la red, y lo que absorbió se habría exportado.
3. Sin placas ni batería: toda la casa tira de la red, así que la red habría
   marcado el consumo de la casa `c`.

Con `coste(x) = compra × importado(x) − venta × exportado(x)`:

    ahorro batería = coste(g + b) − coste(g)
    ahorro placas  = coste(c) − coste(g + b)
    ahorro total   = coste(c) − coste(g) = placas + batería

De la batería salen todos los casos: descarga hacia la casa (ahorra la
compra), descarga que acaba exportada (vale el excedente), carga con sol
(cuesta el excedente que no se vende) y carga desde la red (cuesta lo
comprado). Lo positivo (descargando) es el «ahorro bruto» y lo negativo
(cargando) el «coste de la carga».

Las placas ahorran lo que la casa gasta de su producción al precio de
compra, más lo exportado al precio del excedente. Las pérdidas del inversor
(también su consumo de noche) caen del lado de las placas: c no las lleva y
g + b sí. Detalle y ejemplos en docs/DECISIONES.md §2 y §10.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import PERIODOS

# Lo que se acumula por día y en total. "bruto", "coste" y "placas" en €,
# el resto en kWh.
CLAVES = (
    "bruto",
    "coste",
    "descarga_punta",
    "descarga_llano",
    "descarga_valle",
    "carga",
    "carga_red",
    "placas",
)
# El total además lleva el neto de la batería, que no siempre es bruto −
# coste: puede arrancar con el valor de otro sistema o corregirse a mano.
CLAVES_TOTAL = ("neto", *CLAVES)
# Lo que se puede fijar al dar de alta o corregir en Configurar.
CLAVES_CORREGIBLES = ("neto", "placas", "descarga_punta", "descarga_llano", "descarga_valle", "carga")


@dataclass(frozen=True)
class Entradas:
    """Valores de las fuentes durante un intervalo.

    Potencias en W ya con el signo de la integración (batería positiva al
    descargar, red positiva al importar; el consumo de la casa, positivo).
    `precio_compra` en €/kWh con impuestos; `precio_venta` en €/kWh sin
    ellos (se le aplican `iva` e `impuesto_electrico`, en %). None = sin dato.
    """

    bateria_w: float | None = None
    red_w: float | None = None
    precio_compra: float | None = None
    precio_venta: float | None = None
    iva: float | None = 0.0
    impuesto_electrico: float | None = 0.0
    periodo: str | None = None
    consumo_w: float | None = None

    @property
    def completas(self) -> bool:
        """Hay lo necesario para la batería (las placas además piden el consumo)."""
        return None not in (
            self.bateria_w,
            self.red_w,
            self.precio_compra,
            self.precio_venta,
            self.iva,
            self.impuesto_electrico,
        )

    @property
    def precio_venta_final(self) -> float:
        """Lo que vale de verdad un kWh exportado.

        Con la compensación simplificada, el excedente descuenta del término
        de energía antes de impuestos, así que el impuesto eléctrico y el IVA
        se dejan de pagar también sobre él (DECISIONES §3).
        """
        return (
            self.precio_venta
            * (1 + self.impuesto_electrico / 100)
            * (1 + self.iva / 100)
        )

    def coste(self, red_w: float) -> float:
        """€/h que cuesta la red marcando `red_w` (negativo si se cobra)."""
        return (
            self.precio_compra * max(red_w, 0.0) - self.precio_venta_final * max(-red_w, 0.0)
        ) / 1000


def aportacion(entradas: Entradas, horas: float) -> dict[str, float]:
    """Lo que suma un intervalo de `horas` con las entradas constantes."""
    salida = dict.fromkeys(CLAVES, 0.0)
    if horas <= 0 or not entradas.completas:
        return salida

    bateria, red = entradas.bateria_w, entradas.red_w
    red_sin_bateria = red + bateria
    kwh_por_w = horas / 1000
    euros = (entradas.coste(red_sin_bateria) - entradas.coste(red)) * horas

    if bateria > 0:
        salida["bruto"] = euros
        if entradas.periodo in PERIODOS:
            salida[f"descarga_{entradas.periodo}"] = bateria * kwh_por_w
    elif bateria < 0:
        salida["coste"] = -euros
        salida["carga"] = -bateria * kwh_por_w
        # Lo que la red da de más por estar cargando la batería.
        salida["carga_red"] = (max(red, 0.0) - max(red_sin_bateria, 0.0)) * kwh_por_w

    if entradas.consumo_w is not None:
        salida["placas"] = (entradas.coste(entradas.consumo_w) - entradas.coste(red_sin_bateria)) * horas
    return salida


def _ceros(claves: tuple[str, ...]) -> dict[str, float]:
    return dict.fromkeys(claves, 0.0)


@dataclass
class Acumulados:
    """Lo acumulado hoy y desde siempre. `dia` es la fecha local (ISO) de `hoy`."""

    dia: str
    hoy: dict[str, float] = field(default_factory=lambda: _ceros(CLAVES))
    total: dict[str, float] = field(default_factory=lambda: _ceros(CLAVES_TOTAL))

    @classmethod
    def nuevos(cls, dia: str, iniciales: dict[str, Any] | None = None) -> Acumulados:
        acumulados = cls(dia=dia)
        acumulados.corregir(iniciales or {})
        return acumulados

    @classmethod
    def desde_dict(cls, datos: dict[str, Any]) -> Acumulados:
        # Las claves que falten (p. ej. de una versión anterior) arrancan en 0.
        return cls(
            dia=datos["dia"],
            hoy={**_ceros(CLAVES), **{k: float(v) for k, v in datos.get("hoy", {}).items() if k in CLAVES}},
            total={
                **_ceros(CLAVES_TOTAL),
                **{k: float(v) for k, v in datos.get("total", {}).items() if k in CLAVES_TOTAL},
            },
        )

    def a_dict(self) -> dict[str, Any]:
        return {"dia": self.dia, "hoy": dict(self.hoy), "total": dict(self.total)}

    @property
    def neto_hoy(self) -> float:
        return self.hoy["bruto"] - self.hoy["coste"]

    @property
    def instalacion_hoy(self) -> float:
        return self.hoy["placas"] + self.neto_hoy

    @property
    def instalacion_total(self) -> float:
        return self.total["placas"] + self.total["neto"]

    def sumar(self, aporte: dict[str, float]) -> None:
        for clave in CLAVES:
            self.hoy[clave] += aporte[clave]
            self.total[clave] += aporte[clave]
        self.total["neto"] += aporte["bruto"] - aporte["coste"]

    def cambiar_de_dia(self, dia: str) -> None:
        self.dia = dia
        self.hoy = _ceros(CLAVES)

    def corregir(self, valores: dict[str, Any]) -> None:
        """Fija los totales indicados; lo de hoy no se toca."""
        for clave in CLAVES_CORREGIBLES:
            if valores.get(clave) is not None:
                self.total[clave] = float(valores[clave])
