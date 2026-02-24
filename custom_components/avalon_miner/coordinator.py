"""
DataUpdateCoordinator for Avalon Miner.

- Polls each configured miner every 30 seconds.
- On first connection (miner transitions offline → online) and when
  ``auto_start`` is enabled, it pushes the configured frequency/voltage profile
  to the miner exactly as the original TypeScript ``onConnect()`` / ``startHashing()``
  did.
- Also runs a background network-discovery scan roughly every 60 seconds so that
  newly powered-on miners that are already registered as config entries come up
  automatically without requiring a HA restart.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta, datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

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
    DEFAULT_SCAN_INTERVAL,
)
from .miner_client import AvalonMinerClient, MinerData

_LOGGER = logging.getLogger(__name__)

# How many consecutive offline polls before we stop trying to auto-start
_MAX_OFFLINE_BEFORE_RESET = 3


class AvalonMinerCoordinator(DataUpdateCoordinator[MinerData]):
    """
    Polls a single Avalon Miner and exposes its data to all HA entities.

    One coordinator instance is created per config entry (= per miner IP).
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self._client = AvalonMinerClient(
            ip=entry.data[CONF_IP],
            port=entry.data.get(CONF_PORT, DEFAULT_PORT),
        )
        self._was_online: bool = False
        self._offline_count: int = 0
        self._energy_kwh: float = 0.0
        self._last_energy_ts: datetime | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=f"avalon_miner_{entry.data[CONF_IP]}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    @property
    def client(self) -> AvalonMinerClient:
        return self._client

    # ------------------------------------------------------------------
    # Helpers to read the current config (merged data + options)
    # ------------------------------------------------------------------

    def _get_option(self, key: str, default: Any) -> Any:
        """Return the value from options if set, else from data, else default."""
        return self.entry.options.get(key, self.entry.data.get(key, default))

    @property
    def freq1(self) -> int:
        return int(self._get_option(CONF_FREQ1, DEFAULT_FREQ1))

    @property
    def freq2(self) -> int:
        return int(self._get_option(CONF_FREQ2, DEFAULT_FREQ2))

    @property
    def freq3(self) -> int:
        return int(self._get_option(CONF_FREQ3, DEFAULT_FREQ3))

    @property
    def freq4(self) -> int:
        return int(self._get_option(CONF_FREQ4, DEFAULT_FREQ4))

    @property
    def voltage(self) -> int:
        return int(self._get_option(CONF_VOLTAGE, DEFAULT_VOLTAGE))

    @property
    def hash_no(self) -> int:
        return int(self._get_option(CONF_HASH_NO, DEFAULT_HASH_NO))

    @property
    def auto_start(self) -> bool:
        return bool(self._get_option(CONF_AUTO_START, True))

    # ------------------------------------------------------------------
    # Main update method – called by HA every 30 s
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> MinerData:
        """Fetch data from the miner; handle transitions between online/offline."""

        online = await self._client.is_online()

        if not online:
            self._offline_count += 1
            if self._was_online:
                _LOGGER.warning(
                    "[%s] Miner went offline (consecutive offline: %d)",
                    self._client.ip,
                    self._offline_count,
                )
            self._was_online = False
            # Return a stub so entities become unavailable rather than erroring
            return MinerData(ip=self._client.ip, online=False)

        # Miner is online ---
        just_came_online = not self._was_online
        self._was_online = True
        self._offline_count = 0

        if just_came_online:
            _LOGGER.info("[%s] Miner came online.", self._client.ip)
            if self.auto_start:
                await self._on_connect()

        try:
            data = await self._client.fetch_full_snapshot(
                freq1=self.freq1,
                freq2=self.freq2,
                freq3=self.freq3,
                freq4=self.freq4,
                voltage=self.voltage,
                hash_no=self.hash_no,
            )
        except Exception as exc:
            raise UpdateFailed(f"Error communicating with miner {
                               self._client.ip}: {exc}") from exc

        # Accumulate energy (kWh) from instantaneous power readings.
        # energy += power_W * elapsed_hours
        now = datetime.now()
        if self._last_energy_ts is not None and data.output_power_w > 0:
            elapsed_hours = (
                now - self._last_energy_ts).total_seconds() / 3600.0
            self._energy_kwh += data.output_power_w * elapsed_hours / 1000.0
        self._last_energy_ts = now
        data.energy_consumed_kwh = round(self._energy_kwh, 4)

        return data

    # ------------------------------------------------------------------
    # On-connect: wait for miner to start hashing then push config
    # Mirrors TypeScript onConnect() – up to 10 attempts, 10 s apart
    # ------------------------------------------------------------------

    async def _on_connect(self) -> None:
        _LOGGER.info(
            "[%s] Miner just connected – waiting for it to begin hashing "
            "before pushing frequency/voltage config.",
            self._client.ip,
        )
        max_attempts = 10
        sleep_between_attempts = 30
        for attempt in range(1, max_attempts + 1):
            try:
                summary = await self._client.query_summary()
                if summary.mhs_30s <= 5:
                    _LOGGER.info(
                        "[%s] Not ready yet (MHS 30s=%.1f). "
                        "Waiting 10 s (attempt %d/%d).",
                        self._client.ip,
                        summary.mhs_30s,
                        attempt,
                        max_attempts,
                    )
                    await asyncio.sleep(sleep_between_attempts)
                    continue

                ok = await self._client.start_hashing(
                    freq1=self.freq1,
                    freq2=self.freq2,
                    freq3=self.freq3,
                    freq4=self.freq4,
                    voltage=self.voltage,
                    hash_no=self.hash_no,
                )
                if ok:
                    _LOGGER.info(
                        "[%s] Hashing started successfully.", self._client.ip)
                    return
                _LOGGER.warning(
                    "[%s] start_hashing returned False (attempt %d/%d). Retrying.",
                    self._client.ip,
                    attempt,
                    max_attempts,
                )
                await asyncio.sleep(sleep_between_attempts)
            except Exception as exc:
                _LOGGER.warning(
                    "[%s] Error during on_connect attempt %d: %s",
                    self._client.ip,
                    attempt,
                    exc,
                )
                await asyncio.sleep(sleep_between_attempts)

        _LOGGER.error(
            "[%s] Gave up trying to start hashing after %d attempts.",
            self._client.ip,
            max_attempts,
        )
