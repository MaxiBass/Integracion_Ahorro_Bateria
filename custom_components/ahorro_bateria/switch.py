"""Opciones de facturación como interruptores, para cambiarlas desde un panel.

Son las mismas opciones que en Configurar (DECISIONES §13): se guardan en la
entrada y se aplican sin recargar.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_MONEDERO, CONF_MONEDERO_ANTES_IMPUESTOS, CONF_TOPE_INCLUYE_POTENCIA, DOMAIN
from .contador import ContadorAhorro, senal_actualizado
from .entity import device_info

INTERRUPTORES = {
    CONF_MONEDERO: ("switch.ahorro_monedero", "mdi:wallet-outline"),
    CONF_MONEDERO_ANTES_IMPUESTOS: ("switch.ahorro_monedero_antes_impuestos", "mdi:receipt-text-outline"),
    CONF_TOPE_INCLUYE_POTENCIA: ("switch.ahorro_tope_incluye_potencia", "mdi:transmission-tower"),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[ContadorAhorro],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(OpcionFacturacion(entry, clave) for clave in INTERRUPTORES)


class OpcionFacturacion(SwitchEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry[ContadorAhorro], clave: str) -> None:
        self._contador = entry.runtime_data
        self._clave = clave
        self._attr_translation_key = clave
        self._attr_unique_id = f"{DOMAIN}_{clave}"
        self.entity_id, self._attr_icon = INTERRUPTORES[clave]
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
    def is_on(self) -> bool:
        return bool(self._contador.opcion(self._clave))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._contador.async_cambiar_facturacion(self._clave, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._contador.async_cambiar_facturacion(self._clave, False)
