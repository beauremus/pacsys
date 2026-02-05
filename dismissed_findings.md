# Dismissed Code Review Findings

Findings reviewed and dismissed during the 2026-02-04 Gemini-assisted code audit.
Documented here to avoid re-investigating in future reviews.

---

## CombinedStream thread-per-subscription

**Area:** `pacsys/types.py` — `CombinedStream.readings()`
**Claim:** Spawns a native thread for every subscription; resource-heavy for many devices.
**Dismissal:** This is architecturally necessary. The public API is synchronous, and each
`SubscriptionHandle.readings()` is a blocking generator. There is no way to multiplex
blocking iterators without threads (or async, which would break the sync API contract).
The thread count equals the subscription count, which is bounded by the user's explicit
`subscribe()` calls. Not actionable without a full API redesign.

---

## DMQ callback on IO thread

**Area:** `pacsys/backends/dmq.py` — `_on_message`
**Claim:** User callback runs directly on the Pika IO thread; blocking callbacks stall heartbeats.
**Dismissal:** This is Pika's documented design. Pika's `SelectConnection` dispatches all
callbacks on the IO loop thread. The DMQ backend already documents this constraint
(line 1842: "blocking callbacks will stall IO loop"). Moving callbacks to a thread pool
would add complexity and latency for the common case (fast callbacks). Users who need
heavy processing should use iterator mode (`readings()`) instead of callbacks.

---

## DMQ session eviction with pending writes

**Area:** `pacsys/backends/dmq.py` — `_evict_lru_write_session`
**Claim:** May forcefully close sessions with pending writes under high concurrency.
**Dismissal:** The LRU eviction sorts by `last_used` timestamp. Sessions with pending writes
have recent timestamps (updated on each write) and are unlikely to be the LRU victim.
The `MAX_WRITE_SESSIONS` limit (256) is well above typical usage. This is a theoretical
concern under extreme concurrency, not a practical bug.

---

## ssh.py select.select not cross-platform

**Area:** `pacsys/ssh.py` — `_bidirectional_forward`
**Claim:** `select.select` on `paramiko.Channel` fails on Windows.
**Dismissal:** Paramiko's `Channel.fileno()` is cross-platform by design. On POSIX it uses
`os.pipe()`, on Windows it uses `paramiko.pipe.WindowsPipe` — a loopback socket pair
(`socket.AF_INET`). Since Windows `select.select` requires sockets, and `WindowsPipe`
returns a socket fd, `select.select([sock, chan], [], [], timeout)` works on all platforms.
See `paramiko/pipe.py` source and [paramiko pipe docs](https://docs.paramiko.org/en/stable/api/pipe.html).
OS-specific specialization (epoll/kqueue/threading) adds no benefit for 2 fds.

---

## testing.py _write_range TypeError on single integer

**Area:** `pacsys/testing.py` — `_write_range`
**Claim:** Passing a single integer to `out[start:end] = value` would raise TypeError.
**Dismissal:** `Device.write()` always passes values through `_value_to_setting()` in the
backend, which converts scalars to bytes/arrays before reaching `_write_range`. The
`FakeBackend` follows the same code path. Bare integers never reach the slice assignment.

---

## auth.py manual JWT decoding

**Area:** `pacsys/auth.py` — `JWTAuth._decode_payload`
**Claim:** Manual JWT decoding replicates logic available in libraries like PyJWT.
**Dismissal:** The JWT decoding here is client-side "who am I" extraction only — no
signature verification is performed (the server validates tokens). Adding PyJWT as a
dependency for this one use case would be overkill. The manual decoder handles the
base64url padding correctly and is well-tested.

---

## parse_request "silent data loss" for three-segment DRFs

**Area:** `pacsys/drf3/drf3.py` — `parse_request`
**Claim:** `Dev.Field.Ignored` silently drops the third segment.
**Dismissal:** DRF format is `DEVICE.PROPERTY.FIELD@EVENT`. The regex captures at most
two dot-separated groups after the device name (property and field). A third segment
doesn't match valid DRF syntax. The behavior is correct per the DRF specification.

---

## grpc_backend.py redundant GRPC_AVAILABLE checks

**Area:** `pacsys/backends/grpc_backend.py` — `_grpc_error_code`, `_grpc_facility_code`
**Claim:** These functions check `GRPC_AVAILABLE` but can only be called when gRPC is loaded.
**Dismissal:** The checks are redundant but harmless — they add no measurable overhead and
provide an extra safety net. Not worth changing.

---

## backends/__init__.py datetime import

**Area:** `pacsys/backends/__init__.py`
**Claim:** `datetime` is imported but only used in `timestamp_from_millis`.
**Dismissal:** The import is used (in `timestamp_from_millis`). "Only used once" is not
an issue — the function is a shared utility called by multiple backends.

---

## DeviceError.__init__ trivial duplication

**Area:** `pacsys/errors.py` — `DeviceError.__init__`
**Claim:** Duplicates `super().__init__` for message formatting branches.
**Dismissal:** The two branches produce different message strings. The `super().__init__`
call is one line in each branch. Extracting this would add complexity for no benefit.

---

## resolve_verify creates Verify() on every call

**Area:** `pacsys/verify.py` — `resolve_verify`
**Claim:** `Verify()` instantiated each time `verify=True` is passed.
**Dismissal:** `Verify` is a frozen dataclass. Construction is trivially cheap. A module-level
constant would save a microsecond per call but adds coupling and no measurable benefit.
