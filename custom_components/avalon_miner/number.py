"""
Number platform for Avalon Miner.

Exposes per-miner configurable parameters as HA number entities so the user
can change them live from the dashboard. When a value is changed the command
is sent immediately to the miner *and* the config entry options are updated
so the setting persists across HA restarts.

Entities:
  - Frequency Zone 1–4 (MHz) – constrained to VALID_MINER_FREQUENCIES
  - Voltage Level (0–60)
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_FREQ1,
    CONF_FREQ2,
    CONF_FREQ3,
    CONF_FREQ4,
    CONF_VOLTAGE,
    DATA_COORDINATOR,
    DOMAIN,
    VALID_MINER_FREQUENCIES,
    VOLTAGE_MIN,
    VOLTAGE_MAX,
)
from .coordinator import AvalonMinerCoordinator
from .sensor import AvalonMinerBaseEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AvalonMinerCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(
        [
            AvalonFrequencyZoneNumber(coordinator, entry, zone=1, conf_key=CONF_FREQ1),
            AvalonFrequencyZoneNumber(coordinator, entry, zone=2, conf_key=CONF_FREQ2),
            AvalonFrequencyZoneNumber(coordinator, entry, zone=3, conf_key=CONF_FREQ3),
            AvalonFrequencyZoneNumber(coordinator, entry, zone=4, conf_key=CONF_FREQ4),
            AvalonVoltageLevelNumber(coordinator, entry),
        ]
    )


# ---------------------------------------------------------------------------
# Frequency zone number entity
# ---------------------------------------------------------------------------

class AvalonFrequencyZoneNumber(AvalonMinerBaseEntity, NumberEntity):
    """
    Editable frequency for one of the four ASIC clock zones.

    The picker is a simple number field; valid values snap to the nearest entry
    in VALID_MINER_FREQUENCIES. We use min/max from the list and step=1 so HA
    accepts any integer input, then we round to the nearest valid frequency on
    write.
    """

    def __init__(
        self,
        coordinator: AvalonMinerCoordinator,
        entry: ConfigEntry,
        zone: int,
        conf_key: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._zone = zone
        self._conf_key = conf_key
        self._attr_unique_id = f"{self._ip}_freq_zone{zone}"
        self._attr_name = f"Frequency Zone {zone}"
        self._attr_native_min_value = float(min(VALID_MINER_FREQUENCIES))
        self._attr_native_max_value = float(max(VALID_MINER_FREQUENCIES))
        self._attr_native_step = 1.0
        self._attr_native_unit_of_measurement = "MHz"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:sine-wave"
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> float:
        return float(getattr(self.coordinator, f"freq{self._zone}"))

    async def async_set_native_value(self, value: float) -> None:
        """Snap to nearest valid frequency, persist to options, apply to miner."""
        freq = _nearest_valid_freq(int(value))
        _LOGGER.info("[%s] Setting freq zone %d → %d MHz", self._ip, self._zone, freq)

        coordinator = self.coordinator
        # Build new options dict with updated frequency
        new_options = _build_options(coordinator, **{self._conf_key: freq})
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)

        # Send live command to the miner using all four current zones
        try:
            await coordinator.client.set_frequency(
                freq1=new_options[CONF_FREQ1],
                freq2=new_options[CONF_FREQ2],
                freq3=new_options[CONF_FREQ3],
                freq4=new_options[CONF_FREQ4],
                hash_no=coordinator.hash_no,
            )
        except Exception as exc:
            _LOGGER.error("[%s] set_frequency failed: %s", self._ip, exc)

        await coordinator.async_request_refresh()


# ---------------------------------------------------------------------------
# Voltage level number entity
# ---------------------------------------------------------------------------

class AvalonVoltageLevelNumber(AvalonMinerBaseEntity, NumberEntity):
    """Editable voltage level (0–60 units, hardware maps to ~0–14 V)."""

    def __init__(
        self,
        coordinator: AvalonMinerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._ip}_voltage_level"
        self._attr_name = "Voltage Level"
        self._attr_native_min_value = float(VOLTAGE_MIN)
        self._attr_native_max_value = float(VOLTAGE_MAX)
        self._attr_native_step = 1.0
        self._attr_native_unit_of_measurement = "level"
        self._attr_mode = NumberMode.SLIDER
        self._attr_icon = "mdi:lightning-bolt"
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> float:
        return float(self.coordinator.voltage)

    async def async_set_native_value(self, value: float) -> None:
        voltage = int(value)
        _LOGGER.info("[%s] Setting voltage level → %d", self._ip, voltage)

        coordinator = self.coordinator
        new_options = _build_options(coordinator, **{CONF_VOLTAGE: voltage})
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)

        try:
            await coordinator.client.set_voltage(voltage)
        except Exception as exc:
            _LOGGER.error("[%s] set_voltage failed: %s", self._ip, exc)

        await coordinator.async_request_refresh()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nearest_valid_freq(value: int) -> int:
    """Return the closest frequency from VALID_MINER_FREQUENCIES."""
    return min(VALID_MINER_FREQUENCIES, key=lambda f: abs(f - value))


def _build_options(coordinator: AvalonMinerCoordinator, **overrides: Any) -> dict[str, Any]:
    """Return a merged options dict with the given overrides applied."""
    base = {
        CONF_FREQ1: coordinator.freq1,
        CONF_FREQ2: coordinator.freq2,
        CONF_FREQ3: coordinator.freq3,
        CONF_FREQ4: coordinator.freq4,
        CONF_VOLTAGE: coordinator.voltage,
    }
    base.update(overrides)
    return base
