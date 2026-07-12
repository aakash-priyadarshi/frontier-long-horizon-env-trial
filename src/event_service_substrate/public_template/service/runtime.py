"""Deterministic stage runner used by the runtime engine."""

from __future__ import annotations

from . import flow


def accept(command: dict[str, str], store: object) -> str:
    """Accept a command through s1-s2-s3."""
    prepared = flow.s1(command, store)
    event_id = flow.s2(prepared, store)
    flow.s3(prepared, event_id, store)
    return event_id


def deliver(event_id: str, sequence: int, store: object) -> str:
    """Deliver a journal event through s4-s5-s6."""
    event = flow.s4(event_id, store)
    effect_id = flow.s5(event, store)
    flow.s6(sequence, store)
    return effect_id
