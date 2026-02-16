"""Tests for AsyncDevice."""

from unittest import mock

import pytest

from pacsys.testing import AsyncFakeBackend
from pacsys.types import BasicControl
from pacsys.aio._device import AsyncDevice


class TestAsyncDeviceRead:
    @pytest.mark.asyncio
    async def test_read(self):
        fb = AsyncFakeBackend()
        fb.set_reading("M:OUTTMP.READING", 72.5)

        device = AsyncDevice("M:OUTTMP", backend=fb)
        val = await device.read()
        assert val == 72.5
        assert fb.was_read("M:OUTTMP.READING")

    @pytest.mark.asyncio
    async def test_setting(self):
        fb = AsyncFakeBackend()
        fb.set_reading("M:OUTTMP.SETTING", 50.0)

        device = AsyncDevice("M:OUTTMP", backend=fb)
        val = await device.setting()
        assert val == 50.0
        assert fb.was_read("M:OUTTMP.SETTING")

    @pytest.mark.asyncio
    async def test_status_bool(self):
        fb = AsyncFakeBackend()
        fb.set_reading("M:OUTTMP.STATUS.ON", 1)

        device = AsyncDevice("M:OUTTMP", backend=fb)
        val = await device.status(field="on")
        assert val is True

    @pytest.mark.asyncio
    async def test_status_raw(self):
        fb = AsyncFakeBackend()
        fb.set_reading("M:OUTTMP.STATUS.RAW", 0xFF)

        device = AsyncDevice("M:OUTTMP", backend=fb)
        val = await device.status(field="raw")
        assert val == 0xFF


class TestAsyncDeviceWrite:
    @pytest.mark.asyncio
    async def test_write(self):
        fb = AsyncFakeBackend()
        fb.set_reading("M:OUTTMP.SETTING", 72.5)

        device = AsyncDevice("M:OUTTMP", backend=fb)
        result = await device.write(72.5)
        assert result.success
        assert fb.was_written("M:OUTTMP.SETTING")

    @pytest.mark.asyncio
    async def test_write_with_verify(self):
        from pacsys.verify import Verify

        fb = AsyncFakeBackend()
        fb.set_reading("M:OUTTMP.SETTING", 72.5)
        fb.set_reading("M:OUTTMP.READING", 72.5)

        device = AsyncDevice("M:OUTTMP", backend=fb)
        v = Verify(initial_delay=0.0, retry_delay=0.0)
        result = await device.write(72.5, verify=v)
        assert result.verified

    @pytest.mark.asyncio
    async def test_control_on(self):
        fb = AsyncFakeBackend()
        fb.set_reading("M:OUTTMP.CONTROL", 0)

        device = AsyncDevice("M:OUTTMP", backend=fb)
        result = await device.on()
        assert result.success
        assert fb.was_written("M:OUTTMP.CONTROL")
        # Verify the command value was BasicControl.ON
        _, written_value = fb.writes[-1]
        assert written_value == BasicControl.ON


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
