"""Tests for AsyncDevice."""

from unittest import mock

import pytest

from pacsys.types import WriteResult, BasicControl
from pacsys.aio._device import AsyncDevice


class TestAsyncDeviceRead:
    @pytest.mark.asyncio
    async def test_read(self):
        backend = mock.AsyncMock()
        backend.read = mock.AsyncMock(return_value=72.5)

        device = AsyncDevice("M:OUTTMP", backend=backend)
        val = await device.read()
        assert val == 72.5
        backend.read.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_setting(self):
        backend = mock.AsyncMock()
        backend.read = mock.AsyncMock(return_value=50.0)

        device = AsyncDevice("M:OUTTMP", backend=backend)
        val = await device.setting()
        assert val == 50.0

    @pytest.mark.asyncio
    async def test_status_bool(self):
        backend = mock.AsyncMock()
        backend.read = mock.AsyncMock(return_value=1)

        device = AsyncDevice("M:OUTTMP", backend=backend)
        val = await device.status(field="on")
        assert val is True

    @pytest.mark.asyncio
    async def test_status_raw(self):
        backend = mock.AsyncMock()
        backend.read = mock.AsyncMock(return_value=0xFF)

        device = AsyncDevice("M:OUTTMP", backend=backend)
        val = await device.status(field="raw")
        assert val == 0xFF


class TestAsyncDeviceWrite:
    @pytest.mark.asyncio
    async def test_write(self):
        backend = mock.AsyncMock()
        backend.write = mock.AsyncMock(return_value=WriteResult(drf="M:OUTTMP.SETTING@N"))

        device = AsyncDevice("M:OUTTMP", backend=backend)
        result = await device.write(72.5)
        assert result.success
        backend.write.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_write_with_verify(self):
        from pacsys.verify import Verify

        backend = mock.AsyncMock()
        backend.write = mock.AsyncMock(return_value=WriteResult(drf="M:OUTTMP.SETTING@N"))
        backend.read = mock.AsyncMock(return_value=72.5)

        device = AsyncDevice("M:OUTTMP", backend=backend)
        v = Verify(initial_delay=0.0, retry_delay=0.0)
        result = await device.write(72.5, verify=v)
        assert result.verified

    @pytest.mark.asyncio
    async def test_control_on(self):
        backend = mock.AsyncMock()
        backend.write = mock.AsyncMock(return_value=WriteResult(drf="M:OUTTMP.CONTROL@N"))

        device = AsyncDevice("M:OUTTMP", backend=backend)
        result = await device.on()
        assert result.success
        # Should have written to CONTROL property
        call_args = backend.write.call_args
        assert ".CONTROL@N" in call_args[0][0]
        assert call_args[0][1] == BasicControl.ON


class TestAsyncDeviceFluent:
    def test_with_event(self):
        device = AsyncDevice("M:OUTTMP")
        d2 = device.with_event("p,1000")
        assert isinstance(d2, AsyncDevice)
        assert d2.is_periodic

    def test_with_range(self):
        device = AsyncDevice("B:HS23T")
        d2 = device.with_range(start=0, end=10)
        assert isinstance(d2, AsyncDevice)
        assert "[0:10]" in d2.drf

    def test_with_backend(self):
        backend1 = mock.AsyncMock()
        backend2 = mock.AsyncMock()

        device = AsyncDevice("M:OUTTMP", backend=backend1)
        d2 = device.with_backend(backend2)
        assert isinstance(d2, AsyncDevice)
        assert d2._backend is backend2

    def test_repr(self):
        device = AsyncDevice("M:OUTTMP")
        assert "AsyncDevice" in repr(device)

    def test_equality(self):
        d1 = AsyncDevice("M:OUTTMP")
        d2 = AsyncDevice("M:OUTTMP")
        assert d1 == d2

    def test_hash(self):
        d1 = AsyncDevice("M:OUTTMP")
        d2 = AsyncDevice("M:OUTTMP")
        assert hash(d1) == hash(d2)
        assert len({d1, d2}) == 1
