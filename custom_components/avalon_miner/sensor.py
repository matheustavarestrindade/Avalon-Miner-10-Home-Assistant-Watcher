"""
Sensor platform for Avalon Miner.

Entities created per miner:
  Hashrate
    - Hashrate (av)          TH/s / GH/s / MH/s  (auto-scaled)
    - Hashrate (30 s)        TH/s / GH/s / MH/s  (auto-scaled)
    - Hashrate (1 m)         TH/s / GH/s / MH/s  (auto-scaled)
  Temperature
    - Temperature (current)  °C
    - Temperature (average)  °C
    - Temperature (max)      °C
  Power
    - Output Power           W
    - Hash Board Voltage     V
    - Output Current         A
    - Energy Consumed        kWh  (cumulative, TOTAL_INCREASING – suitable for Energy Dashboard)
  Fan
    - Fan 1 Speed            RPM
    - Fan 2 Speed            RPM
    - Fan Duty               %
  Mining stats
    - Accepted Shares
    - Rejected Shares
    - Hardware Errors
    - Best Share (Session)    scaled K/M/G/T  (resets on miner reboot)
    - Best Share (All-Time)   scaled K/M/G/T  (persists across reboots via RestoreSensor)
    - Pool Rejected %        %
    - Uptime                 formatted string (e.g. "3d 14h 22m")
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
    - Board N Hashrate        TH/s / GH/s / MH/s  (auto-scaled)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import AvalonMinerCoordinator
from .miner_client import MinerData

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_hashrate(mhs: float) -> tuple[float, str]:
    """
    Convert a raw MH/s value to the most readable tier.

    Returns (value, unit) where unit is one of "TH/s", "GH/s", or "MH/s".
    Thresholds:
      ≥ 1 000 000 MH/s  → TH/s  (1 TH/s = 1 000 000 MH/s)
      ≥ 1 000     MH/s  → GH/s  (1 GH/s = 1 000 MH/s)
      otherwise         → MH/s
    """
    if mhs >= 1_000_000:
        return round(mhs / 1_000_000, 3), "TH/s"
    if mhs >= 1_000:
        return round(mhs / 1_000, 2), "GH/s"
    return round(mhs, 2), "MH/s"


def _format_uptime(seconds: int) -> str:
    """
    Format a duration in seconds as a human-readable string.

    Examples:
      59        → "59s"
      3661      → "1h 1m 1s"
      90061     → "1d 1h 1m"   (seconds dropped once hours are shown)
      2 days+   → "2d 1h 3m"
    """
    if seconds < 0:
        return "0s"
    days, remainder = divmod(int(seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _format_share(raw: int) -> tuple[float, str]:
    """
    Scale a raw share difficulty value to the most readable tier.

    Returns (value, suffix) e.g. (4.23, 'T') or (812.5, 'G').
    Tiers (powers of 1000):
      ≥ 1 000 000 000 000  → T  (trillion)
      ≥ 1 000 000 000      → G  (billion)
      ≥ 1 000 000          → M  (million)
      ≥ 1 000              → K  (thousand)
      otherwise            → raw integer, suffix ""
    """
    if raw >= 1_000_000_000_000:
        return round(raw / 1_000_000_000_000, 3), "T"
    if raw >= 1_000_000_000:
        return round(raw / 1_000_000_000, 3), "G"
    if raw >= 1_000_000:
        return round(raw / 1_000_000, 3), "M"
    if raw >= 1_000:
        return round(raw / 1_000, 2), "K"
    return float(raw), ""


@dataclass(frozen=True)
class AvalonSensorEntityDescription(SensorEntityDescription):
    """Extends the standard description with a value-getter callable."""
    value_fn: Callable[[MinerData], Any] | None = None


# ---------------------------------------------------------------------------
# Static sensor descriptors (one entity per miner)
# ---------------------------------------------------------------------------

SENSOR_DESCRIPTIONS: tuple[AvalonSensorEntityDescription, ...] = (
    # --- Hashrate: handled by AvalonMinerHashrateSensor (auto-scaled unit) ---

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
    AvalonSensorEntityDescription(
        key="energy_consumed",
        name="Energy Consumed",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.energy_consumed_kwh,
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
        icon="mdi:timer-outline",
        value_fn=lambda d: _format_uptime(d.uptime_seconds),
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

    # Hashrate sensors (separate class so unit scales dynamically)
    entities.append(AvalonMinerHashrateSensor(coordinator, entry, "av"))
    entities.append(AvalonMinerHashrateSensor(coordinator, entry, "30s"))
    entities.append(AvalonMinerHashrateSensor(coordinator, entry, "1m"))

    # Best-share sensors (session + all-time persistent)
    entities.append(AvalonMinerSessionBestShareSensor(coordinator, entry))
    entities.append(AvalonMinerAllTimeBestShareSensor(coordinator, entry))

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
# Auto-scaling hashrate sensor
# ---------------------------------------------------------------------------

_HASHRATE_FIELD = {
    "av":  lambda d: d.mhs_av,
    "30s": lambda d: d.mhs_30s,
    "1m":  lambda d: d.mhs_1m,
}
_HASHRATE_LABEL = {
    "av":  "Hashrate (Average)",
    "30s": "Hashrate (30s)",
    "1m":  "Hashrate (1m)",
}


class AvalonMinerHashrateSensor(AvalonMinerBaseEntity, SensorEntity):
    """
    Hashrate sensor that automatically scales its unit to the appropriate tier:
      MH/s → GH/s → TH/s
    The unit is re-evaluated on every state update so the dashboard always
    shows the most human-readable value.
    """

    def __init__(
        self,
        coordinator: AvalonMinerCoordinator,
        entry: ConfigEntry,
        period: str,  # "av", "30s", or "1m"
    ) -> None:
        super().__init__(coordinator, entry)
        self._period = period
        self._attr_unique_id = f"{self._ip}_hashrate_{period}"
        self._attr_name = _HASHRATE_LABEL[period]
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:pickaxe"
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> float | None:
        data: MinerData | None = self.coordinator.data
        if not data or not data.online:
            return None
        mhs = _HASHRATE_FIELD[self._period](data)
        value, _ = _format_hashrate(mhs)
        return value

    @property
    def native_unit_of_measurement(self) -> str:
        data: MinerData | None = self.coordinator.data
        if not data or not data.online:
            return "TH/s"
        mhs = _HASHRATE_FIELD[self._period](data)
        _, unit = _format_hashrate(mhs)
        return unit


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
    """Reports the hashrate for a specific hash board, auto-scaled to TH/GH/MH."""

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
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:pickaxe"
        self._attr_has_entity_name = True

    def _board_mhs(self) -> float | None:
        data: MinerData | None = self.coordinator.data
        if not data or not data.online:
            return None
        for board in data.hashboards:
            if board.board_id == self._board_id:
                return board.hashrate_mhs
        return None

    @property
    def native_value(self) -> float | None:
        mhs = self._board_mhs()
        if mhs is None:
            return None
        value, _ = _format_hashrate(mhs)
        return value

    @property
    def native_unit_of_measurement(self) -> str:
        mhs = self._board_mhs()
        if mhs is None:
            return "TH/s"
        _, unit = _format_hashrate(mhs)
        return unit


# ---------------------------------------------------------------------------
# Best-share sensors
# ---------------------------------------------------------------------------

class AvalonMinerSessionBestShareSensor(AvalonMinerBaseEntity, SensorEntity):
    """
    Best share for the current mining session (since last miner boot).

    The value comes directly from the cgminer summary "Best Share" field,
    which resets to zero every time the miner restarts.  The raw integer is
    scaled to the most human-readable suffix (K / M / G / T) so a value like
    4 231 000 000 000 is displayed as "4.231 T" instead of a 13-digit number.
    The suffix is exposed as the unit so HA stores and graphs the numeric part.
    """

    def __init__(
        self,
        coordinator: AvalonMinerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._ip}_best_share_session"
        self._attr_name = "Best Share (Session)"
        self._attr_icon = "mdi:trophy-outline"
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> float | None:
        data: MinerData | None = self.coordinator.data
        if not data or not data.online:
            return None
        value, _ = _format_share(data.best_share)
        return value

    @property
    def native_unit_of_measurement(self) -> str:
        data: MinerData | None = self.coordinator.data
        if not data or not data.online:
            return ""
        _, suffix = _format_share(data.best_share)
        return suffix


class AvalonMinerAllTimeBestShareSensor(AvalonMinerBaseEntity, RestoreSensor):
    """
    All-time best share across every session since the integration was set up.

    The previous best is restored from HA storage on startup so it survives
    both miner reboots and HA restarts.  It is only ever updated upward:
    if the current session best share exceeds the stored record, the record
    is updated.

    The raw integer is stored internally; native_value returns the scaled
    float and native_unit_of_measurement returns the matching suffix so HA
    receives a proper numeric state.
    """

    def __init__(
        self,
        coordinator: AvalonMinerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._ip}_best_share_all_time"
        self._attr_name = "Best Share (All-Time)"
        self._attr_icon = "mdi:trophy"
        self._attr_has_entity_name = True
        self._all_time_best: int = 0

    async def async_added_to_hass(self) -> None:
        """Restore previous all-time best from HA storage on startup."""
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None and last.native_value is not None:
            # Stored value is the scaled float; reconstruct raw int using the
            # stored unit as the suffix multiplier.
            try:
                stored_value = float(last.native_value)
                stored_unit = last.native_unit_of_measurement or ""
                self._all_time_best = _parse_share_string(
                    f"{stored_value} {stored_unit}".strip()
                )
            except (ValueError, AttributeError):
                pass

        # Listen for coordinator updates to keep the record current
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        """Called on every coordinator poll; update record if session best is higher."""
        data: MinerData | None = self.coordinator.data
        if data and data.online and data.best_share > self._all_time_best:
            self._all_time_best = data.best_share
            self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        if self._all_time_best == 0:
            return None
        value, _ = _format_share(self._all_time_best)
        return value

    @property
    def native_unit_of_measurement(self) -> str:
        if self._all_time_best == 0:
            return ""
        _, suffix = _format_share(self._all_time_best)
        return suffix


def _parse_share_string(text: str) -> int:
    """
    Convert a formatted share string back to a raw integer.

    Accepts formats like "4.231 T", "812.5 G", "1.5 M", "300.0 K", "500".
    """
    _SUFFIXES = {"T": 1_000_000_000_000, "G": 1_000_000_000, "M": 1_000_000, "K": 1_000}
    parts = text.strip().split()
    if len(parts) == 2:
        multiplier = _SUFFIXES.get(parts[1], 1)
        return int(float(parts[0]) * multiplier)
    return int(float(parts[0]))
