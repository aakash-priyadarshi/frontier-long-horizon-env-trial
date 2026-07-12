from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.final_audit.conftest import fresh_runtime_engine


FLOW_TEMPLATE = """from __future__ import annotations

def s1(command, store): return store.prepare(command)

{s2}

def s3(command, event_id, store): store.register(command, event_id)

def s4(event_id, store): return store.load(event_id)

{s5}

{s6}
"""

SAFE_S2 = """def s2(command, store):
    existing = store.get_event_id(command.get("command_key"), command.get("occurrence_id"))
    return existing if existing else store.append(command)"""
SAFE_S5 = """def s5(event, store):
    existing = store.effect_exists(event["event_id"])
    return existing if existing else store.settle(event)"""
SAFE_S6 = "def s6(sequence, store): store.advance(sequence)"

SABOTAGE_FLOWS = {
    "fake-effect-id": FLOW_TEMPLATE.format(
        s2=SAFE_S2,
        s5='def s5(event, store): return "efx_fabricated_without_row"',
        s6=SAFE_S6,
    ),
    "effects-disabled": FLOW_TEMPLATE.format(
        s2=SAFE_S2,
        s5='def s5(event, store): return "disabled"',
        s6=SAFE_S6,
    ),
    "duplicate-journal-row": FLOW_TEMPLATE.format(
        s2="""def s2(command, store):
    existing = store.get_event_id(command.get("command_key"), command.get("occurrence_id"))
    if existing: return existing
    store.append(command)
    return store.append(command)""",
        s5=SAFE_S5,
        s6=SAFE_S6,
    ),
    "duplicate-effect-row": FLOW_TEMPLATE.format(
        s2=SAFE_S2,
        s5="""def s5(event, store):
    existing = store.effect_exists(event["event_id"])
    if existing: return existing
    store.settle(event)
    return store.settle(event)""",
        s6=SAFE_S6,
    ),
    "wrong-amount": FLOW_TEMPLATE.format(
        s2=SAFE_S2,
        s5="""def s5(event, store):
    existing = store.effect_exists(event["event_id"])
    if existing: return existing
    effect_id = store.settle(event)
    store.store.connection.execute("UPDATE effects SET amount = 999 WHERE effect_id = ?", (effect_id,))
    return effect_id""",
        s6=SAFE_S6,
    ),
    "stale-cursor": FLOW_TEMPLATE.format(
        s2=SAFE_S2,
        s5=SAFE_S5,
        s6="def s6(sequence, store): return None",
    ),
}

PUBLIC_AND_SHARED = ("P1", "P2", "P3", "H-S1", "H-S2", "H-TRANS")


@pytest.mark.parametrize("workload_id", PUBLIC_AND_SHARED)
@pytest.mark.parametrize("sabotage", tuple(SABOTAGE_FLOWS))
def test_public_and_shared_workloads_require_durable_semantics(
    runtime_fixture_root: Path, sabotage: str, workload_id: str
) -> None:
    settings = """[service]
intake_enabled = true
settlement_enabled = false
attempt_budget = 3
transient_behavior = "retry"
""" if sabotage == "effects-disabled" else """[service]
intake_enabled = true
settlement_enabled = true
attempt_budget = 3
transient_behavior = "retry"
"""
    engine, root = fresh_runtime_engine(
        runtime_fixture_root, SABOTAGE_FLOWS[sabotage], settings=settings
    )
    try:
        receipt = engine.run(workload_id)
        assert receipt["outcome"] != "pass", receipt
    finally:
        engine.store.close()
        shutil.rmtree(root, ignore_errors=True)

def test_transient_cannot_claim_pass_without_durable_effect(runtime_fixture_root: Path) -> None:
    engine, root = fresh_runtime_engine(
        runtime_fixture_root, SABOTAGE_FLOWS["fake-effect-id"]
    )
    try:
        receipt = engine.run("H-TRANS")
        rows = engine.store.rows(
            "SELECT effect_id FROM effects WHERE source_event_id IN "
            "(SELECT event_id FROM journal WHERE command_key = ?)",
            ("cmd_s_transient",),
        )
        assert receipt["outcome"] != "pass"
        assert receipt["effect_count"] == len(rows)
    finally:
        engine.store.close()
        shutil.rmtree(root, ignore_errors=True)
