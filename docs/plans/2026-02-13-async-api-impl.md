# Async API (`pacsys.aio`) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add native async API (`pacsys.aio`) with gRPC and DPM/HTTP backends, enabling single-event-loop operation for async applications.

**Architecture:** `AsyncBackend` ABC mirrors sync `Backend`. gRPC wraps existing `_DaqCore` directly. DPM/HTTP uses new `_AsyncDpmCore` (unified read/write/stream over `_AsyncDPMConnection`). `_DeviceBase` mixin shares DRF logic between `Device` and `AsyncDevice`. See `docs/plans/2026-02-13-async-api-design.md` for full design.

**Tech Stack:** Python asyncio, pytest-asyncio, grpc.aio, existing `_AsyncDPMConnection`

---

### Task 1: Add pytest-asyncio dev dependency

**Files:**
- Modify: `pyproject.toml:47-56`

**Step 1: Add pytest-asyncio to dev dependencies**

In `pyproject.toml`, add `"pytest-asyncio"` to `[project.optional-dependencies] dev`:

```toml
[project.optional-dependencies]
dev = [
  "pytest",
  "pytest-asyncio",
  "pytest-cov",
  "ruff",
  "ty",
  "pre-commit",
  "types-grpcio",
  "types-pika-ts",
  "types-protobuf",
]
```

**Step 2: Install**

Run: `pip install pytest-asyncio`

**Step 3: Verify**

Run: `python -c "import pytest_asyncio; print(pytest_asyncio.__version__)"`
Expected: version string printed

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "add pytest-asyncio dev dependency"
```

---

### Task 2: Extract `_DeviceBase` from `Device`

**Files:**
- Create: `pacsys/_device_base.py`
- Modify: `pacsys/device.py`
- Test: `tests/test_device.py` (existing tests must still pass)

**Step 1: Run existing device tests to establish baseline**

Run: `python -m pytest tests/test_device.py -v -x 2>&1 | tail -10`
Expected: all PASSED

**Step 2: Create `_DeviceBase` with pure logic extracted from `Device`**

Create `pacsys/_device_base.py`. Move these from `Device`:
- `_CONTROL_STATUS_MAP` (module-level constant)
- `_BOOL_STATUS_FIELDS` (class constant)
- Properties: `drf`, `name`, `request`, `has_event`, `is_periodic`
- Helpers: `_build_drf()`, `_resolve_field()`
- Fluent: `with_event()`, `with_range()`
- Dunder: `__repr__`, `__eq__`, `__hash__`

`_DeviceBase.__init__` takes `request: DataRequest` (already parsed), not a raw DRF string. `Device.__init__` calls `parse_request(drf)` then `super().__init__(request)`.

```python
"""Shared base for Device and AsyncDevice - pure DRF logic, no I/O."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pacsys.drf3 import DataRequest, parse_event
from pacsys.drf3.field import (
    DRF_FIELD,
    parse_field,
    DEFAULT_FIELD_FOR_PROPERTY,
    ALLOWED_FIELD_FOR_PROPERTY,
)
from pacsys.drf3.property import DRF_PROPERTY
from pacsys.drf3.range import ARRAY_RANGE
from pacsys.drf3.event import PeriodicEvent
from pacsys.types import BasicControl

if TYPE_CHECKING:
    pass

CONTROL_STATUS_MAP: dict[BasicControl, tuple[str, bool]] = {
    BasicControl.ON: ("on", True),
    BasicControl.OFF: ("on", False),
    BasicControl.RESET: ("ready", True),
    BasicControl.TRIP: ("ready", False),
    BasicControl.POSITIVE: ("positive", True),
    BasicControl.NEGATIVE: ("positive", False),
    BasicControl.RAMP: ("ramp", True),
    BasicControl.DC: ("ramp", False),
    BasicControl.REMOTE: ("remote", True),
    BasicControl.LOCAL: ("remote", False),
}


class _DeviceBase:
    """DRF building, field resolution, fluent modification. No I/O."""

    __slots__ = ("_request",)

    _BOOL_STATUS_FIELDS = frozenset({"ON", "READY", "REMOTE", "POSITIVE", "RAMP"})

    def __init__(self, request: DataRequest):
        object.__setattr__(self, "_request", request)

    @property
    def drf(self) -> str:
        return self._request.to_canonical()

    @property
    def name(self) -> str:
        return self._request.device

    @property
    def request(self) -> DataRequest:
        return self._request

    @property
    def has_event(self) -> bool:
        return self._request.event is not None and self._request.event.mode != "U"

    @property
    def is_periodic(self) -> bool:
        return isinstance(self._request.event, PeriodicEvent)

    def _build_drf(self, prop: DRF_PROPERTY, field: DRF_FIELD | None, event: str) -> str:
        out = self.name
        out += f".{prop.name}"
        if self._request.range is not None:
            out += str(self._request.range)
        if field is not None:
            default = DEFAULT_FIELD_FOR_PROPERTY.get(prop)
            if field != default:
                out += f".{field.name}"
        out += f"@{event}"
        if self._request.extra is not None:
            out += f"<-{self._request.extra.name}"
        return out

    def _resolve_field(self, field: str | None, prop: DRF_PROPERTY) -> DRF_FIELD | None:
        if field is None:
            return DEFAULT_FIELD_FOR_PROPERTY.get(prop)
        f = parse_field(field.upper())
        allowed = ALLOWED_FIELD_FOR_PROPERTY.get(prop, [])
        if f not in allowed:
            raise ValueError(f"Field '{field}' not allowed for {prop.name}")
        return f

    def with_event(self, event: str) -> "_DeviceBase":
        new_event = parse_event(event)
        new_drf = self._request.to_canonical(event=new_event)
        # Subclass.__init__ takes (drf, backend=None), so pass the DRF
        # Handled by subclasses overriding with proper __init__ signature
        return self._from_drf(new_drf)

    def with_range(self, start: int | None = None, end: int | None = None, *, at: int | None = None) -> "_DeviceBase":
        if at is not None:
            if start is not None or end is not None:
                raise ValueError("'at' cannot be combined with 'start'/'end'")
            new_range = ARRAY_RANGE(mode="single", low=at)
        elif start is not None:
            new_range = ARRAY_RANGE(mode="std", low=start, high=end)
        else:
            new_range = ARRAY_RANGE(mode="full")
        new_drf = self._request.to_canonical(range=new_range)
        return self._from_drf(new_drf)

    def _from_drf(self, drf: str) -> "_DeviceBase":
        """Create new instance of same type from DRF. Override in subclasses."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.drf!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _DeviceBase):
            return NotImplemented
        return self.drf == other.drf

    def __hash__(self) -> int:
        return hash(self.drf)
```

**Step 3: Refactor `Device` to inherit `_DeviceBase`**

Modify `pacsys/device.py`:
- Remove all logic now in `_DeviceBase` (properties, `_build_drf`, `_resolve_field`, `with_event`, `with_range`, `__repr__`, `__eq__`, `__hash__`, `_BOOL_STATUS_FIELDS`, `_CONTROL_STATUS_MAP`)
- `Device.__init__` calls `parse_request(drf)` then `super().__init__(request)`
- `Device.__slots__` becomes just `("_backend",)`
- Add `_from_drf` override: `return self.__class__(drf, self._backend)`
- Add `with_backend` method (takes `Backend`, returns `Device`)
- Import `CONTROL_STATUS_MAP` from `_device_base`
- All I/O methods (`read`, `write`, `get`, `control`, etc.) stay on `Device`
- `ScalarDevice`, `ArrayDevice`, `TextDevice` continue inheriting `Device`

**Step 4: Run existing device tests**

Run: `python -m pytest tests/test_device.py -v -x 2>&1 | tail -20`
Expected: all PASSED (no behavior change)

**Step 5: Run full test suite to check for regressions**

Run: `python -m pytest tests/ -v -x 2>&1 | tail -20`
Expected: all PASSED

**Step 6: Lint and format**

Run: `ruff check --fix -q pacsys/_device_base.py pacsys/device.py && ruff format -q pacsys/_device_base.py pacsys/device.py`

**Step 7: Commit**

```bash
git add pacsys/_device_base.py pacsys/device.py
git commit -m "extract _DeviceBase mixin from Device for async reuse"
```

---

### Task 3: Create `pacsys/aio/` package skeleton with `AsyncBackend` ABC

**Files:**
- Create: `pacsys/aio/__init__.py`
- Create: `pacsys/aio/_backends.py`
- Test: `tests/aio/__init__.py`, `tests/aio/test_async_backend.py`

**Step 1: Write test for AsyncBackend ABC**

Create `tests/aio/__init__.py` (empty) and `tests/aio/test_async_backend.py`:

```python
"""Tests for AsyncBackend ABC contract."""

import pytest

from pacsys.aio._backends import AsyncBackend
from pacsys.types import BackendCapability


class ConcreteAsyncBackend(AsyncBackend):
    """Minimal concrete implementation for testing ABC."""

    @property
    def capabilities(self):
        return BackendCapability.READ

    async def read(self, drf, timeout=None):
        return 42.0

    async def get(self, drf, timeout=None):
        raise NotImplementedError

    async def get_many(self, drfs, timeout=None):
        raise NotImplementedError

    async def close(self):
        pass


class TestAsyncBackendABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            AsyncBackend()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with ConcreteAsyncBackend() as b:
            assert b.capabilities == BackendCapability.READ

    @pytest.mark.asyncio
    async def test_write_raises_not_implemented(self):
        async with ConcreteAsyncBackend() as b:
            with pytest.raises(NotImplementedError):
                await b.write("M:OUTTMP", 1.0)

    @pytest.mark.asyncio
    async def test_subscribe_raises_not_implemented(self):
        async with ConcreteAsyncBackend() as b:
            with pytest.raises(NotImplementedError):
                await b.subscribe(["M:OUTTMP@p,1000"])

    def test_auth_defaults(self):
        b = ConcreteAsyncBackend()
        assert b.authenticated is False
        assert b.principal is None
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/aio/test_async_backend.py -v -x 2>&1 | tail -10`
Expected: FAIL (import error - module doesn't exist yet)

**Step 3: Create `AsyncBackend` ABC**

Create `pacsys/aio/_backends.py`:

```python
"""Async backend abstract base class."""

from abc import ABC, abstractmethod
from typing import Optional

from pacsys.types import (
    Value,
    Reading,
    WriteResult,
    BackendCapability,
    ReadingCallback,
    ErrorCallback,
)


class AsyncBackend(ABC):
    """Async counterpart of Backend. Same capabilities, all methods async."""

    @property
    @abstractmethod
    def capabilities(self) -> BackendCapability: ...

    @abstractmethod
    async def read(self, drf: str, timeout: Optional[float] = None) -> Value: ...

    @abstractmethod
    async def get(self, drf: str, timeout: Optional[float] = None) -> Reading: ...

    @abstractmethod
    async def get_many(self, drfs: list[str], timeout: Optional[float] = None) -> list[Reading]: ...

    async def write(self, drf: str, value: Value, timeout: Optional[float] = None) -> WriteResult:
        raise NotImplementedError("This backend does not support writes")

    async def write_many(
        self, settings: list[tuple[str, Value]], timeout: Optional[float] = None
    ) -> list[WriteResult]:
        raise NotImplementedError("This backend does not support writes")

    async def subscribe(
        self,
        drfs: list[str],
        callback: Optional[ReadingCallback] = None,
        on_error: Optional[ErrorCallback] = None,
    ):
        raise NotImplementedError("This backend does not support streaming")

    async def remove(self, handle) -> None:
        raise NotImplementedError("This backend does not support streaming")

    async def stop_streaming(self) -> None:
        raise NotImplementedError("This backend does not support streaming")

    @property
    def authenticated(self) -> bool:
        return False

    @property
    def principal(self) -> Optional[str]:
        return None

    @abstractmethod
    async def close(self) -> None: ...

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False
```

Create `pacsys/aio/__init__.py`:

```python
"""pacsys.aio - async API for pacsys backends."""

from pacsys.aio._backends import AsyncBackend

__all__ = ["AsyncBackend"]
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/aio/test_async_backend.py -v -x 2>&1 | tail -10`
Expected: all PASSED

**Step 5: Lint and commit**

```bash
ruff check --fix -q pacsys/aio/ tests/aio/ && ruff format -q pacsys/aio/ tests/aio/
git add pacsys/aio/ tests/aio/
git commit -m "add pacsys.aio package with AsyncBackend ABC"
```

---

### Task 4: `AsyncSubscriptionHandle`

**Files:**
- Create: `pacsys/aio/_subscription.py`
- Test: `tests/aio/test_async_subscription.py`

**Step 1: Write tests**

Create `tests/aio/test_async_subscription.py`:

```python
"""Tests for AsyncSubscriptionHandle."""

import asyncio

import pytest

from pacsys.types import Reading, ValueType


@pytest.fixture
def make_reading():
    def _make(val):
        return Reading(drf="M:OUTTMP", value_type=ValueType.SCALAR, value=val, error_code=0)
    return _make


class TestAsyncSubscriptionHandle:
    @pytest.mark.asyncio
    async def test_dispatch_and_iterate(self, make_reading):
        from pacsys.aio._subscription import AsyncSubscriptionHandle

        handle = AsyncSubscriptionHandle()
        handle._dispatch(make_reading(1.0))
        handle._dispatch(make_reading(2.0))
        handle._signal_stop()

        results = []
        async for reading, h in handle.readings():
            results.append(reading.value)
            assert h is handle
        assert results == [1.0, 2.0]

    @pytest.mark.asyncio
    async def test_error_propagation(self, make_reading):
        from pacsys.aio._subscription import AsyncSubscriptionHandle

        handle = AsyncSubscriptionHandle()
        handle._dispatch(make_reading(1.0))
        handle._signal_error(RuntimeError("boom"))

        results = []
        with pytest.raises(RuntimeError, match="boom"):
            async for reading, h in handle.readings():
                results.append(reading.value)
        assert results == [1.0]

    @pytest.mark.asyncio
    async def test_timeout(self):
        from pacsys.aio._subscription import AsyncSubscriptionHandle

        handle = AsyncSubscriptionHandle()
        with pytest.raises(asyncio.TimeoutError):
            async for _ in handle.readings(timeout=0.05):
                pass

    @pytest.mark.asyncio
    async def test_overflow_drops(self, make_reading):
        from pacsys.aio._subscription import AsyncSubscriptionHandle

        handle = AsyncSubscriptionHandle()
        handle._maxsize = 3
        handle._queue = asyncio.Queue(maxsize=3)
        for i in range(5):
            handle._dispatch(make_reading(float(i)))
        handle._signal_stop()

        results = []
        async for reading, _ in handle.readings():
            results.append(reading.value)
        assert len(results) == 3  # 2 dropped

    @pytest.mark.asyncio
    async def test_stopped_property(self):
        from pacsys.aio._subscription import AsyncSubscriptionHandle

        handle = AsyncSubscriptionHandle()
        assert handle.stopped is False
        handle._signal_stop()
        assert handle.stopped is True

    @pytest.mark.asyncio
    async def test_callback_feeder_async(self, make_reading):
        from pacsys.aio._subscription import AsyncSubscriptionHandle, _callback_feeder

        handle = AsyncSubscriptionHandle()
        collected = []

        async def cb(reading, h):
            collected.append(reading.value)

        task = asyncio.ensure_future(_callback_feeder(handle, cb, None))
        handle._dispatch(make_reading(10.0))
        handle._dispatch(make_reading(20.0))
        handle._signal_stop()
        await task
        assert collected == [10.0, 20.0]

    @pytest.mark.asyncio
    async def test_callback_feeder_sync(self, make_reading):
        from pacsys.aio._subscription import AsyncSubscriptionHandle, _callback_feeder

        handle = AsyncSubscriptionHandle()
        collected = []

        def cb(reading, h):
            collected.append(reading.value)

        task = asyncio.ensure_future(_callback_feeder(handle, cb, None))
        handle._dispatch(make_reading(5.0))
        handle._signal_stop()
        await task
        assert collected == [5.0]
```

**Step 2: Run to verify fails**

Run: `python -m pytest tests/aio/test_async_subscription.py -v -x 2>&1 | tail -10`
Expected: FAIL (import error)

**Step 3: Implement `AsyncSubscriptionHandle`**

Create `pacsys/aio/_subscription.py`:

```python
"""Async subscription handle using asyncio.Queue."""

import asyncio
import inspect
import logging
import time
from typing import AsyncIterator, Optional

from pacsys.types import Reading

logger = logging.getLogger(__name__)

_DEFAULT_BUFFER_MAXSIZE = 10_000


class AsyncSubscriptionHandle:
    """Async counterpart of BufferedSubscriptionHandle.

    Uses asyncio.Queue for zero-polling async iteration.
    Producer calls _dispatch() (sync, non-blocking).
    Consumer uses async for reading, handle in handle.readings().
    """

    def __init__(self) -> None:
        self._maxsize = _DEFAULT_BUFFER_MAXSIZE
        self._queue: asyncio.Queue[Reading | None] = asyncio.Queue(maxsize=self._maxsize)
        self._stopped = False
        self._exc: Optional[Exception] = None
        self._task: Optional[asyncio.Task] = None
        self._callback_task: Optional[asyncio.Task] = None
        self._drop_count = 0
        self._last_drop_log = 0.0

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def exc(self) -> Optional[Exception]:
        return self._exc

    # -- Producer API (called from core's dispatch_fn) -------------------------

    def _dispatch(self, reading: Reading) -> None:
        if self._stopped:
            return
        try:
            self._queue.put_nowait(reading)
        except asyncio.QueueFull:
            self._drop_count += 1
            now = time.monotonic()
            if now - self._last_drop_log >= 5.0:
                logger.warning(
                    "Async subscription buffer full (%d), dropped %d readings",
                    self._maxsize,
                    self._drop_count,
                )
                self._drop_count = 0
                self._last_drop_log = now

    def _signal_stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            pass  # consumer will see _stopped flag

    def _signal_error(self, exc: Exception) -> None:
        if self._exc is None:
            self._exc = exc
        self._signal_stop()

    def _is_stopped(self) -> bool:
        return self._stopped

    # -- Consumer API ----------------------------------------------------------

    async def readings(
        self, timeout: Optional[float] = None
    ) -> AsyncIterator[tuple[Reading, "AsyncSubscriptionHandle"]]:
        while True:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                if self._stopped:
                    if self._exc is not None:
                        raise self._exc
                    return
                raise
            if item is None:
                if self._exc is not None:
                    raise self._exc
                return
            yield (item, self)

    async def stop(self) -> None:
        self._signal_stop()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        if self._callback_task is not None and not self._callback_task.done():
            self._callback_task.cancel()
            try:
                await self._callback_task
            except (asyncio.CancelledError, Exception):
                pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.stop()
        return False


async def _callback_feeder(handle: AsyncSubscriptionHandle, callback, on_error) -> None:
    """Feed readings from handle to callback (async or sync)."""
    is_async_cb = inspect.iscoroutinefunction(callback)
    is_async_err = inspect.iscoroutinefunction(on_error) if on_error else False

    try:
        async for reading, h in handle.readings():
            try:
                if is_async_cb:
                    await callback(reading, h)
                else:
                    callback(reading, h)
            except Exception as exc:
                if on_error:
                    if is_async_err:
                        await on_error(exc, h)
                    else:
                        on_error(exc, h)
                else:
                    logger.error("Unhandled error in subscription callback: %s", exc)
    except asyncio.CancelledError:
        pass
```

**Step 4: Run tests**

Run: `python -m pytest tests/aio/test_async_subscription.py -v -x 2>&1 | tail -15`
Expected: all PASSED

**Step 5: Lint and commit**

```bash
ruff check --fix -q pacsys/aio/_subscription.py tests/aio/test_async_subscription.py && ruff format -q pacsys/aio/_subscription.py tests/aio/test_async_subscription.py
git add pacsys/aio/_subscription.py tests/aio/test_async_subscription.py
git commit -m "add AsyncSubscriptionHandle with async iteration and callbacks"
```

---

### Task 5: `AsyncGRPCBackend`

**Files:**
- Create: `pacsys/aio/_grpc.py`
- Modify: `pacsys/aio/__init__.py`
- Test: `tests/aio/test_async_grpc_backend.py`

**Step 1: Write tests**

Create `tests/aio/test_async_grpc_backend.py`. Pattern: mock `_DaqCore` methods to return canned responses. Use existing `tests/test_grpc_backend.py` as reference for proto message construction. Key tests:

- `test_read_single` - delegates to `_DaqCore.read_many`, extracts value
- `test_get_many` - delegates to `_DaqCore.read_many`
- `test_read_error_raises` - DeviceError on error reading
- `test_write` - delegates to `_DaqCore.write_many`
- `test_write_no_auth_raises` - AuthenticationError without JWT
- `test_subscribe_creates_task` - creates asyncio.Task from `_DaqCore.stream`
- `test_context_manager_closes` - `async with` calls close
- `test_capabilities` - READ | STREAM | BATCH, + WRITE with auth

The tests should mock `_DaqCore` at the instance level, not the class. Create the backend, replace `_core` with a mock.

**Step 2: Implement `AsyncGRPCBackend`**

Create `pacsys/aio/_grpc.py`:

```python
"""Async gRPC backend - thin shell over _DaqCore."""

import asyncio
import logging
from typing import Optional

from pacsys.aio._backends import AsyncBackend
from pacsys.aio._subscription import AsyncSubscriptionHandle, _callback_feeder
from pacsys.drf_utils import prepare_for_write
from pacsys.errors import AuthenticationError, DeviceError
from pacsys.types import (
    Value,
    Reading,
    WriteResult,
    BackendCapability,
    ReadingCallback,
    ErrorCallback,
)

logger = logging.getLogger(__name__)

# Import guard - same pattern as sync GRPCBackend
try:
    from pacsys.backends.grpc_backend import _DaqCore, GRPC_AVAILABLE
except ImportError:
    GRPC_AVAILABLE = False
    _DaqCore = None  # type: ignore[assignment,misc]


class AsyncGRPCBackend(AsyncBackend):
    """Async gRPC backend. Wraps _DaqCore directly, no reactor thread."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        auth=None,
        timeout: float = 5.0,
    ):
        if not GRPC_AVAILABLE:
            raise ImportError("grpc package not available")
        from pacsys.auth import JWTAuth

        self._host = host or "localhost"
        self._port = port or 23456
        self._auth: Optional[JWTAuth] = auth
        self._timeout = timeout
        self._core: Optional[_DaqCore] = None
        self._connected = False
        self._closed = False
        self._handles: list[AsyncSubscriptionHandle] = []

    async def _ensure_connected(self):
        if self._closed:
            raise RuntimeError("Backend is closed")
        if not self._connected:
            self._core = _DaqCore(self._host, self._port, self._auth, self._timeout)
            await self._core.connect()
            self._connected = True

    @property
    def capabilities(self) -> BackendCapability:
        caps = BackendCapability.READ | BackendCapability.STREAM | BackendCapability.BATCH
        if self._auth is not None:
            caps |= BackendCapability.WRITE | BackendCapability.AUTH_JWT
        return caps

    @property
    def authenticated(self) -> bool:
        return self._auth is not None

    @property
    def principal(self) -> Optional[str]:
        return self._auth.principal if self._auth else None

    async def read(self, drf: str, timeout: Optional[float] = None) -> Value:
        reading = await self.get(drf, timeout=timeout)
        if not reading.ok:
            raise DeviceError(
                drf=reading.drf,
                facility_code=reading.facility_code,
                error_code=reading.error_code,
                message=reading.message or f"Read failed",
            )
        assert reading.value is not None
        return reading.value

    async def get(self, drf: str, timeout: Optional[float] = None) -> Reading:
        readings = await self.get_many([drf], timeout=timeout)
        return readings[0]

    async def get_many(self, drfs: list[str], timeout: Optional[float] = None) -> list[Reading]:
        if not drfs:
            return []
        await self._ensure_connected()
        assert self._core is not None
        effective_timeout = timeout if timeout is not None else self._timeout
        return await self._core.read_many(drfs, effective_timeout)

    async def write(self, drf: str, value: Value, timeout: Optional[float] = None) -> WriteResult:
        results = await self.write_many([(drf, value)], timeout=timeout)
        return results[0]

    async def write_many(
        self,
        settings: list[tuple[str, Value]],
        timeout: Optional[float] = None,
    ) -> list[WriteResult]:
        if not settings:
            return []
        if self._auth is None:
            raise AuthenticationError(
                "JWTAuth required for write operations. "
                "Provide auth=JWTAuth(token=...) or set PACSYS_JWT_TOKEN."
            )
        await self._ensure_connected()
        assert self._core is not None
        prepared = [(prepare_for_write(drf), value) for drf, value in settings]
        effective_timeout = timeout if timeout is not None else self._timeout
        return await self._core.write_many(prepared, effective_timeout)

    async def subscribe(
        self,
        drfs: list[str],
        callback: Optional[ReadingCallback] = None,
        on_error: Optional[ErrorCallback] = None,
    ) -> AsyncSubscriptionHandle:
        await self._ensure_connected()
        assert self._core is not None
        handle = AsyncSubscriptionHandle()
        handle._task = asyncio.ensure_future(
            self._core.stream(drfs, handle._dispatch, handle._is_stopped, handle._signal_error)
        )
        if callback:
            handle._callback_task = asyncio.ensure_future(
                _callback_feeder(handle, callback, on_error)
            )
        self._handles.append(handle)
        return handle

    async def remove(self, handle) -> None:
        if isinstance(handle, AsyncSubscriptionHandle):
            await handle.stop()
            if handle in self._handles:
                self._handles.remove(handle)

    async def stop_streaming(self) -> None:
        for h in list(self._handles):
            await h.stop()
        self._handles.clear()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.stop_streaming()
        if self._core is not None:
            await self._core.close()
            self._core = None
        self._connected = False
```

**Step 3: Update `pacsys/aio/__init__.py`**

Add factory function and exports:

```python
"""pacsys.aio - async API for pacsys backends."""

from pacsys.aio._backends import AsyncBackend
from pacsys.aio._subscription import AsyncSubscriptionHandle

__all__ = ["AsyncBackend", "AsyncSubscriptionHandle"]


def grpc(host=None, port=None, auth=None, timeout=5.0):
    """Create an async gRPC backend."""
    from pacsys.aio._grpc import AsyncGRPCBackend
    return AsyncGRPCBackend(host=host, port=port, auth=auth, timeout=timeout)
```

**Step 4: Run tests**

Run: `python -m pytest tests/aio/test_async_grpc_backend.py -v -x 2>&1 | tail -15`
Expected: all PASSED

**Step 5: Run full test suite**

Run: `python -m pytest tests/ -v -x 2>&1 | tail -15`
Expected: all PASSED (no regressions)

**Step 6: Lint and commit**

```bash
ruff check --fix -q pacsys/aio/ tests/aio/ && ruff format -q pacsys/aio/ tests/aio/
git add pacsys/aio/_grpc.py pacsys/aio/__init__.py tests/aio/test_async_grpc_backend.py
git commit -m "add AsyncGRPCBackend wrapping _DaqCore"
```

---

### Task 6: `_AsyncDpmCore`

This is the largest task. It extracts the read protocol from sync `get_many()` (lines 700-838 of `dpm_http.py`), adapts the write protocol from `_execute_write()` (lines 1168-1293) and `_authenticate_connection()` (lines 844-921), and reuses `_DpmStreamCore.stream()` logic.

**Files:**
- Create: `pacsys/backends/_dpm_core.py`
- Test: `tests/aio/test_async_dpm_core.py`

**Step 1: Write tests**

Create `tests/aio/test_async_dpm_core.py`. Mock `_AsyncDPMConnection` to verify:

- `test_connect` - calls `_AsyncDPMConnection.connect()`
- `test_read_many_single` - sends AddToList+StartList, receives data reply, sends StopList+ClearList
- `test_read_many_with_error` - handles AddToList with non-zero status
- `test_read_many_timeout` - ReadError on no reply within deadline
- `test_write_many_auto_authenticates` - calls authenticate+enable_settings if not done
- `test_write_many_sends_apply_settings` - sends correct ApplySettings
- `test_stream_dispatches_readings` - continuous recv loop dispatches via callback
- `test_authenticate` - sends Authenticate_request, processes reply (mock gssapi)
- `test_enable_settings` - sends EnableSettings_request, checks Status_reply

Use the existing `tests/test_dpm_stream_core.py` and `tests/test_dpm_http_backend.py` as patterns for DPM protocol mocking.

**Step 2: Implement `_AsyncDpmCore`**

Create `pacsys/backends/_dpm_core.py`. Reference:
- Read protocol: `dpm_http.py:700-838` (sync `get_many`)
- Write protocol: `dpm_http.py:1168-1293` (`_execute_write`)
- Auth: `dpm_http.py:844-945` (`_authenticate_connection` + `_enable_settings`)
- Stream: `dpm_http.py:424-521` (`_DpmStreamCore.stream`)
- Value conversion: `dpm_http.py:1044-1078` (`_value_to_setting`)

Reuse pure functions from `dpm_http.py`:
- `_reply_to_reading()`, `_device_info_to_meta()`, `ensure_immediate_event()`
- `prepare_for_write()` from `drf_utils.py`
- Protocol message classes from `dpm_protocol.py`
- `parse_error()`, `status_message()` from `errors.py`

Key implementation detail: use `asyncio.wait_for` with `self._conn.recv_message()` for deadline enforcement, rather than the sync pattern of computing remaining time per recv call.

**Step 3: Run tests**

Run: `python -m pytest tests/aio/test_async_dpm_core.py -v -x 2>&1 | tail -15`
Expected: all PASSED

**Step 4: Lint and commit**

```bash
ruff check --fix -q pacsys/backends/_dpm_core.py tests/aio/test_async_dpm_core.py && ruff format -q pacsys/backends/_dpm_core.py tests/aio/test_async_dpm_core.py
git add pacsys/backends/_dpm_core.py tests/aio/test_async_dpm_core.py
git commit -m "add _AsyncDpmCore for unified async DPM reads/writes/streaming"
```

---

### Task 7: `AsyncDPMHTTPBackend`

**Files:**
- Create: `pacsys/aio/_dpm_http.py`
- Modify: `pacsys/aio/__init__.py`
- Test: `tests/aio/test_async_dpm_backend.py`

**Step 1: Write tests**

Create `tests/aio/test_async_dpm_backend.py`. Mock `_AsyncDpmCore` at the class level (patch its constructor). Key tests:

- `test_read_borrows_from_pool` - acquires core, calls read_many, releases
- `test_read_error_discards_core` - on exception, core is closed not returned
- `test_write_creates_authenticated_core` - calls connect+authenticate+enable_settings
- `test_subscribe_creates_dedicated_core` - one core per subscription, not pooled
- `test_close_drains_pools` - closes all pooled cores
- `test_context_manager` - async with pattern

**Step 2: Implement `AsyncDPMHTTPBackend`**

Create `pacsys/aio/_dpm_http.py`. Follow the design doc pattern with `asyncio.Queue` pools. Reference `dpm_http.py:1140-1167` for `write()` alarm dict expansion (reuse `_expand_alarm_dict` by importing or duplicating the logic - prefer importing from `DPMHTTPBackend` if feasible, else duplicate the small helper).

**Step 3: Update `pacsys/aio/__init__.py`**

Add `dpm()` factory function.

**Step 4: Run tests**

Run: `python -m pytest tests/aio/test_async_dpm_backend.py -v -x 2>&1 | tail -15`
Expected: all PASSED

**Step 5: Lint and commit**

```bash
ruff check --fix -q pacsys/aio/_dpm_http.py tests/aio/test_async_dpm_backend.py && ruff format -q pacsys/aio/_dpm_http.py tests/aio/test_async_dpm_backend.py
git add pacsys/aio/_dpm_http.py pacsys/aio/__init__.py tests/aio/test_async_dpm_backend.py
git commit -m "add AsyncDPMHTTPBackend with async connection pooling"
```

---

### Task 8: `AsyncDevice`

**Files:**
- Create: `pacsys/aio/_device.py`
- Modify: `pacsys/aio/__init__.py`
- Test: `tests/aio/test_async_device.py`

**Step 1: Write tests**

Create `tests/aio/test_async_device.py`. Mirror structure of `tests/test_device.py`:

- DRF validation (delegates to `_DeviceBase`, already tested, just smoke test)
- `test_read` - awaits backend.read
- `test_setting` - awaits backend.read with SETTING property
- `test_status_bool` - status with field="on" returns bool
- `test_write` - awaits backend.write
- `test_write_with_verify` - verify loop uses asyncio.sleep
- `test_control_on` - delegates to control()
- `test_with_event` - returns new AsyncDevice
- `test_with_range` - returns new AsyncDevice
- `test_with_backend` - returns new AsyncDevice bound to different backend

Use `unittest.mock.AsyncMock` for the backend mock.

**Step 2: Implement `AsyncDevice`**

Create `pacsys/aio/_device.py`. Inherits `_DeviceBase`. All I/O methods are async versions of `Device` methods. Uses `asyncio.sleep` in `_verify_readback`. Uses `CONTROL_STATUS_MAP` from `_device_base`.

Key: `_from_drf` creates new `AsyncDevice(drf, self._backend)`. `with_backend` takes `AsyncBackend`.

**Step 3: Update `pacsys/aio/__init__.py`**

Add `AsyncDevice` to exports.

**Step 4: Run tests**

Run: `python -m pytest tests/aio/test_async_device.py -v -x 2>&1 | tail -15`
Expected: all PASSED

**Step 5: Lint and commit**

```bash
ruff check --fix -q pacsys/aio/_device.py tests/aio/test_async_device.py && ruff format -q pacsys/aio/_device.py tests/aio/test_async_device.py
git add pacsys/aio/_device.py pacsys/aio/__init__.py tests/aio/test_async_device.py
git commit -m "add AsyncDevice with async read/write/verify"
```

---

### Task 9: Module-level convenience API

**Files:**
- Modify: `pacsys/aio/__init__.py`
- Test: `tests/aio/test_async_simple_api.py`

**Step 1: Write tests**

Create `tests/aio/test_async_simple_api.py`. Mirror `tests/test_simple_api.py`:

- `test_configure_and_read` - configure then read
- `test_configure_invalid_backend` - ValueError
- `test_read_delegates` - calls global backend.read
- `test_shutdown_resets` - shutdown allows reconfigure

Use `unittest.mock.patch` to mock backend creation.

**Step 2: Implement module-level API**

Expand `pacsys/aio/__init__.py` with:
- `configure()` - same pattern as sync, stores config
- `_get_global_async_backend()` - lazy init with lock (use `asyncio.Lock` since callers are async)
- `read()`, `get()`, `get_many()`, `write()`, `write_many()`, `subscribe()` - delegate to global backend
- `shutdown()` - close and reset global backend

**Step 3: Run tests**

Run: `python -m pytest tests/aio/test_async_simple_api.py -v -x 2>&1 | tail -15`
Expected: all PASSED

**Step 4: Lint and commit**

```bash
ruff check --fix -q pacsys/aio/__init__.py tests/aio/test_async_simple_api.py && ruff format -q pacsys/aio/__init__.py tests/aio/test_async_simple_api.py
git add pacsys/aio/__init__.py tests/aio/test_async_simple_api.py
git commit -m "add pacsys.aio module-level convenience API"
```

---

### Task 10: Full test suite + lint + docs

**Files:**
- Modify: `SPECIFICATION.md` (add async API section)
- Modify: `README.md` (add async usage example)

**Step 1: Run full unit test suite**

Run: `python -m pytest tests/ -v -x 2>&1 | tail -30`
Expected: all PASSED

**Step 2: Run type checker**

Run: `ty check pacsys/aio/ 2>&1 | tail -20`
Fix any type errors.

**Step 3: Run linter on entire codebase**

Run: `ruff check --fix -q pacsys/ tests/ && ruff check pacsys/ tests/ && ruff format -q pacsys/ tests/`
Expected: clean

**Step 4: Update SPECIFICATION.md**

Add section documenting `pacsys.aio` API surface, `AsyncBackend` ABC, `AsyncDevice`, factory functions.

**Step 5: Update README.md**

Add async usage example in the appropriate section.

**Step 6: Commit**

```bash
git add SPECIFICATION.md README.md
git commit -m "document async API in specification and readme"
```

---

## Implementation Notes for the Engineer

### Key files to read before starting:
- `docs/plans/2026-02-13-async-api-design.md` - full design rationale
- `pacsys/backends/grpc_backend.py:334-641` - `_DaqCore` (reuse as-is for gRPC)
- `pacsys/backends/dpm_http.py:221-350` - `_AsyncDPMConnection` (reuse for DPM core)
- `pacsys/backends/dpm_http.py:700-838` - sync `get_many()` (port to async in `_AsyncDpmCore`)
- `pacsys/backends/dpm_http.py:1168-1293` - sync `_execute_write()` (port to async)
- `pacsys/backends/dpm_http.py:844-945` - Kerberos auth (port to async)
- `pacsys/backends/dpm_http.py:424-521` - `_DpmStreamCore.stream()` (adapt for core)
- `pacsys/device.py` - sync Device (extract base, mirror for async)

### Testing pattern:
- Use `@pytest.mark.asyncio` for all async tests
- Mock at core boundaries: `_DaqCore` for gRPC, `_AsyncDpmCore` for DPM
- `_AsyncDpmCore` tests mock `_AsyncDPMConnection` to verify protocol message sequences
- Use `unittest.mock.AsyncMock` for async method mocks

### Common pitfalls:
- `asyncio.Queue.put_nowait()` raises `QueueFull`, not silently drops - handle explicitly
- `asyncio.wait_for` wraps `TimeoutError`, not `asyncio.TimeoutError` on Python 3.11+
- `_DaqCore.stream()` takes sync `dispatch_fn` - pass `handle._dispatch` which calls `put_nowait`
- GSSAPI calls are blocking but acceptable on event loop per design decision
- Don't forget `prepare_for_write()` for write DRFs and `ensure_immediate_event()` for read DRFs
