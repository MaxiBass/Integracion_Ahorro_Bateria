"""Sensores de Ahorro Batería.

Los `entity_id` son fijos y coinciden con los de las plantillas YAML a las
que sustituye, para que el panel, el historial y las estadísticas sigan
igual (DECISIONES §6). No cambiarlos.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .calculo import Acumulados
from .const import DOMAIN
from .contador import ContadorAhorro, senal_actualizado
from .entity import device_info

EURO = "€"


@dataclass(frozen=True, kw_only=True)
class DescripcionAhorro(SensorEntityDescription):
    entity_id: str
    valor: Callable[[Acumulados], float]
    # Se pone a 0 cada medianoche.
    diario: bool = False
    atributos: Callable[[Acumulados], dict[str, Any]] | None = None


def _euros(clave: str, entity_id: str, valor, diario: bool, **extra) -> DescripcionAhorro:
    return DescripcionAhorro(
        key=clave,
        translation_key=clave,
        entity_id=entity_id,
        device_class=SensorDeviceClass.MONETARY,
        # Monetario solo admite `total`; los diarios llevan además last_reset.
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=EURO,
        suggested_display_precision=2,
        valor=valor,
        diario=diario,
        **extra,
    )


def _kwh(clave: str, entity_id: str, valor, diario: bool) -> DescripcionAhorro:
    return DescripcionAhorro(
        key=clave,
        translation_key=clave,
        entity_id=entity_id,
        device_class=SensorDeviceClass.ENERGY,
        # Solo crecen; la vuelta a 0 de los diarios la entiende HA como reinicio.
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        valor=valor,
        diario=diario,
    )


SENSORES: tuple[DescripcionAhorro, ...] = (
    _euros("neto_hoy", "sensor.ahorro_bateria_hoy", lambda a: a.neto_hoy, True),
    _euros(
        "neto_total",
        "sensor.ahorro_bateria_total",
        lambda a: a.total["neto"],
        False,
        atributos=lambda a: {
            "ahorro_bruto": round(a.total["bruto"], 4),
            "coste_carga": round(a.total["coste"], 4),
            "carga_red_kwh": round(a.total["carga_red"], 4),
        },
    ),
    _euros("bruto_hoy", "sensor.bateria_ahorro_bruto_hoy", lambda a: a.hoy["bruto"], True),
    _euros("coste_hoy", "sensor.bateria_coste_oportunidad_hoy", lambda a: a.hoy["coste"], True),
    _kwh("descarga_punta_hoy", "sensor.bateria_descarga_punta_kwh_hoy", lambda a: a.hoy["descarga_punta"], True),
    _kwh("descarga_llano_hoy", "sensor.bateria_descarga_llano_kwh_hoy", lambda a: a.hoy["descarga_llano"], True),
    _kwh("descarga_valle_hoy", "sensor.bateria_descarga_valle_kwh_hoy", lambda a: a.hoy["descarga_valle"], True),
    _kwh("descarga_punta_total", "sensor.bateria_total_kwh_punta", lambda a: a.total["descarga_punta"], False),
    _kwh("descarga_llano_total", "sensor.bateria_total_kwh_llano", lambda a: a.total["descarga_llano"], False),
    _kwh("descarga_valle_total", "sensor.bateria_total_kwh_valle", lambda a: a.total["descarga_valle"], False),
    _kwh("carga_total", "sensor.bateria_total_kwh_carga", lambda a: a.total["carga"], False),
    _kwh("carga_hoy", "sensor.bateria_carga_kwh_hoy", lambda a: a.hoy["carga"], True),
    _kwh("carga_red_hoy", "sensor.bateria_carga_red_kwh_hoy", lambda a: a.hoy["carga_red"], True),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[ContadorAhorro],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(SensorAhorro(entry, descripcion) for descripcion in SENSORES)


class SensorAhorro(SensorEntity):
    """Un valor de los acumulados. Siempre disponible: no depende de las fuentes."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: DescripcionAhorro

    def __init__(self, entry: ConfigEntry[ContadorAhorro], descripcion: DescripcionAhorro) -> None:
        self.entity_description = descripcion
        self._contador = entry.runtime_data
        # Una sola entrada por instalación (manifest), así que el unique_id
        # no lleva el entry_id: si se borra y se vuelve a dar de alta, las
        # entidades recuperan su entity_id.
        self._attr_unique_id = f"{DOMAIN}_{descripcion.key}"
        self.entity_id = descripcion.entity_id
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                senal_actualizado(self._contador.entry.entry_id),
                self._al_actualizar,
            )
        )

    @callback
    def _al_actualizar(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        return round(self.entity_description.valor(self._contador.acumulados), 4)

    @property
    def last_reset(self) -> datetime | None:
        descripcion = self.entity_description
        if descripcion.diario and descripcion.device_class is SensorDeviceClass.MONETARY:
            return dt_util.start_of_local_day(date.fromisoformat(self._contador.acumulados.dia))
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.atributos is None:
            return None
        return self.entity_description.atributos(self._contador.acumulados)
