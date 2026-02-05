"""
ACL Backend implementation.

Provides read-only access to ACNET devices via the ACL CGI endpoint.
This is the simplest backend - just HTTP GET requests.

Usage:
    from pacsys.backends.acl import ACLBackend

    with ACLBackend() as backend:
        temp = backend.read("M:OUTTMP")
        reading = backend.get("M:OUTTMP")
        readings = backend.get_many(["M:OUTTMP", "G:AMANDA"])
"""

import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Optional

from pacsys.acnet.errors import ERR_OK, ERR_RETRY, ERR_TIMEOUT
from pacsys.backends import Backend
from pacsys.errors import DeviceError
from pacsys.types import (
    BackendCapability,
    Reading,
    Value,
    ValueType,
)

logger = logging.getLogger(__name__)

# Default settings
DEFAULT_BASE_URL = "https://www-bd.fnal.gov/cgi-bin/acl.pl"
DEFAULT_TIMEOUT = 5.0

# Escaped semicolon for separating ACL commands in CGI URLs.
# ACL Usage ref: "semicolons used to separate ACL commands should also be
# escaped by a backslash"
_ACL_CMD_SEP = "\\;"

# ACL error codes: DIO_NO_SUCH, CLIB_SYNTAX, DIO_NOSCALE, etc.
_ACL_ERROR_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")


def _parse_acl_line(text: str) -> tuple[Value, ValueType]:
    """Parse a single line of ACL output into a value and type.

    ACL output format is typically: ``DEVICE = VALUE [UNITS]``
    For alarm/description fields the format varies but always uses '='.
    Lines without '=' (e.g. bare numeric from no_name/no_units) are also handled.
    """
    text = text.strip()

    # Extract value part after '='
    if "=" in text:
        _, _, raw = text.partition("=")
        raw = raw.strip()
    else:
        raw = text

    if not raw:
        return text, ValueType.TEXT

    # 1. Try whole string as float (e.g. "12.34")
    try:
        return float(raw), ValueType.SCALAR
    except ValueError:
        pass

    tokens = raw.split()

    # 2. Try all tokens as floats → array (e.g. "45 2.2 3.0")
    if len(tokens) > 1:
        try:
            return [float(t) for t in tokens], ValueType.SCALAR_ARRAY
        except ValueError:
            pass

    # 3. Try all-but-last as floats → array + units (e.g. "45 2.2 3.0 blip")
    if len(tokens) > 2:
        try:
            return [float(t) for t in tokens[:-1]], ValueType.SCALAR_ARRAY
        except ValueError:
            pass

    # 4. Try first token as float → scalar + units (e.g. "12.34 DegF")
    try:
        return float(tokens[0]), ValueType.SCALAR
    except ValueError:
        pass

    # 5. Text
    return raw, ValueType.TEXT


def _is_error_response(text: str) -> tuple[bool, Optional[str]]:
    """Check if an ACL response line indicates an error.

    ACL errors look like::

        ! error message
        Invalid device name (...) ... - DIO_NO_SUCH
        Error reading device ... - DIO_NOSCALE
    """
    text = text.strip()

    if text.startswith("!"):
        return True, text[1:].strip()

    # ACL errors end with " - ERROR_CODE" (e.g. DIO_NO_SUCH, CLIB_SYNTAX)
    if " - " in text:
        error_code = text.rsplit(" - ", 1)[-1].strip()
        if _ACL_ERROR_CODE_RE.match(error_code):
            return True, text

    return False, None


class ACLBackend(Backend):
    """
    ACL backend for HTTP-based device reads (read-only).

    Uses the ACL CGI endpoint for simple device access.
    No streaming, no authentication, no writes.

    Capabilities:
        - READ: Always enabled
        - WRITE: No (read-only backend)
        - STREAM: No (HTTP is request/response only)
        - AUTH: No (public endpoint)
        - BATCH: Yes (get_many supported)

    Example:
        with ACLBackend() as backend:
            temp = backend.read("M:OUTTMP")
            reading = backend.get("M:OUTTMP")
            readings = backend.get_many(["M:OUTTMP", "G:AMANDA"])
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        """
        Initialize ACL backend.

        Args:
            base_url: ACL CGI URL (default: https://www-bd.fnal.gov/cgi-bin/acl.pl)
            timeout: HTTP request timeout in seconds (default: 5.0)

        Raises:
            ValueError: If parameters are invalid
        """
        effective_url = base_url if base_url is not None else DEFAULT_BASE_URL
        effective_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

        if not effective_url:
            raise ValueError("base_url cannot be empty")
        if effective_timeout <= 0:
            raise ValueError(f"timeout must be positive, got {effective_timeout}")

        self._base_url = effective_url
        self._timeout = effective_timeout
        self._closed = False

        logger.debug(f"ACLBackend initialized: base_url={effective_url}, timeout={effective_timeout}")

    @property
    def capabilities(self) -> BackendCapability:
        """ACL only supports READ and BATCH."""
        return BackendCapability.READ | BackendCapability.BATCH

    @property
    def base_url(self) -> str:
        """ACL CGI base URL."""
        return self._base_url

    @property
    def timeout(self) -> float:
        """Default request timeout."""
        return self._timeout

    def _build_url(self, drfs: list[str]) -> str:
        """Build ACL CGI URL for one or more devices.

        ACL ``read`` takes exactly one device; multiple devices are sent as
        separate ``read`` commands joined by ``\\;`` (escaped semicolon).

        Single:   ``?acl=read+DEVICE``
        Batch:    ``?acl=read+DEV1\\;read+DEV2\\;read+DEV3``
        """
        # The ACL CGI only decodes spaces (+/%20) and quotes (%27) from the
        # query string — general %XX sequences like %3A are NOT decoded.
        # DRF characters (colons, brackets, etc.) must be sent raw.
        commands = [f"read+{urllib.parse.quote(drf, safe=':[]@,.$|~')}" for drf in drfs]
        return f"{self._base_url}?acl={_ACL_CMD_SEP.join(commands)}"

    def execute(self, acl_command: str, timeout: Optional[float] = None) -> str:
        """Execute a raw ACL command string and return the text output.

        The *acl_command* is placed verbatim after ``?acl=`` in the CGI URL.
        Spaces should be ``+``, semicolons escaped as ``\\;``.

        Example::

            backend.execute("read+M:OUTTMP")
            backend.execute(
                "device_list/create+devs+devices='M:OUTTMP,G:AMANDA'"
                "\\\\;read_list/no_name/no_units+device_list=devs"
            )
        """
        if self._closed:
            raise RuntimeError("Backend is closed")
        effective_timeout = timeout if timeout is not None else self._timeout
        url = f"{self._base_url}?acl={acl_command}"
        return self._fetch(url, effective_timeout)

    def _fetch(self, url: str, timeout: float) -> str:
        """Fetch URL content.

        Raises:
            DeviceError: If HTTP request fails
        """
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise DeviceError(
                drf="",
                facility_code=0,
                error_code=ERR_RETRY,
                message=f"ACL request failed ({url}): HTTP {e.code} {e.reason}",
            )
        except urllib.error.URLError as e:
            raise DeviceError(
                drf="",
                facility_code=0,
                error_code=ERR_RETRY,
                message=f"ACL request failed ({self._base_url}): {e.reason}",
            )
        except TimeoutError:
            raise DeviceError(
                drf="",
                facility_code=0,
                error_code=ERR_TIMEOUT,
                message=f"ACL request timed out after {timeout}s ({self._base_url})",
            )

    def read(self, drf: str, timeout: Optional[float] = None) -> Value:
        """Read a single device value via HTTP.

        Raises:
            RuntimeError: If backend is closed
            DeviceError: If the read fails
        """
        reading = self.get(drf, timeout=timeout)

        if not reading.ok:
            raise DeviceError(
                drf=reading.drf,
                facility_code=reading.facility_code,
                error_code=reading.error_code,
                message=reading.message or f"Read failed with status {reading.error_code}",
            )

        assert reading.value is not None
        return reading.value

    def get(self, drf: str, timeout: Optional[float] = None) -> Reading:
        """Read a single device with metadata via HTTP."""
        readings = self.get_many([drf], timeout=timeout)
        return readings[0]

    def get_many(self, drfs: list[str], timeout: Optional[float] = None) -> list[Reading]:
        """Read multiple devices via HTTP.

        Sends all reads in a single request using semicolon-separated ACL
        commands.  If the batch fails (e.g. one bad device aborts the whole
        script), falls back to issuing one HTTP request per device so that
        valid devices still return data and only the bad ones get errors.

        .. todo:: When all DRFs share the same property, use ``device_list``
           + ``read_list`` for a true simultaneous batch read instead of
           sequential ``read`` commands.
        """
        if self._closed:
            raise RuntimeError("Backend is closed")

        if not drfs:
            return []

        effective_timeout = timeout if timeout is not None else self._timeout

        url = self._build_url(drfs)
        logger.debug(f"ACL batch request: {url}")

        try:
            response_text = self._fetch(url, effective_timeout)
        except DeviceError as e:
            # HTTP-level error — all devices fail
            return [
                Reading(
                    drf=drf,
                    value_type=ValueType.SCALAR,
                    facility_code=e.facility_code,
                    error_code=e.error_code,
                    message=e.message,
                    timestamp=datetime.now(),
                )
                for drf in drfs
            ]

        logger.debug(f"ACL batch response: {response_text[:200]}")

        lines = response_text.strip().splitlines()

        # ACL aborts the whole script on the first bad device, so if line
        # count doesn't match or any line is an error, fall back to
        # individual reads to isolate the failure(s).
        if len(lines) != len(drfs) or any(_is_error_response(line)[0] for line in lines):
            logger.debug(
                "ACL batch error/mismatch (%d lines for %d drfs), falling back to individual reads",
                len(lines),
                len(drfs),
            )
            return self._get_many_individual(drfs, effective_timeout)

        # Happy path: one line per device, in order
        readings: list[Reading] = []
        now = datetime.now()
        for drf, line in zip(drfs, lines):
            value, value_type = _parse_acl_line(line)
            readings.append(
                Reading(
                    drf=drf,
                    value_type=value_type,
                    value=value,
                    error_code=ERR_OK,
                    timestamp=now,
                )
            )
        return readings

    def _get_many_individual(self, drfs: list[str], timeout: float) -> list[Reading]:
        """Fallback: read each device individually to isolate errors."""
        readings: list[Reading] = []
        now = datetime.now()
        for drf in drfs:
            url = self._build_url([drf])
            try:
                response_text = self._fetch(url, timeout)
                line = response_text.strip().splitlines()[0]
                is_error, error_msg = _is_error_response(line)
                if is_error:
                    readings.append(
                        Reading(
                            drf=drf,
                            value_type=ValueType.SCALAR,
                            facility_code=0,
                            error_code=ERR_RETRY,
                            message=error_msg,
                            timestamp=now,
                        )
                    )
                else:
                    value, value_type = _parse_acl_line(line)
                    readings.append(
                        Reading(
                            drf=drf,
                            value_type=value_type,
                            value=value,
                            error_code=ERR_OK,
                            timestamp=now,
                        )
                    )
            except DeviceError as e:
                readings.append(
                    Reading(
                        drf=drf,
                        value_type=ValueType.SCALAR,
                        facility_code=e.facility_code,
                        error_code=e.error_code,
                        message=e.message,
                        timestamp=now,
                    )
                )
        return readings

    def close(self) -> None:
        """Close the backend. No resources to clean up for HTTP client."""
        self._closed = True
        logger.debug("ACLBackend closed")

    def __repr__(self) -> str:
        status = "closed" if self._closed else "open"
        return f"ACLBackend({self._base_url}, timeout={self._timeout}, {status})"


__all__ = ["ACLBackend"]
