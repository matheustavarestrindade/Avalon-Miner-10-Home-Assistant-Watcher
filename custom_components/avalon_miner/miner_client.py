"""
Avalon Miner TCP client - Python port of the TypeScript miner.ts + parser.ts.

Communicates with a cgminer-compatible Avalon miner over a raw TCP socket on
port 4028 (the cgminer API protocol). Each command is a plain-text string;
responses are pipe-delimited key=value records.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from .const import (
    DEFAULT_PORT,
    TCP_COMMAND_TIMEOUT,
    TCP_PROBE_TIMEOUT,
    CMD_QUERY_HASH_POWER_STATE,
    CMD_QUERY_CURRENT_POOL,
    CMD_QUERY_SUMMARY,
    CMD_QUERY_DETAILS,
    CMD_QUERY_CONTROLLER_VERSION,
    CMD_SOFT_SHUTDOWN,
    CMD_ENABLE_FAN,
    CMD_DISABLE_FAN,
    CMD_REBOOT_MINER,
    CMD_SHUTDOWN_HASH_POWER,
    cmd_set_voltage,
    cmd_set_frequency,
    VALID_MINER_FREQUENCIES,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response parser (port of parser.ts)
# ---------------------------------------------------------------------------

def _is_numeric(value: str) -> bool:
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False


def _is_bool_string(value: str) -> bool:
    return value.lower() in ("true", "false")


def _split_considering_delimiters(text: str, delimiter: str = ",") -> list[str]:
    """Split *text* on *delimiter* but ignore delimiters inside [...] brackets."""
    if not text:
        return []
    parts: list[str] = []
    bracket_count = 0
    current = ""
    for char in text:
        if char == "[":
            bracket_count += 1
        elif char == "]":
            bracket_count -= 1
        if char == delimiter and bracket_count == 0:
            parts.append(current)
            current = ""
            continue
        current += char
    if current:
        parts.append(current)
    return parts


def _extract_inside_brackets(text: str) -> tuple[str, str]:
    """Return (key, value) from a 'key[value]' token."""
    key = ""
    value = ""
    current = ""
    for char in text:
        if char == "[":
            key = current
            current = ""
            continue
        if char == "]":
            value = current
            break
        current += char
    return key, value


def _coerce(value: str) -> Any:
    if _is_numeric(value):
        return float(value) if "." in value else int(value)
    if _is_bool_string(value):
        return value.lower() == "true"
    return value


def parse_miner_response(text: str) -> list[dict[str, Any]]:
    """
    Parse a raw cgminer pipe-delimited response into a list of dicts.

    The first element is always the STATUS header dict; subsequent elements are
    the data records (summary, pools, estats, etc.).
    """
    results: list[dict[str, Any]] = []
    parts = text.split("|")

    for part in parts:
        record: dict[str, Any] = {}
        subparts = _split_considering_delimiters(part)
        for subpart in subparts:
            tokens = _split_considering_delimiters(subpart, "=")
            if len(tokens) < 2:
                continue
            key = tokens[0]
            raw_value = tokens[1]
            if not raw_value:
                continue

            value_parts = _split_considering_delimiters(raw_value, " ")

            if len(value_parts) == 1:
                record[key] = _coerce(raw_value)
                continue

            if len(value_parts) == 0:
                continue

            # No bracket nesting – plain space-separated string
            if all("[" not in vp and "]" not in vp for vp in value_parts):
                record[key] = " ".join(value_parts)
                continue

            # Nested bracket objects: key[subkey[val] subkey[val] ...]
            nested: dict[str, Any] = {}
            for vp in value_parts:
                k, v = _extract_inside_brackets(vp)
                if not v:
                    continue
                inner_parts = v.split(" ")
                is_array = len(inner_parts) > 1
                if is_array:
                    nested[k] = [_coerce(i) for i in inner_parts if i]
                else:
                    nested[k] = _coerce(v)
            record[key] = nested

        results.append(record)

    return results


# ---------------------------------------------------------------------------
# Data classes for structured miner data
# ---------------------------------------------------------------------------

@dataclass
class ControllerVersion:
    api: float = 0.0
    product: str = ""
    model: int = 0
    hw_type: str = ""
    sw_type: str = ""
    version: str = ""
    dna: str = ""
    mac: str = ""


@dataclass
class HashPowerState:
    error: int = 0
    controller_voltage: int = 0   # raw ×0.1 V
    hash_board_voltage: int = 0   # raw ×0.01 V
    output_current: int = 0       # Amps
    output_power: int = 0         # Watts
    voltage_setting: int = 0      # raw target voltage


@dataclass
class SummaryData:
    elapsed: int = 0
    mhs_av: float = 0.0
    mhs_30s: float = 0.0
    mhs_1m: float = 0.0
    accepted: int = 0
    rejected: int = 0
    hardware_errors: int = 0
    best_share: int = 0
    pool_rejected_pct: float = 0.0
    board_mhs: dict[int, float] = field(default_factory=dict)


@dataclass
class PoolData:
    index: int = 0
    url: str = ""
    user: str = ""
    status: str = ""
    accepted: int = 0
    rejected: int = 0
    rejected_pct: float = 0.0
    stratum_difficulty: float = 0.0
    current_block_height: int = 0


@dataclass
class HashboardData:
    board_id: int = 0
    frequencies: list[int] = field(default_factory=list)  # 4 frequency zones (MHz)
    hashrate_mhs: float = 0.0


@dataclass
class MinerData:
    """Aggregated snapshot of a single miner's current state."""
    ip: str = ""
    online: bool = False
    soft_off: bool = False

    # Controller info
    controller: ControllerVersion = field(default_factory=ControllerVersion)

    # Hashrate
    mhs_av: float = 0.0
    mhs_30s: float = 0.0
    mhs_1m: float = 0.0
    accepted_shares: int = 0
    rejected_shares: int = 0
    hardware_errors: int = 0
    best_share: int = 0
    pool_rejected_pct: float = 0.0

    # Temperature (°C)
    temp_current: float = 0.0
    temp_avg: float = 0.0
    temp_max: float = 0.0

    # Fan
    fan1_rpm: int = 0
    fan2_rpm: int = 0
    fan_duty_pct: int = 0

    # Power
    output_power_w: int = 0
    hash_board_voltage_mv: float = 0.0
    output_current_a: int = 0

    # Uptime
    uptime_seconds: int = 0

    # Pools
    pools: list[PoolData] = field(default_factory=list)

    # Per-hashboard data
    hashboards: list[HashboardData] = field(default_factory=list)

    # Work mode: 0=normal, 1=high perf, 2=low power
    work_mode: int = 0


# ---------------------------------------------------------------------------
# TCP client
# ---------------------------------------------------------------------------

class AvalonMinerClient:
    """
    Async TCP client for the cgminer API protocol used by Avalon miners.

    All I/O is non-blocking and uses asyncio streams. A per-command lock
    serialises requests to the same miner (the firmware can only handle one
    command at a time).
    """

    def __init__(self, ip: str, port: int = DEFAULT_PORT) -> None:
        self.ip = ip
        self.port = port
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Low-level I/O
    # ------------------------------------------------------------------

    async def _send_command(self, command: str) -> list[dict[str, Any]]:
        """Open a TCP connection, send *command*, read the response and parse it."""
        async with self._lock:
            _LOGGER.debug("[%s] → %s", self.ip, command)
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.ip, self.port),
                    timeout=TCP_COMMAND_TIMEOUT,
                )
                try:
                    writer.write(command.encode())
                    await writer.drain()
                    raw = await asyncio.wait_for(
                        reader.read(65536),
                        timeout=TCP_COMMAND_TIMEOUT,
                    )
                finally:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass
            except asyncio.TimeoutError as exc:
                raise TimeoutError(f"Command '{command}' to {self.ip} timed out") from exc
            except OSError as exc:
                raise ConnectionError(f"Cannot connect to {self.ip}:{self.port}: {exc}") from exc

            text = raw.decode(errors="replace").strip()
            if not text:
                raise ValueError(f"Empty response from {self.ip} for command '{command}'")

            _LOGGER.debug("[%s] ← %s", self.ip, text[:200])
            return parse_miner_response(text)

    async def is_online(self) -> bool:
        """Return True if the miner's TCP port is reachable within the probe timeout."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(self.ip, self.port),
                timeout=TCP_PROBE_TIMEOUT,
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Query commands
    # ------------------------------------------------------------------

    async def query_controller_version(self) -> ControllerVersion:
        records = await self._send_command(CMD_QUERY_CONTROLLER_VERSION)
        raw = records[1] if len(records) > 1 else {}
        return ControllerVersion(
            api=raw.get("API", 0.0),
            product=raw.get("PROD", ""),
            model=int(raw.get("MODEL", 0)),
            hw_type=raw.get("HWTYPE", ""),
            sw_type=raw.get("SWTYPE", ""),
            version=raw.get("VERSION", ""),
            dna=raw.get("DNA", ""),
            mac=raw.get("MAC", ""),
        )

    async def query_summary(self) -> SummaryData:
        records = await self._send_command(CMD_QUERY_SUMMARY)
        raw = records[1] if len(records) > 1 else {}
        board_mhs: dict[int, float] = {}
        for i in range(8):
            key = f"Board {i} MH/s"
            if key in raw:
                board_mhs[i] = float(raw[key])
        return SummaryData(
            elapsed=int(raw.get("Elapsed", 0)),
            mhs_av=float(raw.get("MHS av", 0.0)),
            mhs_30s=float(raw.get("MHS 30s", 0.0)),
            mhs_1m=float(raw.get("MHS 1m", 0.0)),
            accepted=int(raw.get("Accepted", 0)),
            rejected=int(raw.get("Rejected", 0)),
            hardware_errors=int(raw.get("Hardware Errors", 0)),
            best_share=int(raw.get("Best Share", 0)),
            pool_rejected_pct=float(raw.get("Pool Rejected%", 0.0)),
            board_mhs=board_mhs,
        )

    async def query_details(self) -> dict[str, Any]:
        """Return raw estats dict (keyed 'MM ID0', 'MM ID1', ...)."""
        records = await self._send_command(CMD_QUERY_DETAILS)
        return records[1] if len(records) > 1 else {}

    async def query_current_pools(self) -> list[PoolData]:
        records = await self._send_command(CMD_QUERY_CURRENT_POOL)
        pools: list[PoolData] = []
        for rec in records[1:]:
            if "POOL" not in rec:
                continue
            pools.append(PoolData(
                index=int(rec.get("POOL", 0)),
                url=str(rec.get("URL", "")),
                user=str(rec.get("User", "")),
                status=str(rec.get("Status", "")),
                accepted=int(rec.get("Accepted", 0)),
                rejected=int(rec.get("Rejected", 0)),
                rejected_pct=float(rec.get("Pool Rejected%", 0.0)),
                stratum_difficulty=float(rec.get("Stratum Difficulty", 0.0)),
                current_block_height=int(rec.get("Current Block Height", 0)),
            ))
        return pools

    async def query_hash_power_state(self) -> HashPowerState:
        """
        Parse PS[errcode ctrlV boardV current power voltSetting] from ascset|0,hashpower.
        """
        records = await self._send_command(CMD_QUERY_HASH_POWER_STATE)
        raw = records[0] if records else {}
        msg = raw.get("Msg", {})
        ps: list[int] = []
        if isinstance(msg, dict):
            ps = [int(v) for v in msg.get("PS", [])]
        elif isinstance(msg, str):
            # Sometimes Msg is still a plain string – parse it manually
            # e.g. "ASC 0 set info: PS[0 1220 1314 140 1839 1308]"
            import re
            m = re.search(r"PS\[([^\]]+)\]", msg)
            if m:
                ps = [int(x) for x in m.group(1).split()]

        return HashPowerState(
            error=ps[0] if len(ps) > 0 else 0,
            controller_voltage=ps[1] if len(ps) > 1 else 0,
            hash_board_voltage=ps[2] if len(ps) > 2 else 0,
            output_current=ps[3] if len(ps) > 3 else 0,
            output_power=ps[4] if len(ps) > 4 else 0,
            voltage_setting=ps[5] if len(ps) > 5 else 0,
        )

    # ------------------------------------------------------------------
    # Helpers for parsing estats
    # ------------------------------------------------------------------

    @staticmethod
    def parse_hashboards_and_temps(
        details: dict[str, Any],
        summary: SummaryData,
    ) -> tuple[list[HashboardData], float, float, float, bool, int]:
        """
        Extract per-board frequencies + temperatures from the estats 'MM ID0' record.

        Returns:
            (hashboards, temp_current, temp_avg, temp_max, soft_off, work_mode)
        """
        mod = details.get("MM ID0", {})
        if not mod or not isinstance(mod, dict):
            return [], 0.0, 0.0, 0.0, False, 0

        system_statu = mod.get("SYSTEMSTATU", [])
        board_count = 0
        if system_statu:
            try:
                board_count = int(system_statu[-1])
            except (ValueError, IndexError):
                board_count = 0

        hashboards: list[HashboardData] = []
        for i in range(board_count):
            freqs = mod.get(f"SF{i}", [0, 0, 0, 0])
            hashboards.append(HashboardData(
                board_id=i,
                frequencies=[int(f) for f in freqs],
                hashrate_mhs=summary.board_mhs.get(i, 0.0),
            ))

        temp_current = float(mod.get("Temp", 0.0))
        temp_avg = float(mod.get("TAvg", 0.0))
        temp_max = float(mod.get("TMax", 0.0))
        soft_off = bool(mod.get("SoftOFF", 0))
        work_mode = int(mod.get("WORKMODE", 0))

        return hashboards, temp_current, temp_avg, temp_max, soft_off, work_mode

    @staticmethod
    def parse_fan_data(details: dict[str, Any]) -> tuple[int, int, int]:
        """Return (fan1_rpm, fan2_rpm, fan_duty_pct) from estats MM ID0."""
        mod = details.get("MM ID0", {})
        fan1 = int(mod.get("Fan1", 0))
        fan2 = int(mod.get("Fan2", 0))
        fan_r_raw = mod.get("FanR", "0%")
        try:
            fan_duty = int(str(fan_r_raw).rstrip("%"))
        except ValueError:
            fan_duty = 0
        return fan1, fan2, fan_duty

    # ------------------------------------------------------------------
    # Control commands
    # ------------------------------------------------------------------

    async def enable_fan(self) -> dict[str, Any]:
        records = await self._send_command(CMD_ENABLE_FAN)
        return records[0] if records else {}

    async def disable_fan(self) -> dict[str, Any]:
        records = await self._send_command(CMD_DISABLE_FAN)
        return records[0] if records else {}

    async def set_voltage(self, voltage: int) -> dict[str, Any]:
        if not (0 <= voltage <= 60):
            raise ValueError(f"Voltage level {voltage} out of range [0, 60]")
        records = await self._send_command(cmd_set_voltage(voltage))
        return records[0] if records else {}

    async def set_frequency(
        self,
        freq1: int,
        freq2: int,
        freq3: int,
        freq4: int,
        hash_no: int = 0,
    ) -> dict[str, Any]:
        for freq in (freq1, freq2, freq3, freq4):
            if freq not in VALID_MINER_FREQUENCIES:
                raise ValueError(f"Frequency {freq} MHz is not a valid Avalon frequency")
        if not (freq1 < freq2 < freq3 < freq4):
            raise ValueError("Frequencies must be in strictly ascending order (f1 < f2 < f3 < f4)")
        records = await self._send_command(cmd_set_frequency(freq1, freq2, freq3, freq4, hash_no))
        return records[0] if records else {}

    async def start_hashing(
        self,
        freq1: int,
        freq2: int,
        freq3: int,
        freq4: int,
        voltage: int,
        hash_no: int = 0,
    ) -> bool:
        """
        Enable fan, set voltage, then apply frequency profile – port of miner.ts startHashing().
        Returns True on success.
        """
        try:
            await self.enable_fan()
            await self.set_voltage(voltage)
            await self.set_frequency(freq1, freq2, freq3, freq4, hash_no)
            return True
        except Exception as exc:
            _LOGGER.error("[%s] start_hashing failed: %s", self.ip, exc)
            return False

    async def shutdown_hash_power(self) -> dict[str, Any]:
        records = await self._send_command(CMD_SHUTDOWN_HASH_POWER)
        return records[0] if records else {}

    async def soft_shutdown(self) -> dict[str, Any]:
        records = await self._send_command(CMD_SOFT_SHUTDOWN)
        return records[0] if records else {}

    async def reboot_miner(self) -> dict[str, Any]:
        records = await self._send_command(CMD_REBOOT_MINER)
        return records[0] if records else {}

    # ------------------------------------------------------------------
    # Full snapshot (used by the coordinator)
    # ------------------------------------------------------------------

    async def fetch_full_snapshot(
        self,
        freq1: int,
        freq2: int,
        freq3: int,
        freq4: int,
        voltage: int,
        hash_no: int,
    ) -> MinerData:
        """
        Query every endpoint and return a fully populated MinerData snapshot.
        If any sub-query fails, the rest are still attempted and the error is
        logged rather than propagated.
        """
        data = MinerData(ip=self.ip, online=True)

        try:
            data.controller = await self.query_controller_version()
        except Exception as exc:
            _LOGGER.warning("[%s] query_controller_version failed: %s", self.ip, exc)

        summary = SummaryData()
        try:
            summary = await self.query_summary()
        except Exception as exc:
            _LOGGER.warning("[%s] query_summary failed: %s", self.ip, exc)

        details: dict[str, Any] = {}
        try:
            details = await self.query_details()
        except Exception as exc:
            _LOGGER.warning("[%s] query_details failed: %s", self.ip, exc)

        try:
            power = await self.query_hash_power_state()
            data.output_power_w = power.output_power
            data.hash_board_voltage_mv = power.hash_board_voltage / 100.0  # raw → volts (13.14V)
            data.output_current_a = power.output_current
        except Exception as exc:
            _LOGGER.warning("[%s] query_hash_power_state failed: %s", self.ip, exc)

        try:
            data.pools = await self.query_current_pools()
        except Exception as exc:
            _LOGGER.warning("[%s] query_current_pools failed: %s", self.ip, exc)

        # Populate from summary
        data.mhs_av = summary.mhs_av
        data.mhs_30s = summary.mhs_30s
        data.mhs_1m = summary.mhs_1m
        data.accepted_shares = summary.accepted
        data.rejected_shares = summary.rejected
        data.hardware_errors = summary.hardware_errors
        data.best_share = summary.best_share
        data.pool_rejected_pct = summary.pool_rejected_pct
        data.uptime_seconds = summary.elapsed

        # Populate from estats
        if details:
            (
                data.hashboards,
                data.temp_current,
                data.temp_avg,
                data.temp_max,
                data.soft_off,
                data.work_mode,
            ) = self.parse_hashboards_and_temps(details, summary)
            data.fan1_rpm, data.fan2_rpm, data.fan_duty_pct = self.parse_fan_data(details)

        return data
