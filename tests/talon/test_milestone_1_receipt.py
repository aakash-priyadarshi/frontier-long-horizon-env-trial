from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import verify_talon_milestone_1 as verifier


SOURCE_SHA = "a" * 40


def command(name: str, count: int = 0, **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "command": name,
        "exit_code": 0,
        "passed": True,
        "test_count": count,
        "duration_seconds": 0.01,
        "classification": "real",
        **extra,
    }


def complete_commands() -> list[dict[str, Any]]:
    return [
        command("talon_python", 88),
        command("full_python_regression", 446),
        command("dashboard_unit", 48),
        command("dashboard_lint"),
        command("dashboard_typecheck"),
        command("dashboard_build"),
        command(
            "talon_playwright",
            10,
            skipped_count=0,
            executed_count=10,
            browser="chromium",
        ),
        command(
            "frontier_playwright",
            12,
            skipped_count=0,
            executed_count=12,
            browser="chromium",
        ),
        command(
            "dashboard_playwright",
            22,
            skipped_count=0,
            executed_count=22,
            browser="chromium",
        ),
        command("npm_audit"),
        command("uv_lock"),
        command("diff_check"),
    ]


def complete_receipt() -> dict[str, Any]:
    commands = complete_commands()
    isolation_checks = {
        "python_isolated": True,
        "simulator_import_blocked": True,
        "training_import_blocked": True,
        "verifier_import_blocked": True,
        "hidden_scenario_import_blocked": True,
        "privileged_source_absent": True,
        "metadata_environment_absent": True,
        "privileged_source_read_blocked": True,
        "private_dataset_read_blocked": True,
        "verifier_storage_read_blocked": True,
        "package_listing_blocked": True,
        "process_arguments_safe": True,
        "malformed_output_rejected": True,
        "malformed_output_public_error_sanitized": True,
        "oversized_output_rejected": True,
        "oversized_output_public_error_sanitized": True,
        "timeout_rejected": True,
        "timeout_public_error_sanitized": True,
        "public_errors_sanitized": True,
    }
    return verifier._build_receipt(
        source_commit=SOURCE_SHA,
        commands=commands,
        contract={
            "passed": True,
            "checks": {
                "command_link_requires_dedicated_request": True,
                "dataset_mutation_rejected": True,
                "approval_replay_rejected": True,
                "partition_instance_disjointness": True,
            },
        },
        physical_boundary={"passed": True, "action_count": 13},
        schema_versions={
            "classification": "runtime_import_and_static_assertion",
            "passed": True,
            "checks": {
                "action_schema_matches_expected": True,
                "private_dataset_schema_matches_expected": True,
            },
            "action_schema_version": "talon.action/3.0",
            "private_dataset_schema_version": "talon.private-dataset/3.0",
        },
        browser_verification=verifier._browser_verification(commands),
        policy_worker_isolation={
            "classification": "dynamically_executed",
            "passed": True,
            "checks": isolation_checks,
        },
        frontier_regression={
            "classification": "git_integrity_and_executed_regression",
            "passed": True,
            "source_integrity": {
                "training_ground_unchanged": True,
                "strict_verifier_unchanged": True,
            },
            "evidence_integrity": {
                "pre_existing_frontier_evidence_unchanged": True,
            },
            "python_tests": {"passed": True},
            "playwright": {"passed": True},
        },
    )


@pytest.mark.parametrize(
    ("module_name", "attribute", "value", "check"),
    [
        (
            "drone_decision_ground.actions",
            "ACTION_SCHEMA_VERSION",
            "talon.action/4.0",
            "action_schema_matches_expected",
        ),
        (
            "drone_decision_ground.actions",
            "ACTION_SCHEMA_VERSION",
            "",
            "action_schema_matches_expected",
        ),
        (
            "drone_training.datasets",
            "DATASET_SCHEMA_VERSION",
            "talon.private-dataset/2.0",
            "private_dataset_schema_matches_expected",
        ),
        (
            "drone_training.datasets",
            "DATASET_SCHEMA_VERSION",
            "",
            "private_dataset_schema_matches_expected",
        ),
    ],
)
def test_schema_versions_are_runtime_authoritative(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    attribute: str,
    value: str,
    check: str,
) -> None:
    module = __import__(module_name, fromlist=[attribute])
    monkeypatch.setattr(module, attribute, value)
    result = verifier._schema_versions()
    assert result["passed"] is False
    assert result["checks"][check] is False


def test_complete_receipt_records_required_metadata() -> None:
    receipt = complete_receipt()
    assert receipt["source_commit"] == SOURCE_SHA
    assert receipt["schema_versions"]["action_schema_version"] == "talon.action/3.0"
    assert (
        receipt["schema_versions"]["private_dataset_schema_version"]
        == "talon.private-dataset/3.0"
    )
    assert receipt["test_counts"] == {
        "talon_python": 88,
        "complete_python": 446,
        "dashboard_unit": 48,
        "playwright_total": 22,
        "playwright_talon": 10,
        "playwright_frontier": 12,
    }
    assert receipt["policy_worker_isolation"]["passed"] is True
    assert receipt["frontier_regression"]["passed"] is True
    assert receipt["dynamic_contract"]["checks"]["command_link_requires_dedicated_request"]
    assert receipt["dynamic_contract"]["checks"]["dataset_mutation_rejected"]
    assert receipt["dynamic_contract"]["checks"]["approval_replay_rejected"]
    assert receipt["dynamic_contract"]["checks"]["partition_instance_disjointness"]
    assert receipt["physical_boundary"]["passed"] is True
    assert receipt["learned_model_claims"]["safety_ready"] is False
    assert "C:\\\\Users\\\\" not in json.dumps(receipt)
    assert "/home/" not in json.dumps(receipt)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["schema_versions"].pop("action_schema_version"),
        lambda value: value["schema_versions"].pop("private_dataset_schema_version"),
        lambda value: value["browser_verification"]["talon"].pop("journey_count"),
        lambda value: value["policy_worker_isolation"].update({"passed": False}),
        lambda value: value["browser_verification"]["total"].update(
            {"journey_count": 21}
        ),
    ],
)
def test_incomplete_receipt_is_rejected(mutation: Any) -> None:
    receipt = copy.deepcopy(complete_receipt())
    mutation(receipt)
    with pytest.raises(AssertionError, match="incomplete Talon receipt"):
        verifier._validate_receipt_completeness(
            receipt, expected_source_commit=SOURCE_SHA
        )


def git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def integrity_repository(tmp_path: Path) -> tuple[Path, str]:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "talon-test@example.invalid")
    git(tmp_path, "config", "user.name", "Talon Test")
    for path, content in (
        ("src/training_ground/scoring.py", "SCORE = 1\n"),
        ("src/strict_verifier/scoring.py", "STRICT = True\n"),
        ("evidence/frontier.json", "{}\n"),
    ):
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "baseline")
    return tmp_path, git(tmp_path, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    "changed_path",
    [
        "src/training_ground/scoring.py",
        "src/strict_verifier/scoring.py",
        "evidence/frontier.json",
    ],
)
def test_frontier_integrity_rejects_mutation(tmp_path: Path, changed_path: str) -> None:
    repository, baseline = integrity_repository(tmp_path)
    destination = repository / changed_path
    destination.write_text(destination.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
    git(repository, "add", changed_path)
    git(repository, "commit", "-q", "-m", "mutation")
    source = git(repository, "rev-parse", "HEAD")
    result = verifier._frontier_integrity(
        source,
        complete_commands(),
        repository=repository,
        baseline=baseline,
    )
    assert result["passed"] is False
    if changed_path.startswith("src/training_ground"):
        assert result["source_integrity"]["training_ground_unchanged"] is False
    elif changed_path.startswith("src/strict_verifier"):
        assert result["source_integrity"]["strict_verifier_unchanged"] is False
    else:
        assert (
            result["evidence_integrity"][
                "pre_existing_frontier_evidence_unchanged"
            ]
            is False
        )
