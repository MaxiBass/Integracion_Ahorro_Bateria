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

Tope de la compensación (§13): en cada periodo de facturación lo
compensado no puede pasar del término de energía (y, si la comercializadora
lo permite, también del de potencia). Durante el periodo se valora todo el
excedente; al cerrarlo, `cerrar_periodo` resta lo que pasó del tope en cada
escenario (real y sin batería; sin nada no hay excedente) según vaya a un
monedero o se pierda.
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
CLAVES_TOTAL = ("neto", *CLAVES, "ajuste_tope")
# Lo que se puede fijar al dar de alta o corregir en Configurar.
CLAVES_CORREGIBLES = ("neto", "placas", "descarga_punta", "descarga_llano", "descarga_valle", "carga")
# Lo que se acumula en el periodo de facturación en curso, en € sin
# impuestos: término de energía y compensación en cada escenario, y término
# de potencia.
CLAVES_PERIODO = ("energia_real", "comp_real", "energia_sb", "comp_sb", "potencia")


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
    # Término de potencia en €/día sin impuestos (None: no configurado).
    termino_potencia_dia: float | None = None

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
    def factor_impuestos(self) -> float:
        return (1 + self.impuesto_electrico / 100) * (1 + self.iva / 100)

    @property
    def precio_venta_final(self) -> float:
        """Lo que vale de verdad un kWh exportado.

        Con la compensación simplificada, el excedente descuenta del término
        de energía antes de impuestos, así que el impuesto eléctrico y el IVA
        se dejan de pagar también sobre él (DECISIONES §3).
        """
        return self.precio_venta * self.factor_impuestos

    def coste(self, red_w: float) -> float:
        """€/h que cuesta la red marcando `red_w` (negativo si se cobra)."""
        return (
            self.precio_compra * max(red_w, 0.0) - self.precio_venta_final * max(-red_w, 0.0)
        ) / 1000


def aportacion(entradas: Entradas, horas: float) -> dict[str, float]:
    """Lo que suma un intervalo de `horas` con las entradas constantes.

    Las claves de CLAVES van a hoy y al total; las de CLAVES_PERIODO, al
    periodo de facturación.
    """
    salida = dict.fromkeys(CLAVES + CLAVES_PERIODO, 0.0)
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

    compra_sin_impuestos = entradas.precio_compra / entradas.factor_impuestos
    for escenario, red_w in (("real", red), ("sb", red_sin_bateria)):
        salida[f"energia_{escenario}"] = compra_sin_impuestos * max(red_w, 0.0) * kwh_por_w
        salida[f"comp_{escenario}"] = entradas.precio_venta * max(-red_w, 0.0) * kwh_por_w
    if entradas.termino_potencia_dia is not None:
        salida["potencia"] = entradas.termino_potencia_dia * horas / 24
    return salida


@dataclass(frozen=True)
class Facturacion:
    """Cómo trata la comercializadora lo que pasa del tope (DECISIONES §13)."""

    monedero: bool = False
    monedero_antes_impuestos: bool = True
    tope_incluye_potencia: bool = False

    def valor_perdido(self, exceso: float, factor_impuestos: float) -> float:
        """Lo que la integración contó de más por `exceso` € (sin impuestos)
        de compensación por encima del tope.

        Durante el periodo cada € compensado se valoró con impuestos. Si va a
        un monedero que se descuenta antes de impuestos, vale eso mismo; si se
        descuenta del total de la factura, solo su valor sin impuestos; y si
        se pierde, nada.
        """
        if not self.monedero:
            return exceso * factor_impuestos
        if not self.monedero_antes_impuestos:
            return exceso * (factor_impuestos - 1)
        return 0.0


def resumen_periodo(periodo: dict[str, float], facturacion: Facturacion) -> dict[str, float]:
    """Tope, compensación y exceso del periodo, en € sin impuestos."""
    potencia = periodo["potencia"] if facturacion.tope_incluye_potencia else 0.0
    resumen = {"potencia": round(periodo["potencia"], 4)}
    for escenario in ("real", "sb"):
        tope = periodo[f"energia_{escenario}"] + potencia
        comp = periodo[f"comp_{escenario}"]
        resumen[f"tope_{escenario}"] = tope
        resumen[f"comp_{escenario}"] = comp
        resumen[f"exceso_{escenario}"] = max(0.0, comp - tope)
    resumen["energia"] = periodo["energia_real"]
    return resumen


def _ceros(claves: tuple[str, ...]) -> dict[str, float]:
    return dict.fromkeys(claves, 0.0)


@dataclass
class Acumulados:
    """Lo acumulado hoy y desde siempre. `dia` es la fecha local (ISO) de `hoy`."""

    dia: str
    hoy: dict[str, float] = field(default_factory=lambda: _ceros(CLAVES))
    total: dict[str, float] = field(default_factory=lambda: _ceros(CLAVES_TOTAL))
    # Periodo de facturación en curso: fecha local (ISO) en que empezó a
    # contarse (None: aún no se sabe) y lo acumulado en él.
    inicio_periodo: str | None = None
    periodo: dict[str, float] = field(default_factory=lambda: _ceros(CLAVES_PERIODO))
    # Último periodo cerrado (para mostrarlo): resumen y ajuste aplicado.
    ultimo_periodo: dict[str, Any] | None = None

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
            inicio_periodo=datos.get("inicio_periodo"),
            periodo={
                **_ceros(CLAVES_PERIODO),
                **{k: float(v) for k, v in datos.get("periodo", {}).items() if k in CLAVES_PERIODO},
            },
            ultimo_periodo=datos.get("ultimo_periodo"),
        )

    def a_dict(self) -> dict[str, Any]:
        return {
            "dia": self.dia,
            "hoy": dict(self.hoy),
            "total": dict(self.total),
            "inicio_periodo": self.inicio_periodo,
            "periodo": dict(self.periodo),
            "ultimo_periodo": self.ultimo_periodo,
        }

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
        for clave in CLAVES_PERIODO:
            self.periodo[clave] += aporte.get(clave, 0.0)

    def cerrar_periodo(
        self, nuevo_inicio: str, facturacion: Facturacion, factor_impuestos: float, con_placas: bool
    ) -> dict[str, Any]:
        """Aplica el tope al periodo que acaba y empieza otro en `nuevo_inicio`.

        Lo que pasó del tope sin batería se lo descuentan las placas (eran
        sus excedentes); lo que pasó del tope de verdad se descuenta de la
        instalación. La batería se queda la diferencia: si sin ella se
        habría perdido más excedente, guardarlo valía más de lo contado.
        """
        resumen = resumen_periodo(self.periodo, facturacion)
        perdido_real = facturacion.valor_perdido(resumen["exceso_real"], factor_impuestos)
        perdido_sb = facturacion.valor_perdido(resumen["exceso_sb"], factor_impuestos)
        # Sin consumo no hay placas que ajustar, pero la batería se ajusta igual.
        self.total["neto"] += perdido_sb - perdido_real
        if con_placas:
            self.total["placas"] -= perdido_sb
        self.total["ajuste_tope"] -= perdido_real
        self.ultimo_periodo = {
            "inicio": self.inicio_periodo,
            "fin": nuevo_inicio,
            **{k: round(v, 4) for k, v in resumen.items()},
            "ajuste_instalacion": round(-perdido_real, 4),
            "ajuste_placas": round(-perdido_sb if con_placas else 0.0, 4),
            "ajuste_bateria": round(perdido_sb - perdido_real, 4),
        }
        self.inicio_periodo = nuevo_inicio
        self.periodo = _ceros(CLAVES_PERIODO)
        return self.ultimo_periodo

    def cambiar_de_dia(self, dia: str) -> None:
        self.dia = dia
        self.hoy = _ceros(CLAVES)

    def corregir(self, valores: dict[str, Any]) -> None:
        """Fija los totales indicados; lo de hoy no se toca."""
        for clave in CLAVES_CORREGIBLES:
            if valores.get(clave) is not None:
                self.total[clave] = float(valores[clave])
