"""Public stage composition for intake and settlement delivery."""

from __future__ import annotations


def s1(command: dict[str, str]) -> dict[str, str]:
    return dict(command)


def s2(command: dict[str, str], store: object) -> str:
    return store.append(command)


def s3(command: dict[str, str], event_id: str, store: object) -> None:
    store.register(command, event_id)


def s4(event_id: str, store: object) -> dict[str, str]:
    return store.load(event_id)


def s5(event: dict[str, str], store: object) -> str:
    return store.settle(event)


def s6(sequence: int, store: object) -> None:
    store.advance(sequence)

