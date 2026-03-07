"""Switch platform for the Solar Dispatcher integration.

Each configured dispatch device is represented by a virtual switch entity.
When the switch is ON the dispatch algorithm is allowed to control the
underlying real switch entity.  When the user turns it OFF the algorithm
stops managing the device and the real switch is immediately turned off.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN, SwitchEntity
from homeassistant.const import SERVICE_TURN_ON, STATE_OFF, STATE_ON
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from . import SolarDispatcherConfigEntry
from .const import (
    CONF_DEVICE_ESTIMATED_POWER,
    CONF_DEVICE_ID,
    CONF_DEVICE_MIN_BATTERY_STATE,
    CONF_DEVICE_NAME,
    CONF_DEVICE_PRIORITY,
    CONF_DEVICE_SWITCH_ENTITY,
    CONF_DEVICES,
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
    """Set up one managed switch and one override switch per configured dispatch device."""
    coordinator = entry.runtime_data
    devices = entry.options.get(CONF_DEVICES, [])
    async_add_entities(
        entity
        for device in devices
        for entity in (
            DispatcherSwitch(coordinator, device),
            DispatcherOverrideSwitch(coordinator, device),
        )
    )


class DispatcherSwitch(SolarDispatcherEntity, SwitchEntity, RestoreEntity):
    """Virtual switch that enables or disables coordinator management for one load.

    State semantics
    ---------------
    ON  — the dispatch algorithm is allowed to turn this device on/off.
    OFF — the coordinator ignores this device; its real switch is left in whatever
          state it is currently in and the algorithm will not touch it.

    The managed state is persisted across restarts via RestoreEntity.
    """

    _attr_translation_key = "managed"

    def __init__(
        self,
        coordinator: SolarDispatcherCoordinator,
        device_config: dict[str, Any],
    ) -> None:
        """Initialize the virtual dispatch switch."""
        super().__init__(coordinator)
        self._device_config = device_config
        self._device_id: str = device_config[CONF_DEVICE_ID]
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{self._device_id}"
        self._attr_name = device_config[CONF_DEVICE_NAME]

    async def async_added_to_hass(self) -> None:
        """Restore the last known enabled/disabled state on HA restart."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            is_enabled = last_state.state == STATE_ON
            self.coordinator.device_enabled[self._device_id] = is_enabled
            _LOGGER.debug(
                "Restored dispatch switch '%s': enabled=%s",
                self._attr_name,
                is_enabled,
            )

    @property
    def is_on(self) -> bool:
        """Return True when algorithm control is enabled for this device."""
        return self.coordinator.device_enabled.get(self._device_id, True)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable algorithm control for this device.

        The algorithm will decide whether to actually turn the real device on
        during the next polling cycle.
        """
        self.coordinator.device_enabled[self._device_id] = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop coordinator management for this device.

        The real switch is left in its current state; the coordinator will
        no longer touch it until management is re-enabled.
        """
        self.coordinator.device_enabled[self._device_id] = False
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose live dispatch configuration as state attributes."""
        return {
            "controlled_entity": self._device_config[CONF_DEVICE_SWITCH_ENTITY],
            "priority": self.coordinator.device_priority.get(
                self._device_id,
                self._device_config[CONF_DEVICE_PRIORITY],
            ),
            "estimated_power_w": self.coordinator.device_estimated_power.get(
                self._device_id,
                float(self._device_config[CONF_DEVICE_ESTIMATED_POWER]),
            ),
            "min_battery_state_pct": self.coordinator.device_min_battery.get(
                self._device_id,
                float(self._device_config[CONF_DEVICE_MIN_BATTERY_STATE]),
            ),
        }


class DispatcherOverrideSwitch(SolarDispatcherEntity, SwitchEntity, RestoreEntity):
    """Virtual switch that forces a dispatch device ON, bypassing the algorithm.

    State semantics
    ---------------
    ON  — the real switch is forced on regardless of available surplus or battery
          state.  The device's power draw is still deducted from the surplus
          budget so that lower-priority devices are not over-committed.
    OFF — the coordinator drives the device normally (subject to the managed switch).

    The override state is persisted across restarts via RestoreEntity.
    """

    _attr_translation_key = "override"

    def __init__(
        self,
        coordinator: SolarDispatcherCoordinator,
        device_config: dict[str, Any],
    ) -> None:
        """Initialize the override switch."""
        super().__init__(coordinator)
        self._device_config = device_config
        self._device_id: str = device_config[CONF_DEVICE_ID]
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{self._device_id}_override"
        )
        self._attr_name = f"{device_config[CONF_DEVICE_NAME]} override"

    async def async_added_to_hass(self) -> None:
        """Restore the last known override state on HA restart."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            is_override = last_state.state == STATE_ON
            self.coordinator.device_override[self._device_id] = is_override
            _LOGGER.debug(
                "Restored override switch '%s': override=%s",
                self._attr_name,
                is_override,
            )

        real_switch = self._device_config[CONF_DEVICE_SWITCH_ENTITY]

        @callback
        def _async_real_switch_state_changed(
            event: Event[EventStateChangedData],
        ) -> None:
            """Auto-disable override when real switch is turned off externally.

            The override is intended to counteract the coordinator's own off
            decisions.  When something other than the coordinator turns the
            real switch off, the override is cancelled so the real switch
            will not be forced back on by the next dispatch cycle.
            """
            old_state = event.data["old_state"]
            new_state = event.data["new_state"]

            # Only react to ON → OFF transitions.
            if (
                old_state is None
                or old_state.state != STATE_ON
                or new_state is None
                or new_state.state != STATE_OFF
            ):
                return

            if real_switch in self.coordinator.turning_off_by_coordinator:
                # The coordinator caused this transition; consume the marker
                # and leave the override in place.
                self.coordinator.turning_off_by_coordinator.discard(real_switch)
                _LOGGER.debug(
                    "Real switch '%s' turned off by coordinator; "
                    "keeping override for '%s'",
                    real_switch,
                    self._attr_name,
                )
                return

            # An external component turned the real switch off — cancel the
            # override so the coordinator will not immediately force it back on.
            _LOGGER.debug(
                "Real switch '%s' turned off externally; "
                "auto-disabling override for '%s'",
                real_switch,
                self._attr_name,
            )
            self.coordinator.device_override[self._device_id] = False
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, real_switch, _async_real_switch_state_changed
            )
        )

    @property
    def is_on(self) -> bool:
        """Return True when the device is forced ON regardless of the algorithm."""
        return self.coordinator.device_override.get(self._device_id, False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Force the real switch ON and bypass the dispatch algorithm."""
        self.coordinator.device_override[self._device_id] = True
        real_switch = self._device_config[CONF_DEVICE_SWITCH_ENTITY]
        await self.hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {"entity_id": real_switch},
        )
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Return the device to normal coordinator-driven control."""
        self.coordinator.device_override[self._device_id] = False
        self.async_write_ha_state()
