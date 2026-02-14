# Async API Design: `pacsys.aio`

Native async API for pacsys backends, enabling single-event-loop operation
for high-performance async applications (FastAPI, aiohttp, etc.).

## Motivation

pacsys backends already run async internally (gRPC via `_DaqCore`, DPM/HTTP
via `_AsyncDPMConnection` + `_DpmStreamCore`), but wrap everything in a sync
public API with dedicated reactor threads and `run_coroutine_threadsafe`
bridges. This design exposes native async so callers running their own event
loop can `await` backend operations directly, eliminating unnecessary threads
and cross-thread synchronization.

## Decisions

| Decision | Choice |
|----------|--------|
| Module layout | `pacsys.aio` sub-namespace (like `grpc.aio`, `redis.asyncio`) |
| Async/sync relationship | Async-first for new code, sync path unchanged |
| gRPC approach | Thin shell over existing `_DaqCore` |
| DPM/HTTP approach | New `_AsyncDpmCore` (unified read/write/stream) |
| Sync DPM/HTTP | Unchanged, keeps `DPMConnection` + `ConnectionPool` |
| Streaming interface | Both async iterator and async callbacks |
| Subscription internals | `asyncio.Queue` + sentinel stop |
| Device code sharing | `_DeviceBase` mixin extracted from `Device` |
| Kerberos GSSAPI | Blocking on event loop (acceptable latency) |
| Connection pooling | `asyncio.Queue` of `_AsyncDpmCore` instances |
| Scope | gRPC + DPM/HTTP only (no DMQ/ACL in this phase) |

## Architecture

### File layout

```
pacsys/
  aio/
    __init__.py          # module-level async API + factory functions
    _backends.py         # AsyncBackend ABC
    _grpc.py             # AsyncGRPCBackend
    _dpm_http.py         # AsyncDPMHTTPBackend
    _subscription.py     # AsyncSubscriptionHandle
    _device.py           # AsyncDevice
  device.py              # Device refactored to inherit _DeviceBase
  _device_base.py        # _DeviceBase mixin (DRF building, field resolution)
  backends/
    _dpm_core.py         # NEW: _AsyncDpmCore
    dpm_http.py          # sync backend (unchanged)
    grpc_backend.py      # sync backend (unchanged)
```

### Component relationships

```
AsyncGRPCBackend ──uses──> _DaqCore (existing, unchanged)
AsyncDPMHTTPBackend ──uses──> _AsyncDpmCore (new)
_AsyncDpmCore ──uses──> _AsyncDPMConnection (existing, unchanged)

AsyncDevice ──inherits──> _DeviceBase <──inherits── Device
AsyncDevice ──delegates──> AsyncBackend
Device ──delegates──> Backend (unchanged)
```

The sync backends, `DPMConnection`, `ConnectionPool`, and reactor thread
machinery are untouched.

## AsyncBackend ABC

```python
class AsyncBackend(ABC):
    @property
    @abstractmethod
    def capabilities(self) -> BackendCapability: ...

    @abstractmethod
    async def read(self, drf: str, timeout: float | None = None) -> Value: ...
    @abstractmethod
    async def get(self, drf: str, timeout: float | None = None) -> Reading: ...
    @abstractmethod
    async def get_many(self, drfs: list[str], timeout: float | None = None) -> list[Reading]: ...

    async def write(self, drf, value, timeout=None) -> WriteResult:
        raise NotImplementedError
    async def write_many(self, settings, timeout=None) -> list[WriteResult]:
        raise NotImplementedError
    async def subscribe(self, drfs, callback=None, on_error=None) -> AsyncSubscriptionHandle:
        raise NotImplementedError
    async def remove(self, handle) -> None:
        raise NotImplementedError
    async def stop_streaming(self) -> None:
        raise NotImplementedError

    async def close(self) -> None: ...
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): await self.close()

    @property
    def authenticated(self) -> bool: return False
    @property
    def principal(self) -> str | None: return None
```

Same shape as sync `Backend`. Write and streaming methods default to
`NotImplementedError`. Auth properties are sync (no I/O).

## AsyncSubscriptionHandle

Replaces `threading.Condition` + `deque` with `asyncio.Queue`:

```python
class AsyncSubscriptionHandle:
    _queue: asyncio.Queue[Reading | None]   # None = stop sentinel
    _stopped: bool
    _exc: Exception | None
    _maxsize = 10_000

    def _dispatch(self, reading):
        """Called by core's sync dispatch_fn. Non-blocking put."""
        try:
            self._queue.put_nowait(reading)
        except asyncio.QueueFull:
            pass  # drop on overflow, matches existing behavior

    def _signal_stop(self):
        self._stopped = True
        self._queue.put_nowait(None)

    def _signal_error(self, exc):
        self._exc = exc
        self._signal_stop()

    async def readings(self, timeout=None) -> AsyncIterator[tuple[Reading, Self]]:
        while True:
            item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            if item is None:
                if self._exc:
                    raise self._exc
                return
            yield (item, self)

    async def remove(self) -> None: ...
```

Cores' `dispatch_fn` contract stays sync (`queue.put_nowait()`), so existing
core code works without modification.

### Async callbacks

When `subscribe(drfs, callback=my_async_fn)` is called, the backend spawns a
feeder task:

```python
async def _callback_feeder(handle, callback, on_error):
    async for reading, h in handle.readings():
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(reading, h)
            else:
                callback(reading, h)
        except Exception as exc:
            if on_error:
                await on_error(exc, h) if asyncio.iscoroutinefunction(on_error) else on_error(exc, h)
```

Both sync and async callbacks supported, detected via
`iscoroutinefunction()`.

## `_AsyncDpmCore`

Unified async core for all DPM/HTTP operations. One connection per core
instance. Replaces the split between sync `DPMConnection` (reads/writes)
and `_AsyncDPMConnection` + `_DpmStreamCore` (streaming).

```python
class _AsyncDpmCore:
    _conn: _AsyncDPMConnection
    _host: str
    _port: int
    _timeout: float
    _auth: KerberosAuth | None
    _settings_enabled: bool

    async def connect(self) -> None
    async def close(self) -> None

    # Auth (blocking GSSAPI on event loop)
    async def authenticate(self) -> None
    async def enable_settings(self) -> None

    # Operations
    async def read_many(self, drfs, timeout) -> list[Reading]
    async def write_many(self, settings, role=None, timeout=None) -> list[WriteResult]
    async def stream(self, drfs, dispatch_fn, stop_check, error_fn) -> None
```

### Protocol details

All three operations use the same underlying DPM protocol:

| | Setup | Data phase | Cleanup |
|---|---|---|---|
| **read** | AddToList + StartList | recv data replies | StopList + ClearList |
| **write** | StopList + ClearList + AddToList (+ ROLE) + StartList | recv DeviceInfo, send ApplySettings, recv reply | StopList |
| **stream** | AddToList + StartList | continuous recv loop | (connection closed) |

Handshake, wire format (length-prefixed PC binary), and reply parsing
(`unmarshal_reply()`) are shared. Pure helper functions
(`_reply_to_reading`, `_reply_to_value_and_type`, `prepare_for_write()`)
are reused from the existing codebase.

### Authentication

Two-phase Kerberos GSSAPI handshake:

1. Send `Authenticate_request(token=b"")` -> receive service name
2. Create `gssapi.SecurityContext`, exchange tokens
3. Generate MIC, store for `enable_settings()`

Then `enable_settings()` sends `EnableSettings_request` with MIC to
authorize writes. Both run blocking GSSAPI calls directly on the event loop
(acceptable: fast except first invocation which hits KDC).

`write_many()` auto-authenticates if `_settings_enabled` is False.

## AsyncGRPCBackend

Thin shell over `_DaqCore`. No reactor thread, no sync bridge.

```python
class AsyncGRPCBackend(AsyncBackend):
    _core: _DaqCore

    async def get_many(self, drfs, timeout=None):
        await self._ensure_connected()
        return await self._core.read_many(drfs, effective_timeout)

    async def write_many(self, settings, timeout=None):
        await self._ensure_connected()
        return await self._core.write_many(settings, effective_timeout)

    async def subscribe(self, drfs, callback=None, on_error=None):
        await self._ensure_connected()
        handle = AsyncSubscriptionHandle(drfs)
        handle._task = asyncio.ensure_future(
            self._core.stream(drfs, handle._dispatch, handle._is_stopped, handle._signal_error)
        )
        if callback:
            handle._callback_task = asyncio.ensure_future(
                _callback_feeder(handle, callback, on_error)
            )
        return handle
```

## AsyncDPMHTTPBackend

Manages pools of `_AsyncDpmCore` instances via `asyncio.Queue`:

- **Read pool** (`maxsize=4`): unauthenticated cores, borrow/release pattern
- **Write pool** (`maxsize=4`): authenticated cores (auth cached per connection)
- **Streaming**: one core per subscription, no pooling

```python
class AsyncDPMHTTPBackend(AsyncBackend):
    _read_pool: asyncio.Queue[_AsyncDpmCore]
    _write_pool: asyncio.Queue[_AsyncDpmCore]

    async def get_many(self, drfs, timeout=None):
        core = await self._acquire_read_core()
        try:
            result = await core.read_many(drfs, effective_timeout)
            await self._release_read_core(core)
            return result
        except Exception:
            await core.close()
            raise

    async def write_many(self, settings, timeout=None):
        core = await self._acquire_write_core()  # creates + authenticates if needed
        try:
            result = await core.write_many(settings, timeout=effective_timeout)
            await self._release_write_core(core)
            return result
        except Exception:
            await core.close()
            raise
```

## `_DeviceBase` and `AsyncDevice`

`_DeviceBase` extracts the pure (non-I/O) logic from `Device`:

```python
class _DeviceBase:
    """DRF building, field resolution, fluent modification. No I/O."""
    __slots__ = ("_request",)

    # Properties: name, drf, request, has_event, is_periodic
    # Helpers: _build_drf(), _resolve_field()
    # Constants: _BOOL_STATUS_FIELDS, _CONTROL_STATUS_MAP
    # Fluent: with_event(), with_range()
    # Equality: __repr__, __eq__, __hash__
```

`Device` and `AsyncDevice` both inherit `_DeviceBase` and add their
respective backend slot and I/O methods:

```python
class Device(_DeviceBase):
    __slots__ = ("_backend",)           # Backend (sync)
    def read(self, ...) -> Value: ...   # sync

class AsyncDevice(_DeviceBase):
    __slots__ = ("_backend",)           # AsyncBackend
    async def read(self, ...) -> Value: ...  # async
```

`AsyncDevice._verify_readback()` uses `asyncio.sleep()` instead of
`time.sleep()`.

Fluent methods (`with_event`, `with_range`) return the correct type via
`self.__class__(...)`. `with_backend()` moves to each subclass since the
backend type differs.

## Module-level API

`pacsys/aio/__init__.py` mirrors `pacsys/__init__.py`:

```python
# Configuration
def configure(backend="dpm", **kwargs) -> None: ...

# Reads/writes (lazy global backend)
async def read(drf, timeout=None) -> Value: ...
async def get(drf, timeout=None) -> Reading: ...
async def get_many(drfs, timeout=None) -> list[Reading]: ...
async def write(drf, value, timeout=None) -> WriteResult: ...
async def subscribe(drfs, callback=None, on_error=None) -> AsyncSubscriptionHandle: ...
async def shutdown() -> None: ...

# Factory functions (sync constructors, return async backends)
def grpc(host=None, auth=None, ...) -> AsyncGRPCBackend: ...
def dpm(host=None, auth=None, ...) -> AsyncDPMHTTPBackend: ...
```

## Usage Examples

```python
import pacsys.aio

# Simple reads
value = await pacsys.aio.read("M:OUTTMP")
reading = await pacsys.aio.get("M:OUTTMP")

# Explicit backend
async with pacsys.aio.grpc(host="myhost:50051", auth=jwt) as backend:
    value = await backend.read("M:OUTTMP")
    result = await backend.write("M:OUTTMP", 72.5)

# Device API
from pacsys.aio import AsyncDevice
d = AsyncDevice("M:OUTTMP")
val = await d.read()
await d.write(72.5, verify=True)
await d.on()

# Streaming with async iteration
sub = await backend.subscribe(["M:OUTTMP@p,1000"])
async for reading, handle in sub.readings():
    print(reading.value)

# Streaming with async callback
async def on_reading(reading, handle):
    await db.insert(reading.value)
sub = await backend.subscribe(["M:OUTTMP@p,1000"], callback=on_reading)

# FastAPI integration
@app.get("/device/{name}")
async def read_device(name: str):
    reading = await pacsys.aio.get(name)
    return {"value": reading.value, "timestamp": reading.timestamp}
```

## Testing

### Unit tests (`tests/aio/`)

- `test_async_backend.py` - ABC contract tests
- `test_async_grpc_backend.py` - mocked `_DaqCore`
- `test_async_dpm_backend.py` - mocked `_AsyncDpmCore`
- `test_async_dpm_core.py` - mocked `_AsyncDPMConnection`, verifies protocol sequences
- `test_async_subscription.py` - queue, iteration, callbacks, overflow, stop, errors
- `test_async_device.py` - mirrors `test_device.py`
- `test_device_base.py` - extracted DRF logic

### Integration tests (`tests/real/`)

- `test_async_backend_shared.py` - same suite as sync `test_backend_shared.py`
  but async; parametrized over async backends; auto-skip on server unavailable
- Correctness: async results must match sync results for same DRFs

## Implementation Order

```
Phase 1: Foundation
  - Extract _DeviceBase from Device
  - Create pacsys/aio/ package skeleton
  - AsyncSubscriptionHandle

Phase 2: gRPC async backend
  - AsyncGRPCBackend wrapping _DaqCore
  - Unit tests
  - Integration tests

Phase 3: DPM/HTTP async backend
  - _AsyncDpmCore (read_many, write_many, authenticate, enable_settings, stream)
  - AsyncDPMHTTPBackend with async pool
  - Unit tests
  - Integration tests

Phase 4: AsyncDevice + module-level API
  - AsyncDevice inheriting _DeviceBase
  - pacsys/aio/__init__.py convenience functions
  - Unit tests
  - Integration tests
```

Phases are sequential. Phase 2 proves the API shape with minimal effort.
Phase 3 is the bulk of new code (~300 lines for `_AsyncDpmCore`).
Phase 4 is mechanical.

## Out of Scope

- DMQ / ACL async backends
- Async DevDB client
- Async SSH
- Async `CombinedStream`
- Changes to existing sync API
