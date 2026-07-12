from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from integrations.apex_swe.adapter import run_apex_trial
from training_ground.policies import valid_repair_policy

from tests.final_audit.conftest import REPOSITORY_ROOT


def test_internal_sidecar_is_labeled_and_not_upstream(tmp_path: Path) -> None:
    result = run_apex_trial(
        "final-audit-sidecar",
        valid_repair_policy(),
        profile=0,
        work_dir=tmp_path,
    )
    execution = result["metadata"]["execution"]
    assert execution["kind"] == "internal_sidecar"
    assert execution["upstream_harness"]["executed"] is False
    assert execution["upstream_harness"]["status"] == "NOT VERIFIED"
    assert execution["docker"]["executed"] is False
    assert execution["docker"]["status"] == "NOT VERIFIED"


def test_public_only_sidecar_smoke_does_not_claim_strict_success() -> None:
    result = subprocess.run(
        [sys.executable, str(REPOSITORY_ROOT / "scripts" / "smoke_apex_scripted.py")],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "APEX_SCRIPTED_SMOKE_PASSED" not in result.stdout
    assert "STRICT_SUCCESS" not in result.stdout
    assert "INTERNAL_SIDE_CAR" in result.stdout
    assert "NOT VERIFIED" in result.stdout


def test_docker_nonexecution_is_reported_not_verified(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = REPOSITORY_ROOT / "scripts" / "smoke_apex_docker.py"
    spec = importlib.util.spec_from_file_location("final_audit_apex_docker", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "docker_available", lambda: False)
    assert module.main() == 0
    output = capsys.readouterr().out
    first_line = json.loads(output.splitlines()[0])
    assert first_line["status"] == "NOT VERIFIED"
    assert first_line["executed"] is False
    assert "PASSED" not in output


def test_upstream_harness_and_docker_have_distinct_execution_flags(tmp_path: Path) -> None:
    result = run_apex_trial(
        "final-audit-provenance",
        valid_repair_policy(),
        profile=0,
        work_dir=tmp_path,
    )
    execution = result["metadata"]["execution"]
    assert set(execution) >= {"kind", "upstream_harness", "docker"}
    assert execution["kind"] not in {"upstream_apx", "docker"}
    assert execution["upstream_harness"] != execution["docker"] or (
        execution["upstream_harness"]["status"] == "NOT VERIFIED"
        and execution["docker"]["status"] == "NOT VERIFIED"
    )


def test_documentation_marks_unexecuted_real_paths_not_verified() -> None:
    documentation = "\n".join(
        [
            (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8"),
            (REPOSITORY_ROOT / "docs" / "training-adapters.md").read_text(
                encoding="utf-8"
            ),
        ]
    ).lower()
    assert "upstream apex-swe harness: **not verified**" in documentation
    assert "docker execution: **not verified**" in documentation


def test_evaluated_container_recipe_excludes_privileged_builder_packages() -> None:
    task = (
        REPOSITORY_ROOT
        / "integrations"
        / "apex_swe"
        / "tasks"
        / "frontier-incident-smoke"
    )
    dockerfile = (task / "Dockerfile").read_text(encoding="utf-8").lower()
    compose = (task / "docker-compose.yaml").read_text(encoding="utf-8").lower()
    assert "copy src" not in dockerfile
    assert "strict_verifier" not in dockerfile
    assert "fixture_index" not in compose
