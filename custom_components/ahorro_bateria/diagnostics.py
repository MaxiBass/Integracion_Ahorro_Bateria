"""Diagnóstico descargable (Ajustes → Dispositivos y servicios → la entrada →
⋮ → Descargar diagnóstico): entidades de origen, lo que valen ahora y lo
acumulado. No hay credenciales que ocultar."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .contador import ContadorAhorro


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry[ContadorAhorro]
) -> dict[str, Any]:
    return {
        "opciones": dict(entry.options),
        "datos": dict(entry.data),
        **entry.runtime_data.diagnostico(),
    }
