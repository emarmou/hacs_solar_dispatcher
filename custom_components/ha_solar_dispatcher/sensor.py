"""Sensor platform for the Solar Dispatcher integration."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SolarDispatcherConfigEntry
from .coordinator import SolarDispatcherCoordinator
from .entity import SolarDispatcherEntity

# Coordinator-based entities never make individual service calls, so unlimited
# parallel updates are safe.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarDispatcherConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Solar Dispatcher sensor entities from a config entry."""
    async_add_entities([SolarSurplusSensor(entry.runtime_data)])


class SolarSurplusSensor(SolarDispatcherEntity, SensorEntity):
    """Sensor that exposes the last computed available surplus.

    This value reflects the remaining dispatchable power after the algorithm
    has processed all configured devices in the current polling cycle.
    """

    _attr_translation_key = "surplus"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coordinator: SolarDispatcherCoordinator) -> None:
        """Initialize the surplus sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_surplus"

    @property
    def native_value(self) -> float | None:
        """Return the computed surplus in watts."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.surplus
