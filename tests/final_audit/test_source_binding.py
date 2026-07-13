from __future__ import annotations

import importlib.util
import inspect
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.final_audit.conftest import REPOSITORY_ROOT


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


@pytest.fixture
def source_repo(tmp_path: Path) -> dict[str, str | Path]:
    repo = tmp_path / "repo"
    for path in (
        repo / "src" / "package.py",
        repo / "tests" / "test_package.py",
        repo / "scripts" / "helper.py",
        repo / "evidence" / "final-environment.json",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"initial:{path.name}\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "audit@example.invalid")
    _git(repo, "config", "user.name", "Final Audit")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "source")
    source = _git(repo, "rev-parse", "HEAD")
    return {"repo": repo, "source": source}


def _load_verifier_module() -> ModuleType:
    path = REPOSITORY_ROOT / "scripts" / "verify_final_environment.py"
    name = f"final_audit_verify_{id(path)}_{len(sys.modules)}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _invoke(
    monkeypatch: pytest.MonkeyPatch,
    repo: Path,
    args: list[str],
    *,
    pytest_stdout_tail: str = "1 passed in 0.01s",
) -> tuple[int, Path]:
    module = _load_verifier_module()
    output = repo / "evidence" / "final-environment.json"
    if "--source-commit" in args and "--source-commit" not in inspect.getsource(module):
        # An unknown argparse flag is not evidence that a source object was
        # actually validated. Return success so every rejection assertion stays
        # red until the final verifier implements the binding interface.
        return 0, output
    monkeypatch.setattr(module, "REPOSITORY_ROOT", repo)
    monkeypatch.setattr(
        module,
        "_run_pytest",
        lambda *a, **k: {
            "command": "pytest",
            "exit_code": 0,
            "test_count": 1,
            "passed": True,
            "stdout_tail": pytest_stdout_tail,
        },
    )
    monkeypatch.setattr(
        module,
        "_run_cli",
        lambda *a: ["instance-1"] if a and a[0] == "list-instances" else {"score": 1.0},
    )
    monkeypatch.setattr(
        module,
        "_run_gym_valid",
        lambda *a, **k: {
            "terminated": True,
            "reward": 1.0,
            "score_one": True,
            "check_env_passed": True,
            "check_env_error": None,
        },
    )
    monkeypatch.setattr(
        module,
        "_horizon_metrics",
        lambda: {
            "pair_blind_policy_actions": 15,
            "includes_diagnostics": True,
            "includes_trace": True,
            "includes_rollback": True,
        },
    )
    monkeypatch.setattr(
        module,
        "_gold_families",
        lambda: {
            "logical_identity_profile0": {"score": 1.0, "verdict": "pass"},
            "intent_outbox_profile0": {"score": 1.0, "verdict": "pass"},
        },
    )
    monkeypatch.setattr(
        module,
        "_wrong_control_matrix",
        lambda: [
            {
                "name": "control",
                "executed": True,
                "exploit_path_reached": True,
                "failed_predicates": ["public_workloads_pass"],
            }
        ],
    )
    monkeypatch.setattr(
        module,
        "_reward_ablation_matrix",
        lambda: {"without_transcript_integrity": 0.0, "without_bounded_resources": 0.0},
    )
    monkeypatch.setattr(module, "_run_command", lambda *a, **k: ("INTERNAL_SIDE_CAR\n", 0))
    monkeypatch.setattr(sys, "argv", [str(module.__file__), "--output", str(output), *args])
    try:
        return int(module.main()), output
    except SystemExit as exc:
        return int(exc.code or 0), output
    except ValueError:
        return 2, output


def _receipt_tip(repo: Path) -> str:
    receipt = repo / "evidence" / "final-environment.json"
    receipt.write_text("receipt-only\n", encoding="utf-8")
    _git(repo, "add", "evidence/final-environment.json")
    _git(repo, "commit", "-q", "-m", "receipt")
    return _git(repo, "rev-parse", "HEAD")


def test_missing_source_commit_is_rejected(
    monkeypatch: pytest.MonkeyPatch, source_repo: dict[str, str | Path]
) -> None:
    rc, _ = _invoke(monkeypatch, source_repo["repo"], [])  # type: ignore[arg-type]
    assert rc != 0


def test_receipt_tip_cannot_be_misbound_as_source(
    monkeypatch: pytest.MonkeyPatch, source_repo: dict[str, str | Path]
) -> None:
    repo = source_repo["repo"]
    tip = _receipt_tip(repo)  # type: ignore[arg-type]
    rc, _ = _invoke(monkeypatch, repo, ["--source-commit", tip])  # type: ignore[arg-type]
    assert rc != 0


def test_nonexistent_commit_is_rejected(
    monkeypatch: pytest.MonkeyPatch, source_repo: dict[str, str | Path]
) -> None:
    rc, _ = _invoke(
        monkeypatch,
        source_repo["repo"],  # type: ignore[arg-type]
        ["--source-commit", "f" * 40],
    )
    assert rc != 0


def test_blob_sha_is_rejected(
    monkeypatch: pytest.MonkeyPatch, source_repo: dict[str, str | Path]
) -> None:
    repo = source_repo["repo"]
    blob = _git(repo, "hash-object", "src/package.py")  # type: ignore[arg-type]
    rc, _ = _invoke(monkeypatch, repo, ["--source-commit", blob])  # type: ignore[arg-type]
    assert rc != 0


def test_short_sha_is_rejected(
    monkeypatch: pytest.MonkeyPatch, source_repo: dict[str, str | Path]
) -> None:
    rc, _ = _invoke(
        monkeypatch,
        source_repo["repo"],  # type: ignore[arg-type]
        ["--source-commit", str(source_repo["source"])[:12]],
    )
    assert rc != 0


@pytest.mark.parametrize(
    "dirty_path",
    ("src/package.py", "tests/test_package.py", "scripts/helper.py"),
    ids=("dirty-source", "dirty-tests", "dirty-scripts"),
)
def test_dirty_protected_tree_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    source_repo: dict[str, str | Path],
    dirty_path: str,
) -> None:
    repo = source_repo["repo"]
    (repo / dirty_path).write_text("dirty\n", encoding="utf-8")  # type: ignore[operator]
    rc, _ = _invoke(
        monkeypatch,
        repo,  # type: ignore[arg-type]
        ["--source-commit", str(source_repo["source"])],
    )
    assert rc != 0


def test_receipt_only_tip_binds_explicit_source_parent(
    monkeypatch: pytest.MonkeyPatch, source_repo: dict[str, str | Path]
) -> None:
    repo = source_repo["repo"]
    _receipt_tip(repo)  # type: ignore[arg-type]
    rc, output = _invoke(
        monkeypatch,
        repo,  # type: ignore[arg-type]
        ["--source-commit", str(source_repo["source"])],
    )
    assert rc == 0
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["tested_source_commit"] == source_repo["source"]


def test_permitted_receipt_difference_does_not_dirty_source(
    monkeypatch: pytest.MonkeyPatch, source_repo: dict[str, str | Path]
) -> None:
    repo = source_repo["repo"]
    (repo / "evidence" / "final-environment.json").write_text(  # type: ignore[operator]
        "working receipt\n", encoding="utf-8"
    )
    rc, output = _invoke(
        monkeypatch,
        repo,  # type: ignore[arg-type]
        ["--source-commit", str(source_repo["source"])],
    )
    assert rc == 0
    assert json.loads(output.read_text(encoding="utf-8"))["tested_source_commit"] == source_repo["source"]


def test_receipt_regeneration_is_equal_after_removing_only_timestamp(
    monkeypatch: pytest.MonkeyPatch, source_repo: dict[str, str | Path]
) -> None:
    module = _load_verifier_module()
    pytest_outputs = iter(("1 passed in 0.01s", "1 passed in 9.99s"))
    monkeypatch.setattr(
        module,
        "_run_command",
        lambda *a, **k: (next(pytest_outputs), 0),
    )
    first_suite = module._run_pytest("tests")
    second_suite = module._run_pytest("tests")
    assert first_suite == second_suite
    assert first_suite["command"] == "python -m pytest tests -q"
    assert "stdout_tail" not in first_suite

    repo = source_repo["repo"]
    args = ["--source-commit", str(source_repo["source"])]
    rc, output = _invoke(
        monkeypatch,
        repo,  # type: ignore[arg-type]
        args,
        pytest_stdout_tail="1 passed in 0.01s",
    )
    assert rc == 0
    first = json.loads(output.read_text(encoding="utf-8"))

    rc, output = _invoke(
        monkeypatch,
        repo,  # type: ignore[arg-type]
        args,
        pytest_stdout_tail="1 passed in 9.99s",
    )
    assert rc == 0
    second = json.loads(output.read_text(encoding="utf-8"))

    first.pop("timestamp")
    second.pop("timestamp")
    assert first == second
