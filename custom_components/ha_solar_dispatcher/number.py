"""Number platform for the Solar Dispatcher integration.

Each configured dispatch device gets two number entities — one for the minimum
battery threshold and one for the estimated power draw — that can be adjusted
directly from the HA dashboard without going through the config flow.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberMode, RestoreNumber
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SolarDispatcherConfigEntry
from .const import (
    CONF_DEVICE_ESTIMATED_POWER,
    CONF_DEVICE_ID,
    CONF_DEVICE_MIN_BATTERY_STATE,
    CONF_DEVICE_NAME,
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
    """Set up min-battery and estimated-power number entities per dispatch device."""
    coordinator = entry.runtime_data
    devices = entry.options.get(CONF_DEVICES, [])
    async_add_entities(
        entity
        for device in devices
        for entity in (
            DispatcherMinBatteryNumber(coordinator, device),
            DispatcherEstimatedPowerNumber(coordinator, device),
        )
    )


class DispatcherMinBatteryNumber(SolarDispatcherEntity, RestoreNumber):
    """Number entity (slider) for the minimum battery state of a dispatch device.

    The algorithm will not turn this device on if the battery state of charge
    is below this threshold.  The value is stored in the coordinator's
    ``device_min_battery`` dict so the algorithm picks it up immediately.
    """

    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 100
    _attr_native_step: float = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = NumberDeviceClass.BATTERY
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator: SolarDispatcherCoordinator,
        device_config: dict[str, Any],
    ) -> None:
        """Initialize the minimum battery number."""
        super().__init__(coordinator)
        self._device_id: str = device_config[CONF_DEVICE_ID]
        device_name: str = device_config[CONF_DEVICE_NAME]
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{self._device_id}_min_battery"
        )
        self._attr_name = f"{device_name} min battery"
        # Seed from config so first coordinator cycle uses the right value
        # before RestoreEntity has a chance to restore a prior state.
        coordinator.device_min_battery.setdefault(
            self._device_id, float(device_config[CONF_DEVICE_MIN_BATTERY_STATE])
        )

    @property
    def native_value(self) -> float:
        """Return the current minimum battery threshold."""
        return self.coordinator.device_min_battery.get(self._device_id, 0.0)

    async def async_set_native_value(self, value: float) -> None:
        """Update the minimum battery threshold."""
        self.coordinator.device_min_battery[self._device_id] = value
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore the last known threshold on HA restart."""
        await super().async_added_to_hass()
        if (
            number_data := await self.async_get_last_number_data()
        ) is not None and number_data.native_value is not None:
            self.coordinator.device_min_battery[self._device_id] = float(
                number_data.native_value
            )
            _LOGGER.debug(
                "Restored min battery for '%s': %s%%",
                self._attr_name,
                number_data.native_value,
            )


class DispatcherEstimatedPowerNumber(SolarDispatcherEntity, RestoreNumber):
    """Number entity (slider) for the estimated power draw of a dispatch device.

    The value is used by the algorithm to deduct from the remaining surplus
    when this device is switched on (and as a fallback when no power sensor
    is configured).  Stored in the coordinator's ``device_estimated_power``
    dict so changes take effect immediately without a config-entry reload.
    """

    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 10000
    _attr_native_step: float = 10
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = NumberDeviceClass.POWER
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator: SolarDispatcherCoordinator,
        device_config: dict[str, Any],
    ) -> None:
        """Initialize the estimated power number."""
        super().__init__(coordinator)
        self._device_id: str = device_config[CONF_DEVICE_ID]
        device_name: str = device_config[CONF_DEVICE_NAME]
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{self._device_id}_estimated_power"
        )
        self._attr_name = f"{device_name} estimated power"
        coordinator.device_estimated_power.setdefault(
            self._device_id, float(device_config[CONF_DEVICE_ESTIMATED_POWER])
        )

    @property
    def native_value(self) -> float:
        """Return the current estimated power draw."""
        return self.coordinator.device_estimated_power.get(self._device_id, 0.0)

    async def async_set_native_value(self, value: float) -> None:
        """Update the estimated power draw."""
        self.coordinator.device_estimated_power[self._device_id] = value
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore the last known estimated power on HA restart."""
        await super().async_added_to_hass()
        if (
            number_data := await self.async_get_last_number_data()
        ) is not None and number_data.native_value is not None:
            self.coordinator.device_estimated_power[self._device_id] = float(
                number_data.native_value
            )
            _LOGGER.debug(
                "Restored estimated power for '%s': %sW",
                self._attr_name,
                number_data.native_value,
            )
