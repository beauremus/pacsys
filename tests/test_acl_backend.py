"""
Unit tests for ACLBackend.

Tests cover:
- Backend initialization and capabilities
- ACL output line parsing (DEVICE = VALUE UNITS format)
- Error detection (ACL error codes, ! prefix)
- URL construction (single and batch with \\; separator)
- Single device read/get
- Multiple device read with batch fallback
- HTTP error handling
- Timeout handling
"""

import urllib.error
from unittest import mock

import pytest

from pacsys.backends.acl import (
    ACLBackend,
    _parse_acl_line,
    _is_error_response,
)
from pacsys.errors import DeviceError
from pacsys.types import Reading, ValueType
from tests.conftest import MockACLResponse


class TestACLBackendInit:
    """Tests for ACLBackend input validation."""

    @pytest.mark.parametrize(
        "kwargs,match",
        [
            ({"base_url": ""}, "base_url cannot be empty"),
            ({"timeout": 0}, "timeout must be positive"),
            ({"timeout": -1.0}, "timeout must be positive"),
        ],
    )
    def test_invalid_init_params(self, kwargs, match):
        with pytest.raises(ValueError, match=match):
            ACLBackend(**kwargs)


class TestParseACLLine:
    """Tests for _parse_acl_line — parses full ACL output lines."""

    @pytest.mark.parametrize(
        "line,expected_value,expected_type",
        [
            # Scalar with device name and units
            ("M:OUTTMP       =  12.34 DegF", 12.34, ValueType.SCALAR),
            ("G:AMANDA       =  66", 66.0, ValueType.SCALAR),
            # Alarm fields (no_name/no_units ignored by ACL)
            ("Z:ACLTST alarm maximum = 50 blip", 50.0, ValueType.SCALAR),
            ("Z:ACLTST alarm minimum = -4.007 DegF", -4.007, ValueType.SCALAR),
            # Description (text after =)
            (
                "M:OUTTMP = Outdoor temperature (F)",
                "Outdoor temperature (F)",
                ValueType.TEXT,
            ),
            # Bare numeric (no = sign, e.g. from no_name/no_units)
            ("  12.68", 12.68, ValueType.SCALAR),
            ("42", 42.0, ValueType.SCALAR),
            ("-3.14", -3.14, ValueType.SCALAR),
            ("1.23e-4", pytest.approx(1.23e-4), ValueType.SCALAR),
            # Array (all-numeric tokens)
            ("45  2.2  2  102.81933", [45, 2.2, 2, 102.81933], ValueType.SCALAR_ARRAY),
            # Array with units (all-but-last numeric)
            ("45  2.2  3.0 blip", [45.0, 2.2, 3.0], ValueType.SCALAR_ARRAY),
            # Pure text
            ("Hello World", "Hello World", ValueType.TEXT),
        ],
    )
    def test_parse_acl_line(self, line, expected_value, expected_type):
        value, vtype = _parse_acl_line(line)
        assert value == expected_value
        assert vtype == expected_type


class TestIsErrorResponse:
    """Tests for error detection."""

    def test_exclamation_prefix(self):
        is_error, msg = _is_error_response("! Device not found")
        assert is_error is True
        assert msg == "Device not found"

    def test_acl_error_code_pattern(self):
        line = "Invalid device name (Z:BAD) in read device command at line 0 - DIO_NO_SUCH"
        is_error, msg = _is_error_response(line)
        assert is_error is True
        assert "DIO_NO_SUCH" in msg

    def test_clib_error_code(self):
        line = "Invalid read value variable (G:AMANDA) specified in read_device command at line 1 - CLIB_SYNTAX"
        is_error, msg = _is_error_response(line)
        assert is_error is True

    def test_normal_reading_not_error(self):
        is_error, msg = _is_error_response("M:OUTTMP       =  12.34 DegF")
        assert is_error is False
        assert msg is None

    def test_bare_number_not_error(self):
        is_error, msg = _is_error_response("72.5")
        assert is_error is False

    def test_description_with_dash_not_error(self):
        """A description containing ' - ' should not be a false positive."""
        is_error, msg = _is_error_response("M:FOO = Temperature - external sensor")
        assert is_error is False


class TestBuildURL:
    """Tests for URL construction."""

    def test_single_device_url(self):
        backend = ACLBackend()
        url = backend._build_url(["M:OUTTMP"])
        assert "?acl=read+M:OUTTMP" in url
        assert "\\;" not in url  # no semicolons for single device
        backend.close()

    def test_batch_url_uses_semicolons(self):
        backend = ACLBackend()
        url = backend._build_url(["M:OUTTMP", "G:AMANDA"])
        assert "read+M:OUTTMP\\;read+G:AMANDA" in url
        backend.close()

    def test_default_base_url(self):
        backend = ACLBackend()
        assert "www-bd.fnal.gov" in backend.base_url
        backend.close()


class TestSingleDeviceRead:
    """Tests for single device read/get operations."""

    def test_read_scalar_success(self):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = MockACLResponse("M:OUTTMP       =  72.5 DegF")
            backend = ACLBackend()
            try:
                value = backend.read("M:OUTTMP")
                assert value == 72.5
            finally:
                backend.close()

    def test_read_text_success(self):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = MockACLResponse("M:OUTTMP = Outdoor Temperature")
            backend = ACLBackend()
            try:
                value = backend.read("M:OUTTMP.DESCRIPTION")
                assert value == "Outdoor Temperature"
            finally:
                backend.close()

    def test_get_returns_reading(self):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = MockACLResponse("M:OUTTMP       =  72.5 DegF")
            backend = ACLBackend()
            try:
                reading = backend.get("M:OUTTMP")
                assert isinstance(reading, Reading)
                assert reading.value == 72.5
                assert reading.value_type == ValueType.SCALAR
                assert reading.ok
            finally:
                backend.close()

    def test_read_error_raises_device_error(self):
        """ACL error triggers fallback which also errors → DeviceError."""
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            # Both batch and individual read return the error
            mock_urlopen.return_value = MockACLResponse("Invalid device name (M:BADDEV) in read command - DIO_NO_SUCH")
            backend = ACLBackend()
            try:
                with pytest.raises(DeviceError):
                    backend.read("M:BADDEV")
            finally:
                backend.close()

    def test_get_error_returns_error_reading(self):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = MockACLResponse("Invalid device name (M:BADDEV) in read command - DIO_NO_SUCH")
            backend = ACLBackend()
            try:
                reading = backend.get("M:BADDEV")
                assert reading.is_error
                assert "DIO_NO_SUCH" in reading.message
            finally:
                backend.close()


class TestMultipleDeviceRead:
    """Tests for get_many — batch and fallback behavior."""

    def test_batch_success(self):
        """All devices succeed in a single batch request."""
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = MockACLResponse("M:OUTTMP       =  72.5 DegF\nG:AMANDA       =  66")
            backend = ACLBackend()
            try:
                readings = backend.get_many(["M:OUTTMP", "G:AMANDA"])
                assert len(readings) == 2
                assert readings[0].value == 72.5
                assert readings[1].value == 66.0
            finally:
                backend.close()

    def test_fallback_on_batch_error(self):
        """Bad device in batch triggers individual fallback."""
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            # First call (batch) returns error
            # Subsequent calls (individual) return per-device results
            mock_urlopen.side_effect = [
                # Batch: ACL aborts on bad device
                MockACLResponse("Invalid device name (Z:BAD) - DIO_NO_SUCH"),
                # Individual: M:OUTTMP succeeds
                MockACLResponse("M:OUTTMP       =  72.5 DegF"),
                # Individual: Z:BAD fails
                MockACLResponse("Invalid device name (Z:BAD) - DIO_NO_SUCH"),
                # Individual: G:AMANDA succeeds
                MockACLResponse("G:AMANDA       =  66"),
            ]
            backend = ACLBackend()
            try:
                readings = backend.get_many(["M:OUTTMP", "Z:BAD", "G:AMANDA"])
                assert len(readings) == 3
                assert readings[0].ok
                assert readings[0].value == 72.5
                assert readings[1].is_error
                assert "DIO_NO_SUCH" in readings[1].message
                assert readings[2].ok
                assert readings[2].value == 66.0
            finally:
                backend.close()

    def test_fallback_on_line_count_mismatch(self):
        """Fewer lines than DRFs triggers individual fallback."""
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = [
                # Batch: only 1 line for 2 devices
                MockACLResponse("M:OUTTMP       =  72.5 DegF"),
                # Individual reads
                MockACLResponse("M:OUTTMP       =  72.5 DegF"),
                MockACLResponse("G:AMANDA       =  66"),
            ]
            backend = ACLBackend()
            try:
                readings = backend.get_many(["M:OUTTMP", "G:AMANDA"])
                assert len(readings) == 2
                assert readings[0].ok
                assert readings[1].ok
            finally:
                backend.close()

    def test_empty_drfs(self):
        backend = ACLBackend()
        try:
            assert backend.get_many([]) == []
        finally:
            backend.close()


class TestHTTPErrors:
    """Tests for HTTP error handling."""

    def test_http_error_returns_error_readings(self):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.HTTPError(
                url="http://example.com",
                code=503,
                msg="Service Unavailable",
                hdrs={},
                fp=None,
            )
            backend = ACLBackend()
            try:
                readings = backend.get_many(["M:OUTTMP", "G:AMANDA"])
                assert len(readings) == 2
                assert all(r.is_error for r in readings)
                assert all("HTTP 503" in r.message for r in readings)
            finally:
                backend.close()

    def test_url_error(self):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
            backend = ACLBackend()
            try:
                with pytest.raises(DeviceError, match="ACL request failed"):
                    backend.read("M:OUTTMP")
            finally:
                backend.close()

    def test_timeout_error(self):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = TimeoutError("timed out")
            backend = ACLBackend()
            try:
                with pytest.raises(DeviceError, match="timed out"):
                    backend.read("M:OUTTMP")
            finally:
                backend.close()


class TestContextManager:
    """Tests for context manager usage."""

    def test_context_manager_closes(self):
        with ACLBackend() as backend:
            assert not backend._closed
        assert backend._closed

    def test_context_manager_on_exception(self):
        try:
            with ACLBackend() as backend:
                raise ValueError("test error")
        except ValueError:
            pass
        assert backend._closed

    def test_close_multiple_times_safe(self):
        backend = ACLBackend()
        backend.close()
        backend.close()
        assert backend._closed


class TestWriteNotSupported:
    """Tests for write operations."""

    def test_write_raises_not_implemented(self):
        backend = ACLBackend()
        try:
            with pytest.raises(NotImplementedError):
                backend.write("M:OUTTMP", 72.5)
        finally:
            backend.close()

    def test_write_many_raises_not_implemented(self):
        backend = ACLBackend()
        try:
            with pytest.raises(NotImplementedError):
                backend.write_many([("M:OUTTMP", 72.5)])
        finally:
            backend.close()


class TestOperationAfterClose:
    """Tests for operations after close."""

    def test_read_after_close_raises(self):
        backend = ACLBackend()
        backend.close()
        with pytest.raises(RuntimeError, match="Backend is closed"):
            backend.read("M:OUTTMP")

    def test_get_many_after_close_raises(self):
        backend = ACLBackend()
        backend.close()
        with pytest.raises(RuntimeError, match="Backend is closed"):
            backend.get_many(["M:OUTTMP"])


class TestTimeout:
    """Tests for timeout handling."""

    def test_custom_timeout_passed_to_urlopen(self):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = MockACLResponse("M:OUTTMP = 72.5")
            backend = ACLBackend(timeout=3.0)
            try:
                backend.read("M:OUTTMP")
                assert mock_urlopen.call_args[1]["timeout"] == 3.0
            finally:
                backend.close()

    def test_per_call_timeout_overrides_default(self):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = MockACLResponse("M:OUTTMP = 72.5")
            backend = ACLBackend(timeout=10.0)
            try:
                backend.read("M:OUTTMP", timeout=2.0)
                assert mock_urlopen.call_args[1]["timeout"] == 2.0
            finally:
                backend.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
