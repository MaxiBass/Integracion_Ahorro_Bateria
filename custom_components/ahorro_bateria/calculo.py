"""Cálculo del ahorro de la batería. No depende de Home Assistant.

La idea es comparar la red tal como ha sido con la que habría habido sin la
batería. Si la batería entrega `b` W (positivo al descargar) y la red marca
`g` W (positivo al importar), sin la batería la red habría marcado `g + b`:
lo que dio la batería habría salido de la red, y lo que absorbió se habría
exportado. El ahorro es la diferencia de coste entre los dos casos:

    ahorro = compra × (importado_sin − importado) − venta × (exportado_sin − exportado)

Con una sola fórmula salen todos los casos:

- Descarga hacia la casa: ahorra lo que se habría comprado (positivo).
- Descarga que acaba exportada: vale lo que se cobra por excedente.
- Carga con sol: cuesta el excedente que se deja de vender (negativo).
- Carga desde la red: cuesta lo que se compra para cargarla.

Lo positivo (descargando) es el «ahorro bruto» y lo negativo (cargando) el
«coste de la carga»; el neto es la resta. Detalle y ejemplos en
docs/DECISIONES.md §2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import PERIODOS

# Lo que se acumula por día y en total. "bruto" y "coste" en €, el resto en kWh.
CLAVES = (
    "bruto",
    "coste",
    "descarga_punta",
    "descarga_llano",
    "descarga_valle",
    "carga",
    "carga_red",
)
# El total además lleva el neto, que no siempre es bruto − coste: puede
# arrancar con el valor de otro sistema o corregirse a mano.
CLAVES_TOTAL = ("neto", *CLAVES)
# Lo que se puede fijar al dar de alta o corregir en Configurar.
CLAVES_CORREGIBLES = ("neto", "descarga_punta", "descarga_llano", "descarga_valle", "carga")


@dataclass(frozen=True)
class Entradas:
    """Valores de las fuentes durante un intervalo.

    Potencias en W ya con el signo de la integración (batería positiva al
    descargar, red positiva al importar). `precio_compra` en €/kWh con
    impuestos; `precio_venta` en €/kWh sin ellos (se le aplican `iva` e
    `impuesto_electrico`, en %). None = sin dato.
    """

    bateria_w: float | None = None
    red_w: float | None = None
    precio_compra: float | None = None
    precio_venta: float | None = None
    iva: float | None = 0.0
    impuesto_electrico: float | None = 0.0
    periodo: str | None = None

    @property
    def completas(self) -> bool:
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


def aportacion(entradas: Entradas, horas: float) -> dict[str, float]:
    """Lo que suma un intervalo de `horas` con las entradas constantes."""
    salida = dict.fromkeys(CLAVES, 0.0)
    if horas <= 0 or not entradas.completas:
        return salida

    bateria, red = entradas.bateria_w, entradas.red_w
    red_sin = red + bateria
    importado, exportado = max(red, 0.0), max(-red, 0.0)
    importado_sin, exportado_sin = max(red_sin, 0.0), max(-red_sin, 0.0)
    kwh_por_w = horas / 1000
    euros = (
        entradas.precio_compra * (importado_sin - importado)
        - entradas.precio_venta_final * (exportado_sin - exportado)
    ) * kwh_por_w

    if bateria > 0:
        salida["bruto"] = euros
        if entradas.periodo in PERIODOS:
            salida[f"descarga_{entradas.periodo}"] = bateria * kwh_por_w
    elif bateria < 0:
        salida["coste"] = -euros
        salida["carga"] = -bateria * kwh_por_w
        # Lo que la red da de más por estar cargando la batería.
        salida["carga_red"] = (importado - importado_sin) * kwh_por_w
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
