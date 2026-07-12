from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agent_surface.runtime import RuntimeStore
from training_ground.policies import SETTINGS, valid_repair_policy

from tests.final_audit.conftest import execute_policy, fresh_runtime_engine


INTENT_OUTBOX_FLOW = """from __future__ import annotations

def s1(command, store): return store.prepare(command)

def s2(command, store):
    existing = store.get_event_id(command.get("command_key"), command.get("occurrence_id"))
    return existing if existing else store.append(command)

def s3(command, event_id, store): store.register(command, event_id)

def s4(event_id, store): return store.load(event_id)

def s5(event, store):
    intent = store.get_intent(event["event_id"])
    if intent and intent["state"] == "completed":
        return intent["effect_id"]
    intent_id = intent["intent_id"] if intent else store.intent_create(
        event["event_id"], event["command_key"], event["occurrence_id"]
    )
    existing = store.effect_exists(event["event_id"])
    if existing:
        store.intent_complete(intent_id, existing)
        return existing
    effect_id = store.settle(event)
    store.intent_complete(intent_id, effect_id)
    return effect_id

def s6(sequence, store): store.advance(sequence)
"""


ATOMIC_REGISTRATION_PROGRESS_FLOW = """from __future__ import annotations

def s1(command, store): return store.prepare(command)

def s2(command, store):
    existing = store.get_event_id(command.get("command_key"), command.get("occurrence_id"))
    return existing if existing else store.append(command)

def s3(command, event_id, store): store.register(command, event_id)

def s4(event_id, store): return store.load(event_id)

def s5(event, store):
    existing = store.effect_exists(event["event_id"])
    if existing:
        store.mark_event(event["event_id"], "settled")
        return existing
    effect_id = store.settle(event)
    store.mark_event(event["event_id"], "settled")
    return effect_id

def s6(sequence, store): store.advance(sequence)
"""


def _runtime(runtime_fixture_root: Path) -> tuple[RuntimeStore, object, Path]:
    engine, root = fresh_runtime_engine(runtime_fixture_root)
    runtime = RuntimeStore(
        engine.store,
        profile=0,
        cutpoint=None,
        workload_id="H-LOGICAL",
        alias="logical",
        handle="handle",
        transient=False,
    )
    return runtime, engine, root


def _event(runtime: RuntimeStore, occurrence: str = "occ-1") -> dict[str, str]:
    command = {
        "command_key": "cmd-logical",
        "occurrence_id": occurrence,
        "amount": "100",
    }
    event_id = runtime.append(command)
    return runtime.load(event_id)


def test_stable_logical_effect_identity(runtime_fixture_root: Path) -> None:
    runtime, engine, root = _runtime(runtime_fixture_root)
    try:
        event = _event(runtime)
        first = runtime.settle(
            event, logical_effect_id="settlement:occ-1", kind="settlement"
        )
        second = runtime.settle(
            event, logical_effect_id="settlement:occ-1", kind="settlement"
        )
        assert first == second
    finally:
        engine.store.close()
        shutil.rmtree(root, ignore_errors=True)


def test_multiple_legitimate_effects_for_one_event(runtime_fixture_root: Path) -> None:
    runtime, engine, root = _runtime(runtime_fixture_root)
    try:
        event = _event(runtime)
        first = runtime.settle(event, logical_effect_id="charge:occ-1", kind="charge")
        second = runtime.settle(event, logical_effect_id="receipt:occ-1", kind="receipt")
        assert first != second
        rows = engine.store.rows(
            "SELECT kind FROM effects WHERE source_event_id = ? ORDER BY kind",
            (event["event_id"],),
        )
        assert rows == [("charge",), ("receipt",)]
    finally:
        engine.store.close()
        shutil.rmtree(root, ignore_errors=True)


def test_replay_same_logical_effect_does_not_duplicate(runtime_fixture_root: Path) -> None:
    runtime, engine, root = _runtime(runtime_fixture_root)
    try:
        event = _event(runtime)
        for _ in range(3):
            runtime.settle(
                event, logical_effect_id="settlement:occ-1", kind="settlement"
            )
        rows = engine.store.rows(
            "SELECT effect_id FROM effects WHERE source_event_id = ?",
            (event["event_id"],),
        )
        assert len(rows) == 1
    finally:
        engine.store.close()
        shutil.rmtree(root, ignore_errors=True)


def test_conflicting_payload_reuse_is_rejected(runtime_fixture_root: Path) -> None:
    runtime, engine, root = _runtime(runtime_fixture_root)
    try:
        runtime.append(
            {"command_key": "cmd-conflict", "occurrence_id": "occ-conflict", "amount": "100"}
        )
        with pytest.raises(Exception):
            runtime.append(
                {"command_key": "cmd-conflict", "occurrence_id": "occ-conflict", "amount": "200"}
            )
    finally:
        engine.store.close()
        shutil.rmtree(root, ignore_errors=True)


def test_same_shape_different_occurrence_is_accepted(runtime_fixture_root: Path) -> None:
    runtime, engine, root = _runtime(runtime_fixture_root)
    try:
        first = runtime.append(
            {"command_key": "cmd-repeat", "occurrence_id": "occ-first", "amount": "100"}
        )
        second = runtime.append(
            {"command_key": "cmd-repeat", "occurrence_id": "occ-second", "amount": "100"}
        )
        assert first != second
        assert len(engine.store.rows("SELECT event_id FROM journal WHERE command_key = ?", ("cmd-repeat",))) == 2
    finally:
        engine.store.close()
        shutil.rmtree(root, ignore_errors=True)


@pytest.mark.parametrize("profile", (0, 1))
def test_intent_outbox_repair_family_is_accepted(tmp_path: Path, profile: int) -> None:
    policy = valid_repair_policy(flow=INTENT_OUTBOX_FLOW, settings=SETTINGS)
    env = execute_policy(
        profile=profile, seed=profile, work_dir=tmp_path / f"intent-{profile}", policy=policy
    )
    try:
        assert env.grade()["score"] == 1.0
    finally:
        env.close()

@pytest.mark.parametrize("profile", (0, 1))
def test_alternate_atomic_registration_progress_family_is_accepted(
    tmp_path: Path, profile: int
) -> None:
    policy = valid_repair_policy(flow=ATOMIC_REGISTRATION_PROGRESS_FLOW, settings=SETTINGS)
    env = execute_policy(
        profile=profile, seed=profile, work_dir=tmp_path / f"atomic-{profile}", policy=policy
    )
    try:
        assert env.grade()["score"] == 1.0
    finally:
        env.close()
