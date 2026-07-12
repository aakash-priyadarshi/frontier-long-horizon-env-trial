from __future__ import annotations

import inspect
import shutil
from pathlib import Path

from event_service_substrate import RecoveryAuthority, build_fixture
from event_service_substrate.instance import CODE_FILES
from training_ground import load_environment
from training_ground.manifests import build_manifest, list_instance_ids


def _public_bytes(root: Path) -> dict[str, bytes]:
    return {name: (root / "workspace" / name).read_bytes() for name in CODE_FILES}


def test_public_workspace_is_equal_across_pair(tmp_path: Path) -> None:
    key = bytes.fromhex("11" * 32)
    left_root = tmp_path / "left"
    right_root = tmp_path / "right"
    left = build_fixture(left_root, 0, RecoveryAuthority(key, "scope-left"))
    right = build_fixture(right_root, 1, RecoveryAuthority(key, "scope-right"))
    try:
        assert _public_bytes(left_root) == _public_bytes(right_root)
    finally:
        left.close()
        right.close()


def test_public_manifest_has_no_profile() -> None:
    public = build_manifest("eval", 7).public()
    assert "profile" not in public
    assert all("profile" not in str(key).lower() for key in public)


def test_public_manifest_module_has_no_seed_to_profile_formula() -> None:
    source = inspect.getsource(inspect.getmodule(build_manifest))
    forbidden = ("profile-", "effective_seed).hexdigest", "profile = int(")
    assert not any(token in source for token in forbidden)


def test_split_instance_ids_do_not_overlap() -> None:
    sets = {split: set(list_instance_ids(split, 1_000)) for split in ("train", "dev", "eval")}
    assert sets["train"].isdisjoint(sets["dev"])
    assert sets["train"].isdisjoint(sets["eval"])
    assert sets["dev"].isdisjoint(sets["eval"])


def test_hidden_runtime_workload_is_not_agent_callable(tmp_path: Path) -> None:
    env = load_environment("eval", 0, work_dir=tmp_path)
    try:
        env.reset()
        obs, reward, terminated, truncated, info = env.step(
            {"tool": "runtime.run", "arguments": {"workload_id": "H-A1"}}
        )
        assert reward == 0.0
        assert not terminated
        assert "error" in obs
        assert info["response"]["error"]["code"] != "ok"
        assert "workload_id" not in info["response"]
    finally:
        env.close()
