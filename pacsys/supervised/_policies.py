"""Pluggable policy system for supervised proxy server."""

import fnmatch
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from pacsys.drf_utils import get_device_name


@dataclass(frozen=True)
class RequestContext:
    """Context for a single RPC request, passed to policy checks."""

    drfs: list[str]
    rpc_method: str  # "Read", "Set", or "Alarms"
    peer: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyDecision:
    """Result of a policy check."""

    allowed: bool
    reason: Optional[str] = None  # required when denied

    def __post_init__(self):
        if not self.allowed and not self.reason:
            raise ValueError("PolicyDecision must include a reason when denied")


_ALLOW = PolicyDecision(allowed=True)


class Policy(ABC):
    """Abstract base for policy checks. Implement check() to allow or deny requests."""

    @abstractmethod
    def check(self, ctx: RequestContext) -> PolicyDecision: ...


class ReadOnlyPolicy(Policy):
    """Denies Set RPCs, allows everything else."""

    def check(self, ctx: RequestContext) -> PolicyDecision:
        if ctx.rpc_method == "Set":
            return PolicyDecision(allowed=False, reason="Write operations disabled")
        return _ALLOW


class DeviceAccessPolicy(Policy):
    """Allow or deny access based on device name glob patterns.

    Args:
        patterns: List of fnmatch patterns (e.g. ["M:*", "G:AMANDA"])
        mode: "allow" = only matching devices allowed, "deny" = matching devices blocked
    """

    def __init__(self, patterns: list[str], mode: str = "allow"):
        if not patterns:
            raise ValueError("patterns must not be empty")
        if mode not in ("allow", "deny"):
            raise ValueError(f"mode must be 'allow' or 'deny', got {mode!r}")
        self._patterns = patterns
        self._mode = mode

    def _matches(self, device_name: str) -> bool:
        return any(fnmatch.fnmatchcase(device_name.upper(), p.upper()) for p in self._patterns)

    def check(self, ctx: RequestContext) -> PolicyDecision:
        for drf in ctx.drfs:
            name = get_device_name(drf)
            matched = self._matches(name)
            if self._mode == "allow" and not matched:
                return PolicyDecision(allowed=False, reason=f"Device {name} not in allow list")
            if self._mode == "deny" and matched:
                return PolicyDecision(allowed=False, reason=f"Device {name} is denied")
        return _ALLOW


class RateLimitPolicy(Policy):
    """Sliding window rate limit per peer.

    Args:
        max_requests: Maximum requests per window
        window_seconds: Window size in seconds (default: 60)
    """

    def __init__(self, max_requests: int, window_seconds: float = 60.0):
        if max_requests <= 0:
            raise ValueError(f"max_requests must be positive, got {max_requests}")
        if window_seconds <= 0:
            raise ValueError(f"window_seconds must be positive, got {window_seconds}")
        self._max_requests = max_requests
        self._window = window_seconds
        self._lock = threading.Lock()
        self._timestamps: dict[str, list[float]] = {}

    def check(self, ctx: RequestContext) -> PolicyDecision:
        now = time.monotonic()
        cutoff = now - self._window

        with self._lock:
            times = self._timestamps.get(ctx.peer, [])
            # Prune expired entries
            times = [t for t in times if t > cutoff]

            if len(times) >= self._max_requests:
                self._timestamps[ctx.peer] = times
                return PolicyDecision(
                    allowed=False,
                    reason=f"Rate limit exceeded ({self._max_requests} per {self._window}s)",
                )

            times.append(now)
            self._timestamps[ctx.peer] = times

        return _ALLOW


def evaluate_policies(policies: list[Policy], ctx: RequestContext) -> PolicyDecision:
    """Evaluate a chain of policies. First denial short-circuits."""
    for policy in policies:
        decision = policy.check(ctx)
        if not decision.allowed:
            return decision
    return _ALLOW
