"""Coordinator for the Solar Dispatcher integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ALLOWANCE_ENTITY,
    CONF_BATTERY_CHARGE_ENTITY,
    CONF_BATTERY_CHARGE_INVERT,
    CONF_BATTERY_STATE_ENTITY,
    CONF_DEVICE_ESTIMATED_POWER,
    CONF_DEVICE_ID,
    CONF_DEVICE_MIN_BATTERY_STATE,
    CONF_DEVICE_NAME,
    CONF_DEVICE_POWER_ENTITY,
    CONF_DEVICE_PRIORITY,
    CONF_DEVICE_SWITCH_ENTITY,
    CONF_DEVICES,
    CONF_GRID_ENTITY,
    CONF_GRID_INVERT,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DISPATCH_PRIORITY_ORDER,
    DOMAIN,
    DispatchPriority,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class SolarDispatcherData:
    """Data returned by the Solar Dispatcher coordinator."""

    surplus: float
    battery_state: float


class SolarDispatcherCoordinator(DataUpdateCoordinator[SolarDispatcherData]):
    """Coordinator that runs the solar dispatch algorithm on a fixed schedule."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        # Store a typed reference so callers don't have to deal with the
        # base-class config_entry being Optional.
        self.entry: ConfigEntry = entry
        interval_seconds = entry.data.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.total_seconds()
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval_seconds),
            config_entry=entry,
        )
        # device_id -> bool: True means algorithm is allowed to control this device.
        # Virtual switch entities update this dict; the algorithm reads it each run.
        self.device_enabled: dict[str, bool] = {
            device[CONF_DEVICE_ID]: True
            for device in entry.options.get(CONF_DEVICES, [])
        }
        # device_id -> bool: True means the real switch is forced ON regardless of
        # available surplus. DispatcherOverrideSwitch entities update this dict.
        self.device_override: dict[str, bool] = {
            device[CONF_DEVICE_ID]: False
            for device in entry.options.get(CONF_DEVICES, [])
        }
        # Per-device mutable settings — initialised from config entry options but
        # kept up-to-date at runtime by the select / number entities so that users
        # can adjust values directly from the dashboard without reconfiguring.
        self.device_priority: dict[str, DispatchPriority] = {
            device[CONF_DEVICE_ID]: DispatchPriority(device[CONF_DEVICE_PRIORITY])
            for device in entry.options.get(CONF_DEVICES, [])
        }
        self.device_min_battery: dict[str, float] = {
            device[CONF_DEVICE_ID]: float(device[CONF_DEVICE_MIN_BATTERY_STATE])
            for device in entry.options.get(CONF_DEVICES, [])
        }
        self.device_estimated_power: dict[str, float] = {
            device[CONF_DEVICE_ID]: float(device[CONF_DEVICE_ESTIMATED_POWER])
            for device in entry.options.get(CONF_DEVICES, [])
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_float(
        self, entity_id: str | None, *, default: float = 0.0
    ) -> float | None:
        """Read a numeric state from a HA entity.

        Returns None when the entity is unavailable or its state is non-numeric.
        Returns *default* when *entity_id* is None (optional entity not configured).
        """
        if not entity_id:
            return default

        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None

        try:
            return float(state.state)
        except ValueError:
            _LOGGER.warning(
                "Entity '%s' has non-numeric state '%s'", entity_id, state.state
            )
            return None

    def _get_actual_power(self, device: dict, fallback: float) -> float:
        """Return the actual measured power of a device.

        Falls back to the configured estimated power when no measurement
        entity is set or the entity is currently unavailable.
        """
        power_entity = device.get(CONF_DEVICE_POWER_ENTITY)
        if not power_entity:
            return float(fallback)
        value = self._read_float(power_entity)
        if value is None:
            _LOGGER.debug(
                "Power entity '%s' unavailable, using estimated power %dW",
                power_entity,
                fallback,
            )
            return float(fallback)
        return value

    async def _turn_on(self, entity_id: str) -> None:
        """Call the switch.turn_on service for a real switch entity."""
        await self.hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {"entity_id": entity_id},
        )

    async def _turn_off(self, entity_id: str) -> None:
        """Call the switch.turn_off service for a real switch entity."""
        await self.hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_OFF,
            {"entity_id": entity_id},
        )

    # ------------------------------------------------------------------
    # Dispatch algorithm
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> SolarDispatcherData:
        """Run the solar dispatch algorithm.

        Reads the configured energy inputs, computes the available surplus,
        then iterates through configured devices sorted by priority and
        decides whether to turn each real switch ON or OFF.
        """
        data = self.entry.data
        options = self.entry.options

        # --- Grid power (mandatory) ---
        grid_value = self._read_float(data.get(CONF_GRID_ENTITY))
        if grid_value is None:
            raise UpdateFailed(
                f"Grid power entity '{data.get(CONF_GRID_ENTITY)}' is unavailable"
            )
        if data.get(CONF_GRID_INVERT, False):
            grid_value = -grid_value

        # --- Battery charging power (optional) ---
        batt_power = 0.0
        if batt_entity := data.get(CONF_BATTERY_CHARGE_ENTITY):
            batt_value = self._read_float(batt_entity)
            if batt_value is not None:
                if data.get(CONF_BATTERY_CHARGE_INVERT, False):
                    batt_value = -batt_value
                batt_power = batt_value

        # --- Battery state of charge % (optional, defaults to 100 when absent) ---
        batt_state_pct = 100.0
        if batt_state_entity := data.get(CONF_BATTERY_STATE_ENTITY):
            value = self._read_float(batt_state_entity)
            if value is not None:
                batt_state_pct = value

        # --- Allowance from an input_number/number entity (optional) ---
        allowance = 0.0
        if allowance_entity := data.get(CONF_ALLOWANCE_ENTITY):
            value = self._read_float(allowance_entity)
            if value is not None:
                allowance = value

        # --- Available surplus ---
        # surplus = grid_power + battery_charge_power + allowance
        # All three are signed: positive means power is available/exporting.
        surplus = grid_value + batt_power + allowance

        _LOGGER.debug(
            "Grid: %.0fW  Battery: %.0fW  Allowance: %.0fW"
            "  → Surplus: %.0fW  Battery: %.0f%%",
            grid_value,
            batt_power,
            allowance,
            surplus,
            batt_state_pct,
        )

        # --- Run the greedy priority-queue dispatch algorithm ---
        # Devices are sorted by DispatchPriority: highest priority first.
        # DISPATCH_PRIORITY_ORDER[0] = HIGHEST, so index 0 = smallest sort key.
        devices = sorted(
            options.get(CONF_DEVICES, []),
            key=lambda d: DISPATCH_PRIORITY_ORDER.index(
                self.device_priority.get(d[CONF_DEVICE_ID], DispatchPriority.NORMAL)
            ),
        )

        for device in devices:
            device_id: str = device[CONF_DEVICE_ID]
            device_name: str = device.get(CONF_DEVICE_NAME, device_id)

            if not self.device_enabled.get(device_id, True):
                _LOGGER.debug("Skipping '%s': not managed", device_name)
                continue

            real_switch: str = device[CONF_DEVICE_SWITCH_ENTITY]
            real_state = self.hass.states.get(real_switch)
            if real_state is None or real_state.state in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                _LOGGER.warning(
                    "Device '%s': switch entity '%s' is unavailable — skipping",
                    device_name,
                    real_switch,
                )
                continue

            is_on: bool = real_state.state == STATE_ON
            estimated_power: float = self.device_estimated_power.get(
                device_id, float(device[CONF_DEVICE_ESTIMATED_POWER])
            )
            min_batt: float = self.device_min_battery.get(
                device_id, float(device[CONF_DEVICE_MIN_BATTERY_STATE])
            )

            if self.device_override.get(device_id, False):
                # Override mode: force the real switch ON and deduct its power
                # from the remaining surplus so lower-priority devices see the
                # reduced budget.
                _LOGGER.debug("Override active for '%s': forcing ON", device_name)
                if not is_on:
                    await self._turn_on(real_switch)
                    surplus -= estimated_power
                continue

            if not is_on:
                # Device is currently OFF.
                # Turn it ON if there is enough surplus and battery condition is met.
                if estimated_power <= surplus and batt_state_pct >= min_batt:
                    _LOGGER.info(
                        "Turning ON '%s' (needs %dW, surplus %.0fW, batt %.0f%%)",
                        device_name,
                        estimated_power,
                        surplus,
                        batt_state_pct,
                    )
                    await self._turn_on(real_switch)
                    # Subtract estimated power from remaining surplus so that
                    # lower-priority devices see the reduced budget.
                    surplus -= estimated_power
                else:
                    _LOGGER.debug(
                        "Keeping '%s' OFF (needs %dW, surplus %.0fW, batt %.0f%%)",
                        device_name,
                        estimated_power,
                        surplus,
                        batt_state_pct,
                    )
            # Device is currently ON.
            # Turn it OFF if surplus is exhausted or battery threshold not met.
            elif surplus <= 0 or batt_state_pct < min_batt:
                actual_power = self._get_actual_power(device, estimated_power)
                _LOGGER.info(
                    "Turning OFF '%s' (consuming %.0fW, surplus %.0fW, batt %.0f%%)",
                    device_name,
                    actual_power,
                    surplus,
                    batt_state_pct,
                )
                await self._turn_off(real_switch)
                # Add back the power freed by turning this device off so
                # lower-priority devices can benefit from the freed budget.
                surplus += actual_power
            else:
                _LOGGER.debug(
                    "Keeping '%s' ON (consuming ~%dW, surplus %.0fW)",
                    device_name,
                    estimated_power,
                    surplus,
                )

        _LOGGER.debug("Remaining surplus after dispatch: %.0fW", surplus)
        return SolarDispatcherData(surplus=surplus, battery_state=batt_state_pct)
