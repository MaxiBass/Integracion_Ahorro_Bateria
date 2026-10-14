"""Dispositivos de la integración (servicios, no aparatos)."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN


# Un dispositivo por cosa, para que no se mezclen en la ficha de la
# integración. La batería conserva el identificador de la v0.1.0.
DISPOSITIVOS = {
    "bateria": "Ahorro batería",
    "placas": "Ahorro placas",
    "instalacion": "Ahorro instalación",
    "facturacion": "Ahorro facturación",
}


def device_info(entry: ConfigEntry, grupo: str = "bateria") -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id if grupo == "bateria" else f"{entry.entry_id}_{grupo}")},
        name=DISPOSITIVOS[grupo],
        manufacturer="MaxiBass",
        model="Cálculo del ahorro",
        entry_type=DeviceEntryType.SERVICE,
    )
