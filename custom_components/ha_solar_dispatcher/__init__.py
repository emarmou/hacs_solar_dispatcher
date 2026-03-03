"""The Solar Dispatcher integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import SolarDispatcherCoordinator

type SolarDispatcherConfigEntry = ConfigEntry[SolarDispatcherCoordinator]

PLATFORMS: list[Platform] = [
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(
    hass: HomeAssistant, entry: SolarDispatcherConfigEntry
) -> bool:
    """Set up Solar Dispatcher from a config entry."""
    coordinator = SolarDispatcherCoordinator(hass, entry)

    # Perform the first refresh synchronously so that platform setup can
    # rely on coordinator.data being populated.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload the config entry whenever the user saves new options (e.g. adds
    # or removes a dispatched device) so that platform entities are recreated.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SolarDispatcherConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: SolarDispatcherConfigEntry
) -> None:
    """Reload the integration when the options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)
