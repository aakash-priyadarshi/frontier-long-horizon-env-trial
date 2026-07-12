from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterator

import pytest

from agent_surface.runtime import RuntimeEngine
from agent_surface.trace import TraceCapabilityAuthority
from event_service_substrate import RecoveryAuthority, build_fixture
from event_service_substrate.store import StateStore
from training_ground import load_environment
from training_ground.policies import IDEMPOTENT_FLOW, SETTINGS, valid_repair_policy


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def execute_policy(
    *,
    profile: int = 0,
    seed: int = 0,
    work_dir: Path | None = None,
    policy: list[dict[str, Any]] | None = None,
    max_steps: int = 64,
):
    env = load_environment(
        "eval",
        seed,
        options={"profile": profile, "max_steps": max_steps},
        work_dir=work_dir,
    )
    env.reset()
    for action in policy or valid_repair_policy():
        _, _, terminated, truncated, _ = env.step(action)
        if terminated or truncated:
            break
    return env


@pytest.fixture
def valid_episode(tmp_path: Path) -> Iterator[Any]:
    env = execute_policy(profile=0, seed=0, work_dir=tmp_path / "valid")
    assert env.grade()["score"] == 1.0
    yield env
    env.close()


@pytest.fixture(scope="session")
def runtime_fixture_root() -> Iterator[Path]:
    root = Path(tempfile.mkdtemp(prefix="final-audit-fixture-"))
    shutil.rmtree(root)
    authority = RecoveryAuthority(
        bytes.fromhex("a740d62c0860d7f2d8c0b7261a622d9c8ab44298984e65ff8d53d365e486f731"),
        "scope-71e5a88c9bdc47f0",
    )
    fixture = build_fixture(root, 0, authority)
    fixture.close()
    yield root
    shutil.rmtree(root, ignore_errors=True)


def fresh_runtime_engine(
    fixture_root: Path,
    flow: str = IDEMPOTENT_FLOW,
    *,
    profile: int = 0,
    settings: str = SETTINGS,
) -> tuple[RuntimeEngine, Path]:
    root = Path(tempfile.mkdtemp(prefix="final-audit-runtime-"))
    active = root / "active"
    shutil.copytree(fixture_root / "workspace", active)
    (active / "service" / "flow.py").write_text(flow, encoding="utf-8")
    (active / "service" / "settings.toml").write_text(settings, encoding="utf-8")

    authority = RecoveryAuthority(
        bytes.fromhex("a740d62c0860d7f2d8c0b7261a622d9c8ab44298984e65ff8d53d365e486f731"),
        "scope-71e5a88c9bdc47f0",
    )
    store_path = root / "service.sqlite3"
    shutil.copy2(fixture_root / "service.sqlite3", store_path)
    store = StateStore(store_path, authority)
    store.pause_intake()
    store.restore_snapshot("S0")
    trace = TraceCapabilityAuthority.derive_from_recovery_authority(
        authority.key, authority.scope, profile
    )
    return RuntimeEngine(store, active, profile, trace, "final_audit", 1), root
