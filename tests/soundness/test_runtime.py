from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from agent_surface.runtime import RuntimeEngine
from agent_surface.trace import TraceCapabilityAuthority
from event_service_substrate import RecoveryAuthority


@pytest.fixture(scope="module")
def fixture_root():
    root = Path(tempfile.mkdtemp())
    shutil.rmtree(root, ignore_errors=True)
    key = bytes.fromhex("a740d62c0860d7f2d8c0b7261a622d9c8ab44298984e65ff8d53d365e486f731")
    scope = "scope-71e5a88c9bdc47f0"
    auth = RecoveryAuthority(key, scope)
    from event_service_substrate import build_fixture

    build_fixture(root, 0, auth)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _fresh_engine(root: Path, profile: int, attempt_budget: int = 3) -> RuntimeEngine:
    active = Path(tempfile.mkdtemp()) / "active"
    shutil.copytree(root / "workspace", active)
    settings = active / "service" / "settings.toml"
    settings.write_text(
        f"[service]\nintake_enabled = true\nsettlement_enabled = true\n"
        f"attempt_budget = {attempt_budget}\ntransient_behavior = \"retry\"\n",
        encoding="utf-8",
    )
    key = bytes.fromhex("a740d62c0860d7f2d8c0b7261a622d9c8ab44298984e65ff8d53d365e486f731")
    scope = "scope-71e5a88c9bdc47f0"
    auth = RecoveryAuthority(key, scope)
    store_path = Path(tempfile.mktemp(suffix=".sqlite3"))
    shutil.copy2(root / "service.sqlite3", store_path)
    from event_service_substrate.store import StateStore

    store = StateStore(store_path, auth)
    store.pause_intake()
    store.restore_snapshot("S0")
    trace = TraceCapabilityAuthority.derive_from_recovery_authority(key, scope, profile)
    return RuntimeEngine(store, active, profile, trace, "test_soundness", 1)


def test_public_workloads_pass_with_idempotent_flow(fixture_root: Path) -> None:
    from training_ground.policies import LOGICAL_IDENTITY_FLOW

    engine = _fresh_engine(fixture_root, 0)
    (engine.active_workspace / "service" / "flow.py").write_text(
        LOGICAL_IDENTITY_FLOW, encoding="utf-8"
    )
    for wl in ("P1", "P2", "P3"):
        receipt = engine.run(wl)
        assert receipt["outcome"] == "pass", receipt
        assert receipt["effect_count"] == receipt["event_count"], receipt


def test_ha1_rejects_non_idempotent_s5(fixture_root: Path) -> None:
    engine = _fresh_engine(fixture_root, 0)
    receipt = engine.run("H-A1", cutpoint="s5.exit")
    assert receipt["outcome"] == "fail", receipt


def test_hb2_rejects_non_idempotent_s2(fixture_root: Path) -> None:
    engine = _fresh_engine(fixture_root, 1)
    receipt = engine.run("H-B2")
    assert receipt["outcome"] == "fail", receipt


def test_hs2_rejects_non_idempotent_s2(fixture_root: Path) -> None:
    engine = _fresh_engine(fixture_root, 0)
    receipt = engine.run("H-S2")
    assert receipt["outcome"] == "fail", receipt
