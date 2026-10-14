"""Día en que empieza el periodo de facturación, para cambiarlo desde un panel."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_DIA_FACTURACION, DOMAIN
from .contador import ContadorAhorro, senal_actualizado
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[ContadorAhorro],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([DiaFacturacion(entry)])


class DiaFacturacion(NumberEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = CONF_DIA_FACTURACION
    _attr_icon = "mdi:calendar-start"
    _attr_native_min_value = 1
    _attr_native_max_value = 31
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, entry: ConfigEntry[ContadorAhorro]) -> None:
        self._contador = entry.runtime_data
        self._attr_unique_id = f"{DOMAIN}_{CONF_DIA_FACTURACION}"
        self.entity_id = "number.ahorro_dia_facturacion"
        self._attr_device_info = device_info(entry, "facturacion")

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, senal_actualizado(self._contador.entry.entry_id), self._al_actualizar
            )
        )

    @callback
    def _al_actualizar(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        return int(self._contador.opcion(CONF_DIA_FACTURACION))

    async def async_set_native_value(self, value: float) -> None:
        await self._contador.async_cambiar_facturacion(CONF_DIA_FACTURACION, int(value))
