"""Switch platform for Avalon Miner – Start/Stop hashing."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import AvalonMinerCoordinator
from .miner_client import MinerData
from .sensor import AvalonMinerBaseEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AvalonMinerCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities([AvalonMinerHashingSwitch(coordinator, entry)])


class AvalonMinerHashingSwitch(AvalonMinerBaseEntity, SwitchEntity):
    """
    Switch that mirrors the miner's SoftOFF state.

    Turning ON  → start_hashing (fan + voltage + frequency)
    Turning OFF → shutdown_hash_power
    """

    def __init__(
        self,
        coordinator: AvalonMinerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._ip}_hashing"
        self._attr_name = "Hashing"
        self._attr_icon = "mdi:pickaxe"
        self._attr_has_entity_name = True

    @property
    def is_on(self) -> bool | None:
        data: MinerData | None = self.coordinator.data
        if not data or not data.online:
            return None
        # SoftOFF=1 means stopped; is_on=True means hashing
        return not data.soft_off

    async def async_turn_on(self, **kwargs: Any) -> None:
        coordinator: AvalonMinerCoordinator = self.coordinator
        _LOGGER.info("[%s] Turning hashing ON.", self._ip)
        ok = await coordinator.client.start_hashing(
            freq1=coordinator.freq1,
            freq2=coordinator.freq2,
            freq3=coordinator.freq3,
            freq4=coordinator.freq4,
            voltage=coordinator.voltage,
            hash_no=coordinator.hash_no,
        )
        if not ok:
            _LOGGER.error("[%s] start_hashing command failed.", self._ip)
        await coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        _LOGGER.info("[%s] Turning hashing OFF.", self._ip)
        await self.coordinator.client.shutdown_hash_power()
        await self.coordinator.async_request_refresh()
