"""Base entity class for the Solar Dispatcher integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SolarDispatcherCoordinator


class SolarDispatcherEntity(CoordinatorEntity[SolarDispatcherCoordinator]):
    """Base class shared by all Solar Dispatcher entities.

    Groups all entities under a single virtual service device whose name
    matches the config entry title chosen by the user.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: SolarDispatcherCoordinator) -> None:
        """Initialize the base entity."""
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )
