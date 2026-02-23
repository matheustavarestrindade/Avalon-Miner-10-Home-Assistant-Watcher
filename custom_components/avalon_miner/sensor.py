"""
Sensor platform for Avalon Miner.

Entities created per miner:
  Hashrate
    - Hashrate (av)          MH/s
    - Hashrate (30 s)        MH/s
    - Hashrate (1 m)         MH/s
  Temperature
    - Temperature (current)  °C
    - Temperature (average)  °C
    - Temperature (max)      °C
  Power
    - Output Power           W
    - Hash Board Voltage     V
    - Output Current         A
  Fan
    - Fan 1 Speed            RPM
    - Fan 2 Speed            RPM
    - Fan Duty               %
  Mining stats
    - Accepted Shares
    - Rejected Shares
    - Hardware Errors
    - Best Share
    - Pool Rejected %        %
    - Uptime                 s
  Pool (first active pool)
    - Pool URL
    - Pool User
    - Pool Status
  Controller
    - Firmware Version
    - Model
    - MAC Address
  Per hashboard (dynamic, one set per board reported by the miner):
    - Board N Freq Zone 1–4  MHz
    - Board N Hashrate        MH/s
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import AvalonMinerCoordinator
from .miner_client import MinerData

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AvalonSensorEntityDescription(SensorEntityDescription):
    """Extends the standard description with a value-getter callable."""
    value_fn: Callable[[MinerData], Any] | None = None


# ---------------------------------------------------------------------------
# Static sensor descriptors (one entity per miner)
# ---------------------------------------------------------------------------

SENSOR_DESCRIPTIONS: tuple[AvalonSensorEntityDescription, ...] = (
    # --- Hashrate ---
    AvalonSensorEntityDescription(
        key="hashrate_av",
        name="Hashrate (Average)",
        native_unit_of_measurement="MH/s",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:pickaxe",
        value_fn=lambda d: round(d.mhs_av, 2),
    ),
    AvalonSensorEntityDescription(
        key="hashrate_30s",
        name="Hashrate (30s)",
        native_unit_of_measurement="MH/s",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:pickaxe",
        value_fn=lambda d: round(d.mhs_30s, 2),
    ),
    AvalonSensorEntityDescription(
        key="hashrate_1m",
        name="Hashrate (1m)",
        native_unit_of_measurement="MH/s",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:pickaxe",
        value_fn=lambda d: round(d.mhs_1m, 2),
    ),
    # --- Temperature ---
    AvalonSensorEntityDescription(
        key="temp_current",
        name="Temperature (Intake)",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.temp_current, 1),
    ),
    AvalonSensorEntityDescription(
        key="temp_avg",
        name="Temperature (Average)",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.temp_avg, 1),
    ),
    AvalonSensorEntityDescription(
        key="temp_max",
        name="Temperature (Max)",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.temp_max, 1),
    ),
    # --- Power ---
    AvalonSensorEntityDescription(
        key="output_power",
        name="Output Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.output_power_w,
    ),
    AvalonSensorEntityDescription(
        key="hash_board_voltage",
        name="Hash Board Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.hash_board_voltage_mv, 2),
    ),
    AvalonSensorEntityDescription(
        key="output_current",
        name="Output Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.output_current_a,
    ),
    # --- Fan ---
    AvalonSensorEntityDescription(
        key="fan1_rpm",
        name="Fan 1 Speed",
        native_unit_of_measurement="RPM",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fan",
        value_fn=lambda d: d.fan1_rpm,
    ),
    AvalonSensorEntityDescription(
        key="fan2_rpm",
        name="Fan 2 Speed",
        native_unit_of_measurement="RPM",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fan",
        value_fn=lambda d: d.fan2_rpm,
    ),
    AvalonSensorEntityDescription(
        key="fan_duty",
        name="Fan Duty Cycle",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fan",
        value_fn=lambda d: d.fan_duty_pct,
    ),
    # --- Mining stats ---
    AvalonSensorEntityDescription(
        key="accepted_shares",
        name="Accepted Shares",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:check-circle-outline",
        value_fn=lambda d: d.accepted_shares,
    ),
    AvalonSensorEntityDescription(
        key="rejected_shares",
        name="Rejected Shares",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:close-circle-outline",
        value_fn=lambda d: d.rejected_shares,
    ),
    AvalonSensorEntityDescription(
        key="hardware_errors",
        name="Hardware Errors",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:alert-circle-outline",
        value_fn=lambda d: d.hardware_errors,
    ),
    AvalonSensorEntityDescription(
        key="best_share",
        name="Best Share",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:trophy",
        value_fn=lambda d: d.best_share,
    ),
    AvalonSensorEntityDescription(
        key="pool_rejected_pct",
        name="Pool Rejected %",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent",
        value_fn=lambda d: round(d.pool_rejected_pct, 2),
    ),
    AvalonSensorEntityDescription(
        key="uptime",
        name="Uptime",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.uptime_seconds,
    ),
    # --- Pool info (first pool) ---
    AvalonSensorEntityDescription(
        key="pool_url",
        name="Pool URL",
        icon="mdi:server",
        value_fn=lambda d: d.pools[0].url if d.pools else None,
    ),
    AvalonSensorEntityDescription(
        key="pool_user",
        name="Pool User",
        icon="mdi:account",
        value_fn=lambda d: d.pools[0].user if d.pools else None,
    ),
    AvalonSensorEntityDescription(
        key="pool_status",
        name="Pool Status",
        icon="mdi:connection",
        value_fn=lambda d: d.pools[0].status if d.pools else None,
    ),
    # --- Controller / device info ---
    AvalonSensorEntityDescription(
        key="firmware_version",
        name="Firmware Version",
        icon="mdi:chip",
        value_fn=lambda d: d.controller.version,
    ),
    AvalonSensorEntityDescription(
        key="model",
        name="Model",
        icon="mdi:information-outline",
        value_fn=lambda d: d.controller.model if d.controller.model else None,
    ),
    AvalonSensorEntityDescription(
        key="mac_address",
        name="MAC Address",
        icon="mdi:ethernet",
        value_fn=lambda d: d.controller.mac,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Avalon Miner sensors from a config entry."""
    coordinator: AvalonMinerCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]

    entities: list[SensorEntity] = []

    # Static sensors
    for description in SENSOR_DESCRIPTIONS:
        entities.append(AvalonMinerSensor(coordinator, entry, description))

    # Dynamic per-hashboard sensors will be added once we have real data
    # We schedule a one-time callback after the first successful poll.
    async def _add_hashboard_sensors(_: Any = None) -> None:
        data: MinerData = coordinator.data
        if not data or not data.online:
            return
        board_entities: list[SensorEntity] = []
        for board in data.hashboards:
            board_entities.append(
                AvalonMinerHashboardFreqSensor(coordinator, entry, board.board_id, zone=0)
            )
            board_entities.append(
                AvalonMinerHashboardFreqSensor(coordinator, entry, board.board_id, zone=1)
            )
            board_entities.append(
                AvalonMinerHashboardFreqSensor(coordinator, entry, board.board_id, zone=2)
            )
            board_entities.append(
                AvalonMinerHashboardFreqSensor(coordinator, entry, board.board_id, zone=3)
            )
            board_entities.append(
                AvalonMinerHashboardHashrateSensor(coordinator, entry, board.board_id)
            )
        async_add_entities(board_entities)

    # Register listener so hashboard entities are created after the first poll
    coordinator.async_add_listener(_add_hashboard_sensors)

    async_add_entities(entities)


# ---------------------------------------------------------------------------
# Base entity
# ---------------------------------------------------------------------------

class AvalonMinerBaseEntity(CoordinatorEntity[AvalonMinerCoordinator]):
    """Base class shared by all Avalon Miner entities."""

    def __init__(
        self,
        coordinator: AvalonMinerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._ip = entry.data["ip"]

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device registry info so all entities share one device tile."""
        data: MinerData | None = self.coordinator.data
        model = None
        sw_version = None
        if data and data.online:
            model = str(data.controller.model) if data.controller.model else None
            sw_version = data.controller.version or None

        return {
            "identifiers": {(DOMAIN, self._ip)},
            "name": f"Avalon Miner {self._ip}",
            "manufacturer": "Canaan",
            "model": model or "Avalon Miner",
            "sw_version": sw_version,
            "configuration_url": f"http://{self._ip}",
        }

    @property
    def available(self) -> bool:
        """Entity is unavailable when miner is offline."""
        if not self.coordinator.last_update_success:
            return False
        data: MinerData | None = self.coordinator.data
        return data is not None and data.online


# ---------------------------------------------------------------------------
# Static sensor entity
# ---------------------------------------------------------------------------

class AvalonMinerSensor(AvalonMinerBaseEntity, SensorEntity):
    """A single static sensor reading from a miner."""

    entity_description: AvalonSensorEntityDescription

    def __init__(
        self,
        coordinator: AvalonMinerCoordinator,
        entry: ConfigEntry,
        description: AvalonSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{self._ip}_{description.key}"
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> Any:
        data: MinerData | None = self.coordinator.data
        if not data or not data.online:
            return None
        fn = self.entity_description.value_fn
        if fn is None:
            return None
        try:
            return fn(data)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Dynamic per-hashboard frequency sensor
# ---------------------------------------------------------------------------

class AvalonMinerHashboardFreqSensor(AvalonMinerBaseEntity, SensorEntity):
    """Reports one of the four frequency zones for a specific hash board."""

    def __init__(
        self,
        coordinator: AvalonMinerCoordinator,
        entry: ConfigEntry,
        board_id: int,
        zone: int,
    ) -> None:
        super().__init__(coordinator, entry)
        self._board_id = board_id
        self._zone = zone
        self._attr_unique_id = f"{self._ip}_board{board_id}_freq_zone{zone + 1}"
        self._attr_name = f"Board {board_id} Freq Zone {zone + 1}"
        self._attr_native_unit_of_measurement = UnitOfFrequency.MEGAHERTZ
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:sine-wave"
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> int | None:
        data: MinerData | None = self.coordinator.data
        if not data or not data.online:
            return None
        for board in data.hashboards:
            if board.board_id == self._board_id:
                freqs = board.frequencies
                if self._zone < len(freqs):
                    return int(freqs[self._zone])
        return None


# ---------------------------------------------------------------------------
# Dynamic per-hashboard hashrate sensor
# ---------------------------------------------------------------------------

class AvalonMinerHashboardHashrateSensor(AvalonMinerBaseEntity, SensorEntity):
    """Reports the hashrate for a specific hash board."""

    def __init__(
        self,
        coordinator: AvalonMinerCoordinator,
        entry: ConfigEntry,
        board_id: int,
    ) -> None:
        super().__init__(coordinator, entry)
        self._board_id = board_id
        self._attr_unique_id = f"{self._ip}_board{board_id}_hashrate"
        self._attr_name = f"Board {board_id} Hashrate"
        self._attr_native_unit_of_measurement = "MH/s"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:pickaxe"
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> float | None:
        data: MinerData | None = self.coordinator.data
        if not data or not data.online:
            return None
        for board in data.hashboards:
            if board.board_id == self._board_id:
                return round(board.hashrate_mhs, 2)
        return None
