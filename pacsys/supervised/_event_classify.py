"""Classify DRF events as one-shot or streaming for request routing."""

from pacsys.drf3 import parse_request
from pacsys.drf3.event import (
    DefaultEvent,
    ImmediateEvent,
    NeverEvent,
    PeriodicEvent,
)


def is_oneshot_event(drf: str) -> bool:
    """True for @I, @U, @N, @Q (non-continuous periodic), or no event.

    False for @P (continuous periodic), @E (clock), @S (state).
    """
    req = parse_request(drf)
    event = req.event
    if event is None:
        return True
    if isinstance(event, (DefaultEvent, ImmediateEvent, NeverEvent)):
        return True
    if isinstance(event, PeriodicEvent):
        # Use mode char not .cont (parser has case-sensitivity issue with lowercase p)
        return event.mode == "Q"
    return False


def all_oneshot(drfs: list[str]) -> bool:
    """True if ALL drfs are one-shot. Mixed list -> streaming path."""
    return all(is_oneshot_event(drf) for drf in drfs)
