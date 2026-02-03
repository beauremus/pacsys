"""
ACNET error codes.

Error codes follow the pattern: FACILITY + (error_number * 256)
where error_number is signed (-128 to +127) and facility is 1-255.
"""

from enum import IntEnum


class AcnetFacility(IntEnum):
    """ACNET facility codes."""

    ACNET = 1  # Core ACNET errors
    DIO = 14  # Device I/O
    FTP = 15  # Fast Time Plot
    DBM = 16  # Database Manager
    DPM = 17  # Data Pool Manager


def make_error(facility: int, error_number: int) -> int:
    """Create an error code from facility and error number."""
    return facility + (error_number * 256)


def parse_error(code: int) -> tuple[int, int]:
    """Parse error code into facility and error number."""
    facility = code & 0xFF
    error_number = (code >> 8) & 0xFF
    if error_number > 127:
        error_number -= 256
    return facility, error_number


# ACNET facility errors
ACNET_OK = 0
ACNET_SUCCESS = 0
ACNET_DEPRECATED = make_error(1, 4)  # Used a deprecated feature
ACNET_REPLY_TIMEOUT = make_error(1, 3)  # Reply timeout (not fatal)
ACNET_ENDMULT = make_error(1, 2)  # End multiple replies
ACNET_PEND = make_error(1, 1)  # Operation pending

# Negative error codes (failures)
ACNET_RETRY = make_error(1, -1)  # Retryable I/O error
ACNET_NOLCLMEM = make_error(1, -2)  # No local memory
ACNET_NOREMMEM = make_error(1, -3)  # No remote memory
ACNET_RPLYPACK = make_error(1, -4)  # Reply packet assembly error
ACNET_REQPACK = make_error(1, -5)  # Request packet assembly error
ACNET_REQTMO = make_error(1, -6)  # Request timeout (6.5 min)
ACNET_QUEFULL = make_error(1, -7)  # Destination queue full
ACNET_BUSY = make_error(1, -8)  # Destination task busy
ACNET_NOT_CONNECTED = make_error(1, -21)  # Not connected to network
ACNET_ARG = make_error(1, -22)  # Missing argument(s)
ACNET_IVM = make_error(1, -23)  # Invalid message length/buffer
ACNET_NO_SUCH = make_error(1, -24)  # No such request or reply
ACNET_REQREJ = make_error(1, -25)  # Request rejected
ACNET_CANCELLED = make_error(1, -26)  # Request cancelled
ACNET_NAME_IN_USE = make_error(1, -27)  # Task name already in use
ACNET_NCR = make_error(1, -28)  # Not connected as RUM task
ACNET_NO_NODE = make_error(1, -30)  # No such logical node
ACNET_TRUNC_REQUEST = make_error(1, -31)  # Truncated request
ACNET_TRUNC_REPLY = make_error(1, -32)  # Truncated reply
ACNET_NO_TASK = make_error(1, -33)  # No such destination task
ACNET_DISCONNECTED = make_error(1, -34)  # Replier disconnected
ACNET_LEVEL2 = make_error(1, -35)  # Level II function error
ACNET_HARD_IO = make_error(1, -36)  # Hard I/O error
ACNET_NODE_DOWN = make_error(1, -42)  # Node offline
ACNET_UTIME = make_error(1, -49)  # User timeout
ACNET_INVARG = make_error(1, -50)  # Invalid argument

# DBM facility errors (Database Manager)
DBM_NOPROP = make_error(16, -13)  # Property not found

# FTP facility errors (Fast Time Plot, facility 15)
FACILITY_FTP = int(AcnetFacility.FTP)  # 15

# Positive status codes (informational, not errors)
FTP_COLLECTING = make_error(15, 4)  # Snapshot data collection in progress
FTP_WAIT_DELAY = make_error(15, 3)  # Snapshot armed, waiting for time delay
FTP_WAIT_EVENT = make_error(15, 2)  # Snapshot armed, waiting for arm event
FTP_PEND = make_error(15, 1)  # Snapshot pending (setup accepted)

# Negative error codes (actual failures)
FTP_INVTYP = make_error(15, -1)  # Invalid request typecode (software bug)
FTP_INVSSDN = make_error(15, -2)  # Invalid SSDN from database
FTP_FE_OUTOFMEM = make_error(15, -5)  # Front-end out of memory
FTP_NOCHAN = make_error(15, -6)  # No more MADC plot channels available
FTP_NO_DECODER = make_error(15, -7)  # No more MADC clock decoders
FTP_FE_PLOTLIM = make_error(15, -8)  # Front-end plot limit exceeded
FTP_INVNUMDEV = make_error(15, -9)  # Invalid number of devices in request
FTP_ENDOFDATA = make_error(15, -10)  # End of data
FTP_FE_PLOTLEN = make_error(15, -11)  # Front-end buffer length computation error
FTP_INVREQLEN = make_error(15, -12)  # Invalid request length (software bug)
FTP_NO_DATA = make_error(15, -13)  # No data from MADC (transient or hardware)
FTP_INVREQ = make_error(15, -14)  # Snapshot retrieval doesn't match active setup
FTP_BADEV = make_error(15, -15)  # Wrong set of clock events
FTP_BUMPED = make_error(15, -16)  # Bumped by higher priority plot
FTP_REROUTE = make_error(15, -17)  # Internal front-end reroute error
FTP_UNSFREQ = make_error(15, -19)  # Unsupported frequency (FRIG: only 1 KHz)
FTP_BIGDLY = make_error(15, -20)  # Delay too long (FRIG: max 16.384s)
FTP_UNSDEV = make_error(15, -21)  # Unsupported device type (FRIG: ADC only)
FTP_SOFTWARE = make_error(15, -22)  # Internal front-end software error
FTP_NOTRDY = make_error(15, -23)  # Snapshot data not yet ready (FRIG)
FTP_ARCNET = make_error(15, -24)  # ARCNET communication error (FRIG)
FTP_BADARM = make_error(15, -25)  # Bad arm value, can't decode arm word
FTP_INVFREQ_FOR_HARDWARE = make_error(15, -26)  # Frequency unsupported by hardware
FTP_BAD_PLOT_MODE = make_error(15, -27)  # Bad plot mode in arm/trigger word
FTP_NO_SUCH_DEVICE = make_error(15, -28)  # Device not found for retrieval
FTP_DEVICE_IN_USE = make_error(15, -29)  # Device already has active retrieval
FTP_FREQ_TOO_HIGH = make_error(15, -30)  # Frequency exceeds front-end capability
FTP_NO_SETUP = make_error(15, -31)  # No matching setup for retrieval/restart
FTP_UNSUPPORTED_PROP = make_error(15, -32)  # Unsupported property
FTP_INVALID_CHANNEL = make_error(15, -33)  # Channel in SSDN doesn't exist
FTP_NO_FIFO = make_error(15, -34)  # Missing FIFO board (FRIG)
FTP_BAD_DATA_LENGTH = make_error(15, -35)  # Data length not 2 or 4 (class bug)
FTP_BUFFER_OVERFLOW = make_error(15, -36)  # Front-end buffer overflow
FTP_NO_EVENT_SUPPORT = make_error(15, -37)  # Event-triggered sampling unsupported
FTP_TRIGGER_ERROR = make_error(15, -38)  # Internal trigger definition error
FTP_INV_CLASS_DEF = make_error(15, -39)  # Invalid class definition (software bug)
FTP_NO_RANDOM_ACCESS = make_error(15, -40)  # Random access not yet supported
FTP_INVALID_OFFSET = make_error(15, -41)  # Non-zero data offset unsupported
FTP_NO_SNAPSHOT = make_error(15, -42)  # Device doesn't support snapshot plots
FTP_EVENT_UNAVAILABLE = make_error(15, -43)  # Clock event not decoded by front-end
FTP_NO_FTPMAN_INIT = make_error(15, -44)  # FTPMAN not initialized (need class query first)
FTP_BADTIMES = make_error(15, -100)  # UCD module timestamp disagreement
FTP_BADRESETS = make_error(15, -101)  # Device timestamp didn't reset properly
FTP_BADARG = make_error(15, -102)  # Invalid argument in ACNET request
FTP_BADRPY = make_error(15, -103)  # Invalid reply from front-end

# FTP status code descriptions (composite code -> message)
_FTP_STATUS_MESSAGES = {
    FTP_COLLECTING: "collecting data",
    FTP_WAIT_DELAY: "waiting for arm delay",
    FTP_WAIT_EVENT: "waiting for arm event",
    FTP_PEND: "snapshot pending",
    FTP_INVTYP: "invalid request typecode",
    FTP_INVSSDN: "invalid SSDN",
    FTP_FE_OUTOFMEM: "front-end out of memory",
    FTP_NOCHAN: "no available MADC plot channels",
    FTP_NO_DECODER: "no available clock decoders",
    FTP_FE_PLOTLIM: "front-end plot limit exceeded",
    FTP_INVNUMDEV: "invalid number of devices",
    FTP_ENDOFDATA: "end of data",
    FTP_FE_PLOTLEN: "buffer length computation error",
    FTP_INVREQLEN: "invalid request length",
    FTP_NO_DATA: "no data from MADC",
    FTP_INVREQ: "retrieval doesn't match active setup",
    FTP_BADEV: "wrong set of clock events",
    FTP_BUMPED: "bumped by higher priority plot",
    FTP_REROUTE: "internal reroute error",
    FTP_UNSFREQ: "unsupported frequency",
    FTP_BIGDLY: "delay too long",
    FTP_UNSDEV: "unsupported device type",
    FTP_SOFTWARE: "internal software error",
    FTP_NOTRDY: "data not ready",
    FTP_ARCNET: "ARCNET communication error",
    FTP_BADARM: "bad arm value",
    FTP_INVFREQ_FOR_HARDWARE: "frequency unsupported by hardware",
    FTP_BAD_PLOT_MODE: "bad plot mode",
    FTP_NO_SUCH_DEVICE: "device not found for retrieval",
    FTP_DEVICE_IN_USE: "device already has active retrieval",
    FTP_FREQ_TOO_HIGH: "frequency exceeds front-end capability",
    FTP_NO_SETUP: "no matching setup for retrieval/restart",
    FTP_UNSUPPORTED_PROP: "unsupported property",
    FTP_INVALID_CHANNEL: "channel doesn't exist on device",
    FTP_NO_FIFO: "missing FIFO board",
    FTP_BAD_DATA_LENGTH: "invalid data length (expected 2 or 4)",
    FTP_BUFFER_OVERFLOW: "front-end buffer overflow",
    FTP_NO_EVENT_SUPPORT: "event-triggered sampling unsupported",
    FTP_TRIGGER_ERROR: "trigger definition error",
    FTP_INV_CLASS_DEF: "invalid class definition",
    FTP_NO_RANDOM_ACCESS: "random access not supported",
    FTP_INVALID_OFFSET: "non-zero data offset unsupported",
    FTP_NO_SNAPSHOT: "device doesn't support snapshots",
    FTP_EVENT_UNAVAILABLE: "clock event not available on front-end",
    FTP_NO_FTPMAN_INIT: "FTPMAN not initialized (send class query first)",
    FTP_BADTIMES: "UCD module timestamp error",
    FTP_BADRESETS: "device timestamp reset error",
    FTP_BADARG: "invalid argument",
    FTP_BADRPY: "invalid reply from front-end",
}


def ftp_status_message(composite_status: int) -> str:
    """Return human-readable message for an FTP composite status code.

    Works for both positive (informational) and negative (error) codes.
    """
    msg = _FTP_STATUS_MESSAGES.get(composite_status)
    if msg:
        return msg
    facility, error_num = parse_error(composite_status)
    if facility != FACILITY_FTP:
        return f"non-FTP status (facility={facility}, error={error_num})"
    return f"unknown FTP status (error={error_num})"


# DPM facility errors
DPM_PEND = make_error(17, 1)  # Request pending
DPM_STALE = make_error(17, 2)  # Stale data warning
DPM_BAD_REQUEST = make_error(17, -24)  # Malformed request
DPM_NO_SUCH_DEVICE = make_error(17, -26)  # Device not found
DPM_NO_SUCH_PROP = make_error(17, -27)  # Property not found
DPM_BAD_RANGE = make_error(17, -28)  # Invalid range
DPM_NO_SCALE = make_error(17, -31)  # Scaling not available
DPM_BAD_EVENT = make_error(17, -33)  # Invalid event
DPM_INTERNAL_ERROR = make_error(17, -45)  # Internal error

# Decomposed error numbers (signed int8) for use with Reading/WriteResult fields.
# These match the error_number component of the composite constants above.
FACILITY_ACNET = int(AcnetFacility.ACNET)  # 1
FACILITY_DBM = int(AcnetFacility.DBM)  # 16
ERR_OK = 0
ERR_RETRY = -1  # Generic retryable error (error number of ACNET_RETRY)
ERR_TIMEOUT = -6  # Request timeout (error number of ACNET_REQTMO)
ERR_NOPROP = -13  # Property not found (error number of DBM_NOPROP)


def normalize_error_code(code: int) -> int:
    """Normalize unsigned error code to signed int8 convention.

    Backends receive error codes as unsigned values (uint8/uint32).
    ACNET convention: negative=error, 0=ok, positive=warning.
    Values > 127 are negative when interpreted as signed int8.
    """
    if code > 127:
        return code - 256
    return code


def status_message(facility: int, error: int) -> str | None:
    """Build human-readable status message from decomposed error codes.

    Returns None for success (error == 0).
    """
    if error < 0:
        return f"Device error (facility={facility}, error={error})"
    elif error > 0:
        return f"Warning (facility={facility}, error={error})"
    return None


class AcnetError(Exception):
    """Exception for ACNET protocol errors."""

    def __init__(self, status: int, message: str | None = None):
        self.status = status
        facility, error_num = parse_error(status)
        self.facility = facility
        self.error_number = error_num
        tag = f"ACNET error [{facility} {error_num}]"
        if message:
            super().__init__(f"{tag}: {message}")
        else:
            super().__init__(tag)

    def __repr__(self):
        return f"AcnetError(facility={self.facility}, error={self.error_number})"


class AcnetUnavailableError(AcnetError):
    """Exception when ACNET daemon is unavailable."""

    def __init__(self):
        super().__init__(ACNET_NOT_CONNECTED, "ACNET daemon unavailable")


class AcnetTimeoutError(AcnetError):
    """Exception when a request times out."""

    def __init__(self, timeout_ms: int | None = None):
        msg = f"timeout after {timeout_ms}ms" if timeout_ms else "timeout"
        super().__init__(ACNET_REQTMO, msg)


class AcnetNodeError(AcnetError):
    """Exception when a node is not found."""

    def __init__(self, node: str | int):
        super().__init__(ACNET_NO_NODE, f"node not found: {node}")


class AcnetTaskError(AcnetError):
    """Exception when a task is not found."""

    def __init__(self, task: str):
        super().__init__(ACNET_NO_TASK, f"task not found: {task}")


class AcnetRequestRejectedError(AcnetError):
    """Exception when acnetd rejects a request to a restricted task.

    acnetd can be configured with -r to reject TCP client requests
    to specific task handles (e.g., FTPMAN). This error provides a
    clear message identifying the rejected task.
    """

    def __init__(self, task: str):
        self.task = task
        super().__init__(
            ACNET_REQREJ,
            f"request to task '{task}' rejected by acnetd (task is on the TCP reject list, see acnetd -r flag)",
        )
