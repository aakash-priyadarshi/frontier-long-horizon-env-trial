from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tests.final_audit.conftest import REPOSITORY_ROOT


@pytest.fixture(scope="module")
def receipt() -> dict[str, Any]:
    return json.loads(
        (REPOSITORY_ROOT / "evidence" / "final-environment.json").read_text(
            encoding="utf-8"
        )
    )


def test_receipt_has_validated_source_sha(receipt: dict[str, Any]) -> None:
    binding = receipt["source_binding"]
    assert binding["validated"] is True
    assert re.fullmatch(r"[0-9a-f]{40}", binding["validated_source_sha"])
    assert binding["validated_source_sha"] == receipt["tested_source_commit"]


def test_receipt_has_separate_suite_counts(receipt: dict[str, Any]) -> None:
    suites = receipt["suites"]
    required = {
        "milestone_1",
        "milestone_2",
        "final_core",
        "soundness",
        "controls",
        "adapters",
        "integrations",
        "final_audit",
    }
    assert required <= set(suites)
    assert all(isinstance(suites[name]["test_count"], int) for name in required)
    assert all("outcome" in suites[name] for name in required)


def test_receipt_has_hidden_workload_counts(receipt: dict[str, Any]) -> None:
    hidden = receipt["workloads"]["hidden"]
    assert hidden["total"] > 0
    assert hidden["shared"] > 0
    assert hidden["member"] > 0
    assert hidden["passed"] + hidden["failed"] == hidden["total"]


def test_receipt_has_two_gold_families(receipt: dict[str, Any]) -> None:
    families = receipt["gold_families"]
    assert len(families) >= 2
    assert len({family["family"] for family in families}) >= 2
    assert all(family["executed"] and family["score"] == 1.0 for family in families)


@pytest.mark.parametrize("section", ("controls", "cheats"))
def test_receipt_has_executed_attack_matrix(
    receipt: dict[str, Any], section: str
) -> None:
    rows = receipt[section]
    assert rows
    assert all("executed" in row for row in rows)
    assert all("exploit_path_reached" in row for row in rows)
    assert all("failed_predicates" in row for row in rows)


def test_receipt_records_failed_predicates(receipt: dict[str, Any]) -> None:
    assert isinstance(receipt["failed_predicates"], list)
    assert all(isinstance(value, str) for value in receipt["failed_predicates"])


def test_receipt_records_ablations(receipt: dict[str, Any]) -> None:
    assert receipt["ablations"]
    assert all("predicate" in row and "score" in row for row in receipt["ablations"])


def test_receipt_records_horizon(receipt: dict[str, Any]) -> None:
    horizon = receipt["horizon"]
    assert horizon["meaningful_executed_actions"] >= 15
    assert horizon["pair_blind"] is True
    assert horizon["required_actions_present"] is True


def test_receipt_records_gymnasium_result(receipt: dict[str, Any]) -> None:
    gym = receipt["gymnasium"]
    assert gym["check_env"]["executed"] is True
    assert gym["check_env"]["passed"] is True
    assert gym["observation_space"] is True
    assert gym["action_space"] is True


def test_receipt_records_apex_result(receipt: dict[str, Any]) -> None:
    apex = receipt["apex"]
    assert apex["sidecar"]["executed"] is True
    assert "upstream_harness" in apex
    if not apex["upstream_harness"]["executed"]:
        assert apex["upstream_harness"]["status"] == "NOT VERIFIED"


def test_receipt_records_docker_status(receipt: dict[str, Any]) -> None:
    docker = receipt["docker"]
    assert "executed" in docker and "status" in docker
    if not docker["executed"]:
        assert docker["status"] == "NOT VERIFIED"


def test_receipt_records_limitations(receipt: dict[str, Any]) -> None:
    limitations = receipt["limitations"]
    assert isinstance(limitations, list)
    assert limitations
    assert all(isinstance(value, str) and value.strip() for value in limitations)
