"""Dispositivo de la integración (un servicio, no un aparato)."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN


def device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Ahorro batería",
        manufacturer="MaxiBass",
        model="Cálculo del ahorro",
        entry_type=DeviceEntryType.SERVICE,
    )
