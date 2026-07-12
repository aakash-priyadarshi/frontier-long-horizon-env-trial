"""Public stage composition for intake and settlement delivery.

This module is the intentional default behavior and is the intended repair
surface. The runtime engine calls these six functions through the public
``service.runtime`` module. Each stage receives the canonical ``store`` object
and must use only the bounded store methods.

The default implementation below matches the documented baseline. It is not
idempotent across retries and does not reject duplicate occurrences. A valid
repair typically modifies ``s2`` (command/occurrence identity) and/or ``s5``
(effect identity) while keeping the same function signatures.
"""

from __future__ import annotations


def s1(command: dict[str, str], store: object) -> dict[str, str]:
    """s1: prepare and return the canonical command."""
    return store.prepare(command)


def s2(command: dict[str, str], store: object) -> str:
    """s2: accept the command into the journal and return the event id."""
    return store.append(command)


def s3(command: dict[str, str], event_id: str, store: object) -> None:
    """s3: register the command-key/occurrence mapping for the event."""
    store.register(command, event_id)


def s4(event_id: str, store: object) -> dict[str, str]:
    """s4: load the journal event."""
    return store.load(event_id)


def s5(event: dict[str, str], store: object) -> str:
    """s5: settle the effect for the event and return the effect id."""
    return store.settle(event)


def s6(sequence: int, store: object) -> None:
    """s6: advance the settlement cursor."""
    store.advance(sequence)
