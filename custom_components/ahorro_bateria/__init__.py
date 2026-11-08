"""Ahorro Solar (dominio ahorro_bateria): cuánto ahorran la batería y las
placas de una instalación solar, por separado, y el tope de la compensación
en cada periodo de facturación.

Sustituye al paquete YAML `calculo_ahorro_bateria` (plantillas, sumas de
Riemann, utility_meter, input_number y una automatización). Ver README y
docs/DECISIONES.md.
"""
from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .contador import ContadorAhorro, EntradaAhorro
from .entity import device_info

PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.NUMBER]


async def async_setup_entry(hass: HomeAssistant, entry: EntradaAhorro) -> bool:
    contador = ContadorAhorro(hass, entry)
    await contador.async_cargar()
    entry.runtime_data = contador

    dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, **device_info(entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    contador.async_arrancar()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EntradaAhorro) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_parar()
    return unload_ok
