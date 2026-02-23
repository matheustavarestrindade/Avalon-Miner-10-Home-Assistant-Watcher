"""Constants for the Avalon Miner integration."""

DOMAIN = "avalon_miner"

# Default connection settings
DEFAULT_PORT = 4028
DEFAULT_SCAN_INTERVAL = 30  # seconds between status polls
NETWORK_SCAN_INTERVAL = 60  # seconds between network discovery scans
HEALTH_CHECK_INTERVAL = 5   # seconds between health checks per miner
TCP_COMMAND_TIMEOUT = 5     # seconds for TCP command socket
TCP_PROBE_TIMEOUT = 0.4     # seconds for connectivity probe

# Config entry keys
CONF_IP = "ip"
CONF_PORT = "port"
CONF_FREQ1 = "freq1"
CONF_FREQ2 = "freq2"
CONF_FREQ3 = "freq3"
CONF_FREQ4 = "freq4"
CONF_VOLTAGE = "voltage"
CONF_HASH_NO = "hash_no"
CONF_AUTO_START = "auto_start"

# Defaults applied when a miner first comes online
DEFAULT_FREQ1 = 325
DEFAULT_FREQ2 = 337
DEFAULT_FREQ3 = 350
DEFAULT_FREQ4 = 362
DEFAULT_VOLTAGE = 25
DEFAULT_HASH_NO = 0

# Valid ASIC clock frequencies (MHz) for Avalon miners
VALID_MINER_FREQUENCIES = [
    25, 300, 312, 325, 337, 350, 362, 375, 387, 400, 408, 412, 416, 425, 433,
    437, 441, 450, 458, 462, 466, 475, 483, 487, 491, 500, 508, 512, 516, 525,
    533, 537, 550, 562, 575, 587, 600, 612, 625, 637, 650, 662, 675, 687, 700,
    712, 725, 737, 750, 762, 775, 787, 800, 825, 850, 875, 900, 925, 950, 975,
    1000, 1025, 1050, 1075, 1100, 1125, 1150, 1175, 1200,
]

# Voltage level range (maps to hardware voltage-level units, 0–60)
VOLTAGE_MIN = 0
VOLTAGE_MAX = 60
VOLTAGE_STEP = 1

# cgminer API commands (TCP text protocol)
CMD_QUERY_HASH_POWER_STATE = "ascset|0,hashpower"
CMD_QUERY_CURRENT_POOL = "pools"
CMD_QUERY_SUMMARY = "summary"
CMD_QUERY_DETAILS = "estats"
CMD_QUERY_CONTROLLER_VERSION = "version"

CMD_SOFT_SHUTDOWN = "ascset|0,softoff"
CMD_ENABLE_FAN = "ascset|0,fan-spd,100"
CMD_DISABLE_FAN = "ascset|0,fan-spd,0"
CMD_REBOOT_MINER = "ascset|0,reboot,0"
CMD_SHUTDOWN_HASH_POWER = "ascset|0,hashpower,0"


def cmd_set_fan_speed(speed: int) -> str:
    return f"ascset|0,fan-spd,{speed}"


def cmd_set_voltage(voltage: int) -> str:
    return f"ascset|0,voltage-level,{voltage}-0-0"


def cmd_set_frequency(freq1: int, freq2: int, freq3: int, freq4: int, hash_no: int) -> str:
    return f"ascset|0,frequency,{freq1}:{freq2}:{freq3}:{freq4}-0-{hash_no}-0"


def cmd_set_work_mode(mode: int) -> str:
    return f"ascset|0,workmode,{mode}"


# Platform names
PLATFORM_SENSOR = "sensor"
PLATFORM_SWITCH = "switch"
PLATFORM_NUMBER = "number"
PLATFORM_BUTTON = "button"

PLATFORMS = [PLATFORM_SENSOR, PLATFORM_SWITCH, PLATFORM_NUMBER, PLATFORM_BUTTON]

# Coordinator data keys
DATA_COORDINATOR = "coordinator"
DATA_CLIENT = "client"
