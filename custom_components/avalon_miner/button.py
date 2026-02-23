"""Button platform for Avalon Miner – Reboot and Soft-Shutdown actions."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
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
            AvalonRebootButton(coordinator, entry),
            AvalonSoftShutdownButton(coordinator, entry),
        ]
    )


class AvalonRebootButton(AvalonMinerBaseEntity, ButtonEntity):
    """Button that triggers a full hardware reboot of the miner."""

    def __init__(
        self,
        coordinator: AvalonMinerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._ip}_reboot"
        self._attr_name = "Reboot Miner"
        self._attr_icon = "mdi:restart"
        self._attr_has_entity_name = True

    async def async_press(self) -> None:
        _LOGGER.warning("[%s] Reboot button pressed.", self._ip)
        await self.coordinator.client.reboot_miner()
        # The miner will go offline – the coordinator will detect it on the next poll


class AvalonSoftShutdownButton(AvalonMinerBaseEntity, ButtonEntity):
    """Button that triggers a soft (OS-level) shutdown of the miner."""

    def __init__(
        self,
        coordinator: AvalonMinerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._ip}_soft_shutdown"
        self._attr_name = "Soft Shutdown"
        self._attr_icon = "mdi:power"
        self._attr_has_entity_name = True

    async def async_press(self) -> None:
        _LOGGER.warning("[%s] Soft-shutdown button pressed.", self._ip)
        await self.coordinator.client.soft_shutdown()
        await self.coordinator.async_request_refresh()
