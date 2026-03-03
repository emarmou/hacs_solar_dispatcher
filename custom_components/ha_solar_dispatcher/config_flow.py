"""Config flow for the Solar Dispatcher integration."""

from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

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

# ── Schemas ───────────────────────────────────────────────────────────────────

# Initial / reconfigure config form.
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_GRID_ENTITY): EntitySelector(
            EntitySelectorConfig(
                domain="sensor",
                device_class=SensorDeviceClass.POWER,
            )
        ),
        vol.Required(CONF_GRID_INVERT, default=False): BooleanSelector(),
        vol.Optional(CONF_BATTERY_CHARGE_ENTITY): EntitySelector(
            EntitySelectorConfig(
                domain="sensor",
                device_class=SensorDeviceClass.POWER,
            )
        ),
        vol.Optional(CONF_BATTERY_CHARGE_INVERT, default=False): BooleanSelector(),
        vol.Optional(CONF_BATTERY_STATE_ENTITY): EntitySelector(
            EntitySelectorConfig(
                domain="sensor",
                device_class=SensorDeviceClass.BATTERY,
            )
        ),
        vol.Optional(CONF_ALLOWANCE_ENTITY): EntitySelector(
            EntitySelectorConfig(domain=["input_number", "number"])
        ),
        vol.Required(
            CONF_SCAN_INTERVAL, default=int(DEFAULT_SCAN_INTERVAL.total_seconds())
        ): NumberSelector(
            NumberSelectorConfig(
                min=10,
                max=3600,
                step=1,
                unit_of_measurement="s",
                mode=NumberSelectorMode.BOX,
            )
        ),
    }
)

# Per-device configuration form (shared by add and edit steps).
DEVICE_FORM_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_NAME): TextSelector(),
        vol.Required(
            CONF_DEVICE_PRIORITY, default=DispatchPriority.NORMAL
        ): SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(value=p.value, label=p.value.capitalize())
                    for p in DISPATCH_PRIORITY_ORDER
                ],
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="dispatch_priority",
            )
        ),
        vol.Required(CONF_DEVICE_MIN_BATTERY_STATE, default=0): NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=100,
                step=1,
                unit_of_measurement="%",
                mode=NumberSelectorMode.SLIDER,
            )
        ),
        vol.Required(CONF_DEVICE_ESTIMATED_POWER): NumberSelector(
            NumberSelectorConfig(
                min=1,
                max=100000,
                step=1,
                unit_of_measurement="W",
                mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Required(CONF_DEVICE_SWITCH_ENTITY): EntitySelector(
            EntitySelectorConfig(domain="switch")
        ),
        vol.Optional(CONF_DEVICE_POWER_ENTITY): EntitySelector(
            EntitySelectorConfig(
                domain="sensor",
                device_class=SensorDeviceClass.POWER,
            )
        ),
    }
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _entity_exists(hass: HomeAssistant, entity_id: str) -> bool:
    """Return True if *entity_id* is registered or has a current state."""
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    registry = er.async_get(hass)
    return (
        registry.async_get(entity_id) is not None
        or hass.states.get(entity_id) is not None
    )


def _validate_entities(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> dict[str, str]:
    """Validate that every specified entity ID resolves in HA."""
    for key in (
        CONF_GRID_ENTITY,
        CONF_BATTERY_CHARGE_ENTITY,
        CONF_BATTERY_STATE_ENTITY,
        CONF_ALLOWANCE_ENTITY,
    ):
        if (entity_id := user_input.get(key)) and not _entity_exists(hass, entity_id):
            return {"base": "entity_not_found"}
    return {}


def _parse_main_config(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalise the main config form values for storage."""
    data: dict[str, Any] = {
        CONF_GRID_ENTITY: user_input[CONF_GRID_ENTITY],
        CONF_GRID_INVERT: user_input.get(CONF_GRID_INVERT, False),
        CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
    }
    if batt_entity := user_input.get(CONF_BATTERY_CHARGE_ENTITY):
        data[CONF_BATTERY_CHARGE_ENTITY] = batt_entity
        data[CONF_BATTERY_CHARGE_INVERT] = user_input.get(
            CONF_BATTERY_CHARGE_INVERT, False
        )
    if batt_state := user_input.get(CONF_BATTERY_STATE_ENTITY):
        data[CONF_BATTERY_STATE_ENTITY] = batt_state
    if allowance := user_input.get(CONF_ALLOWANCE_ENTITY):
        data[CONF_ALLOWANCE_ENTITY] = allowance
    return data


def _parse_device_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalise device form values (NumberSelector returns floats → convert to int)."""
    parsed: dict[str, Any] = {
        CONF_DEVICE_NAME: user_input[CONF_DEVICE_NAME],
        CONF_DEVICE_PRIORITY: DispatchPriority(user_input[CONF_DEVICE_PRIORITY]),
        CONF_DEVICE_MIN_BATTERY_STATE: int(user_input[CONF_DEVICE_MIN_BATTERY_STATE]),
        CONF_DEVICE_ESTIMATED_POWER: int(user_input[CONF_DEVICE_ESTIMATED_POWER]),
        CONF_DEVICE_SWITCH_ENTITY: user_input[CONF_DEVICE_SWITCH_ENTITY],
    }
    if power_entity := user_input.get(CONF_DEVICE_POWER_ENTITY):
        parsed[CONF_DEVICE_POWER_ENTITY] = power_entity
    return parsed


# ── Config flow ───────────────────────────────────────────────────────────────


class SolarDispatcherConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration flow for Solar Dispatcher."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> SolarDispatcherOptionsFlow:
        """Return the options flow for managing dispatch devices."""
        return SolarDispatcherOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial setup step.

        When the integration is already configured, routes to the add-device
        step so the user can add a dispatch device directly from the
        integrations page '+' button instead of seeing an 'already configured'
        error.
        """
        if self._async_current_entries():
            return await self.async_step_add_device(user_input)

        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_entities(self.hass, user_input)

            if not errors:
                # Use the grid entity ID as unique_id so that the same grid
                # meter cannot be tracked by two dispatcher instances.
                await self.async_set_unique_id(user_input[CONF_GRID_ENTITY])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="Solar Dispatcher",
                    data=_parse_main_config(user_input),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_add_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a dispatch device to the existing Solar Dispatcher entry.

        Shown when the user clicks the '+' button on the integrations page
        while the integration is already configured.
        """
        if user_input is None:
            return self.async_show_form(
                step_id="add_device",
                data_schema=DEVICE_FORM_SCHEMA,
            )

        entry = self._async_current_entries()[0]
        devices = list(entry.options.get(CONF_DEVICES, []))
        devices.append(
            {CONF_DEVICE_ID: str(uuid.uuid4()), **_parse_device_input(user_input)}
        )
        # Updating options triggers the update listener which reloads the entry
        # so the new virtual switch entity is created automatically.
        self.hass.config_entries.async_update_entry(
            entry, options={CONF_DEVICES: devices}
        )
        return self.async_abort(reason="device_added")

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow the user to update the energy inputs without removing the entry."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            errors = _validate_entities(self.hass, user_input)

            if not errors:
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data_updates=_parse_main_config(user_input),
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, reconfigure_entry.data
            ),
            errors=errors,
        )


# ── Options flow ──────────────────────────────────────────────────────────────


class SolarDispatcherOptionsFlow(OptionsFlow):
    """Manage the dispatched device list via the options flow.

    Flow graph
    ----------
    init ──┬── add_device
           ├── select_edit ──► edit_device
           └── select_remove
    """

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialise with a mutable copy of the current device list."""
        self._devices: list[dict[str, Any]] = list(
            config_entry.options.get(CONF_DEVICES, [])
        )
        self._edit_device_id: str | None = None

    # -- helpers ---------------------------------------------------------------

    def _build_device_selector_schema(self) -> vol.Schema:
        """Build a form schema with a SelectSelector populated by current devices."""
        return vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(
                                label=d[CONF_DEVICE_NAME], value=d[CONF_DEVICE_ID]
                            )
                            for d in self._devices
                        ],
                        mode=SelectSelectorMode.LIST,
                    )
                )
            }
        )

    # -- main menu -------------------------------------------------------------

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the energy-input configuration form.

        This is the form shown when the user clicks the 'Configure' button on
        the Solar Dispatcher integration card.  It lets the user update the
        grid, battery, and allowance entities without removing the entry.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_entities(self.hass, user_input)
            if not errors:
                # Persist the updated energy-input settings directly on the
                # config entry data, then close the options dialog.
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=_parse_main_config(user_input),
                )
                return self.async_create_entry(data={CONF_DEVICES: self._devices})

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, self.config_entry.data
            ),
            errors=errors,
        )

    # -- add -------------------------------------------------------------------

    async def async_step_add_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a new dispatch device to the configuration."""
        if user_input is None:
            return self.async_show_form(
                step_id="add_device",
                data_schema=DEVICE_FORM_SCHEMA,
            )

        new_device: dict[str, Any] = {
            CONF_DEVICE_ID: str(uuid.uuid4()),
            **_parse_device_input(user_input),
        }
        self._devices.append(new_device)
        return self.async_create_entry(data={CONF_DEVICES: self._devices})

    # -- edit ------------------------------------------------------------------

    async def async_step_select_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose which device to edit."""
        if user_input is not None:
            self._edit_device_id = user_input[CONF_DEVICE_ID]
            return await self.async_step_edit_device()

        return self.async_show_form(
            step_id="select_edit",
            data_schema=self._build_device_selector_schema(),
        )

    async def async_step_edit_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a pre-filled edit form for the previously selected device."""
        device = next(
            d for d in self._devices if d[CONF_DEVICE_ID] == self._edit_device_id
        )

        if user_input is not None:
            updated: dict[str, Any] = {
                CONF_DEVICE_ID: self._edit_device_id,
                **_parse_device_input(user_input),
            }
            self._devices = [
                updated if d[CONF_DEVICE_ID] == self._edit_device_id else d
                for d in self._devices
            ]
            return self.async_create_entry(data={CONF_DEVICES: self._devices})

        return self.async_show_form(
            step_id="edit_device",
            data_schema=self.add_suggested_values_to_schema(DEVICE_FORM_SCHEMA, device),
        )

    # -- remove ----------------------------------------------------------------

    async def async_step_select_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select and immediately remove a dispatch device."""
        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]
            self._devices = [d for d in self._devices if d[CONF_DEVICE_ID] != device_id]
            return self.async_create_entry(data={CONF_DEVICES: self._devices})

        return self.async_show_form(
            step_id="select_remove",
            data_schema=self._build_device_selector_schema(),
        )
