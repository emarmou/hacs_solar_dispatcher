"""Constants for the Solar Dispatcher integration."""

from datetime import timedelta
from enum import StrEnum


class DispatchPriority(StrEnum):
    """Priority levels for dispatch devices.

    Devices with a higher priority are served surplus before lower-priority
    devices. The enum value is stored as a string in the config entry so it
    survives serialisation without custom JSON handling.
    """

    LOWEST = "lowest"
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    HIGHEST = "highest"


# Ordered from highest to lowest so a simple list-index lookup gives the sort
# key used by the dispatch algorithm (index 0 = highest priority).
DISPATCH_PRIORITY_ORDER: list[DispatchPriority] = [
    DispatchPriority.HIGHEST,
    DispatchPriority.HIGH,
    DispatchPriority.NORMAL,
    DispatchPriority.LOW,
    DispatchPriority.LOWEST,
]

DOMAIN = "ha_solar_dispatcher"

# Fixed polling interval for the dispatch algorithm
DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)

# ── Initial config entry data keys ──────────────────────────────────────────
CONF_SCAN_INTERVAL = "scan_interval"
CONF_GRID_ENTITY = "grid_entity"
CONF_GRID_INVERT = "grid_invert"
CONF_BATTERY_CHARGE_ENTITY = "battery_charge_entity"
CONF_BATTERY_CHARGE_INVERT = "battery_charge_invert"
CONF_BATTERY_STATE_ENTITY = "battery_state_entity"
CONF_ALLOWANCE_ENTITY = "allowance_entity"

# ── Options keys ─────────────────────────────────────────────────────────────
CONF_DEVICES = "devices"

# ── Per-device config keys ───────────────────────────────────────────────────
CONF_DEVICE_ID = "id"
CONF_DEVICE_NAME = "name"
CONF_DEVICE_PRIORITY = "priority"
CONF_DEVICE_MIN_BATTERY_STATE = "min_battery_state"
CONF_DEVICE_ESTIMATED_POWER = "estimated_power"
CONF_DEVICE_SWITCH_ENTITY = "switch_entity"
CONF_DEVICE_POWER_ENTITY = "power_entity"
