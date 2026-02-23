"""Config flow for Avalon Miner integration.

Step 1 – User: enter IP address (and optionally port).
Step 2 – Options: per-miner frequency zones, voltage level and auto-start flag.
         Also exposed as an Options flow so settings can be changed after setup.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_IP,
    CONF_PORT,
    CONF_FREQ1,
    CONF_FREQ2,
    CONF_FREQ3,
    CONF_FREQ4,
    CONF_VOLTAGE,
    CONF_HASH_NO,
    CONF_AUTO_START,
    DEFAULT_PORT,
    DEFAULT_FREQ1,
    DEFAULT_FREQ2,
    DEFAULT_FREQ3,
    DEFAULT_FREQ4,
    DEFAULT_VOLTAGE,
    DEFAULT_HASH_NO,
    VALID_MINER_FREQUENCIES,
    VOLTAGE_MIN,
    VOLTAGE_MAX,
)
from .miner_client import AvalonMinerClient

_LOGGER = logging.getLogger(__name__)

# Schema for the initial setup step (IP + port)
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_IP): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.Coerce(int),
    }
)


def _options_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Return the options vol.Schema populated with *defaults*."""
    return vol.Schema(
        {
            vol.Required(CONF_FREQ1, default=defaults.get(CONF_FREQ1, DEFAULT_FREQ1)): vol.In(VALID_MINER_FREQUENCIES),
            vol.Required(CONF_FREQ2, default=defaults.get(CONF_FREQ2, DEFAULT_FREQ2)): vol.In(VALID_MINER_FREQUENCIES),
            vol.Required(CONF_FREQ3, default=defaults.get(CONF_FREQ3, DEFAULT_FREQ3)): vol.In(VALID_MINER_FREQUENCIES),
            vol.Required(CONF_FREQ4, default=defaults.get(CONF_FREQ4, DEFAULT_FREQ4)): vol.In(VALID_MINER_FREQUENCIES),
            vol.Required(CONF_VOLTAGE, default=defaults.get(CONF_VOLTAGE, DEFAULT_VOLTAGE)): vol.All(
                vol.Coerce(int), vol.Range(min=VOLTAGE_MIN, max=VOLTAGE_MAX)
            ),
            vol.Required(CONF_HASH_NO, default=defaults.get(CONF_HASH_NO, DEFAULT_HASH_NO)): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=4)
            ),
            vol.Required(CONF_AUTO_START, default=defaults.get(CONF_AUTO_START, True)): bool,
        }
    )


class AvalonMinerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow for adding an Avalon Miner."""

    VERSION = 1

    def __init__(self) -> None:
        self._user_input: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """First step: enter IP address."""
        errors: dict[str, str] = {}

        if user_input is not None:
            ip = user_input[CONF_IP].strip()
            port = int(user_input.get(CONF_PORT, DEFAULT_PORT))

            # Deduplicate entries with the same IP
            await self.async_set_unique_id(f"{ip}:{port}")
            self._abort_if_unique_id_configured()

            # Quick reachability check
            client = AvalonMinerClient(ip, port)
            if not await client.is_online():
                errors["base"] = "cannot_connect"
            else:
                self._user_input = {CONF_IP: ip, CONF_PORT: port}
                return await self.async_step_options()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_options(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Second step: configure frequency + voltage defaults."""
        errors: dict[str, str] = {}

        if user_input is not None:
            f1, f2, f3, f4 = (
                user_input[CONF_FREQ1],
                user_input[CONF_FREQ2],
                user_input[CONF_FREQ3],
                user_input[CONF_FREQ4],
            )
            if not (f1 < f2 < f3 < f4):
                errors[CONF_FREQ1] = "frequencies_not_ascending"
            else:
                data = {**self._user_input, **user_input}
                return self.async_create_entry(
                    title=f"Avalon Miner {self._user_input[CONF_IP]}",
                    data=data,
                )

        return self.async_show_form(
            step_id="options",
            data_schema=_options_schema({}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> AvalonMinerOptionsFlow:
        return AvalonMinerOptionsFlow(config_entry)


class AvalonMinerOptionsFlow(config_entries.OptionsFlow):
    """Allow the user to reconfigure frequency/voltage after initial setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        # Merge config data + existing options to get current values
        current: dict[str, Any] = {
            **self._config_entry.data,
            **self._config_entry.options,
        }

        if user_input is not None:
            f1, f2, f3, f4 = (
                user_input[CONF_FREQ1],
                user_input[CONF_FREQ2],
                user_input[CONF_FREQ3],
                user_input[CONF_FREQ4],
            )
            if not (f1 < f2 < f3 < f4):
                errors[CONF_FREQ1] = "frequencies_not_ascending"
            else:
                return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(current),
            errors=errors,
        )
