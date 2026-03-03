"""Select platform for the Solar Dispatcher integration.

Each configured dispatch device gets a priority select entity that lets the
user change the device's dispatch priority directly from the HA dashboard
without going through the config flow.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import SolarDispatcherConfigEntry
from .const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_DEVICES,
    DISPATCH_PRIORITY_ORDER,
    DispatchPriority,
)
from .coordinator import SolarDispatcherCoordinator
from .entity import SolarDispatcherEntity

_LOGGER = logging.getLogger(__name__)

# Coordinator-based entities; no individual polling needed.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarDispatcherConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one priority select per configured dispatch device."""
    coordinator = entry.runtime_data
    devices = entry.options.get(CONF_DEVICES, [])
    async_add_entities(
        DispatcherPrioritySelect(coordinator, device) for device in devices
    )


class DispatcherPrioritySelect(SolarDispatcherEntity, SelectEntity, RestoreEntity):
    """Select entity that controls the dispatch priority for a device.

    The selected option is stored in the coordinator's ``device_priority`` dict
    so the dispatch algorithm picks it up on the next polling cycle.  The last
    known value is persisted via RestoreEntity so it survives HA restarts
    without requiring a config-entry reload.
    """

    _attr_options: list[str] = [p.value for p in DISPATCH_PRIORITY_ORDER]

    def __init__(
        self,
        coordinator: SolarDispatcherCoordinator,
        device_config: dict[str, Any],
    ) -> None:
        """Initialize the priority select."""
        super().__init__(coordinator)
        self._device_id: str = device_config[CONF_DEVICE_ID]
        device_name: str = device_config[CONF_DEVICE_NAME]
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{self._device_id}_priority"
        )
        self._attr_name = f"{device_name} priority"

    @property
    def current_option(self) -> str | None:
        """Return the currently selected priority."""
        return self.coordinator.device_priority.get(
            self._device_id, DispatchPriority.NORMAL
        ).value

    async def async_select_option(self, option: str) -> None:
        """Change the dispatch priority for this device."""
        self.coordinator.device_priority[self._device_id] = DispatchPriority(option)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore the last known priority on HA restart."""
        await super().async_added_to_hass()
        if (
            state := await self.async_get_last_state()
        ) is not None and state.state in self._attr_options:
            self.coordinator.device_priority[self._device_id] = DispatchPriority(
                state.state
            )
            _LOGGER.debug(
                "Restored priority for '%s': %s",
                self._attr_name,
                state.state,
            )
