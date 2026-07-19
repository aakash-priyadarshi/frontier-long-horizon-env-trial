from __future__ import annotations

import pytest

from scripts import verify_talon_milestone_2 as verifier


def test_dirty_tree_evidence_refusal_is_explicit() -> None:
    with pytest.raises(RuntimeError, match="clean working tree"):
        verifier.refuse_dirty_evidence(" M src/file.py")
    verifier.refuse_dirty_evidence("")


def test_milestone_1_receipt_blob_identity_reports_failed_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(tuple(command))
        if command[:2] == ["git", "rev-parse"]:
            return type("Completed", (), {"returncode": 0, "stdout": "aaa\n", "stderr": ""})()
        if command[:2] == ["git", "hash-object"]:
            return type("Completed", (), {"returncode": 0, "stdout": "bbb\n", "stderr": ""})()
        if command[:3] == ["git", "diff", "--quiet"]:
            return type("Completed", (), {"returncode": 1, "stdout": "", "stderr": ""})()
        raise AssertionError(command)

    monkeypatch.setattr(verifier.subprocess, "run", fake_run)
    result = verifier._m1_receipt_blob_identity("abc123")
    assert result["passed"] is False
    assert result["integrity_method"] == "git_blob_identity"
    assert result["working_oid"] == "bbb"
    assert result["committed_oid"] == "aaa"


def test_physical_boundary_scan_has_no_control_implementation() -> None:
    assert verifier._source_scan()["passed"] is True


def test_td_backup_documentation_scan_passes() -> None:
    result = verifier._td_backup_documentation()
    assert result["passed"] is True


def test_receipt_completeness_requires_new_check_keys() -> None:
    incomplete = {
        "receipt_version": "talon.milestone-2-verification/1.0",
        "source_commit": "abc",
        "generated_at": "now",
        "passed": True,
        "checks": {"dynamic_offline_rl": {"passed": True}},
        "limitations": [],
    }
    result = verifier._receipt_completeness(incomplete)
    assert result["passed"] is False
    assert "td_backup_documentation" in result["missing_check_keys"]
    assert "receipt_completeness" in result["missing_check_keys"]
    assert "playwright" in result["missing_check_keys"]
    assert "frontier_integrity" in result["missing_check_keys"]
    assert "product_hardenings" in result["missing_check_keys"]
    assert "bc_checkpoint_compatibility" in result["missing_check_keys"]


def _valid_bc_architecture_block() -> dict:
    return {
        "passed": True,
        "valid_load": True,
        "missing_environment_rejected": True,
        "missing_verifier_rejected": True,
        "environment_mismatch_rejected": True,
        "verifier_mismatch_rejected": True,
        "action_schema_mismatch_rejected": True,
        "feature_schema_mismatch_rejected": True,
        "architecture_config_mismatch_rejected": True,
    }


def _valid_bc_checkpoint_compatibility_block() -> dict:
    return {
        "passed": True,
        "classification": "dynamically_executed",
        "missing_architectures": [],
        "gru": _valid_bc_architecture_block(),
        "decision_transformer": _valid_bc_architecture_block(),
    }


def test_receipt_completeness_rejects_missing_dynamic_proof_keys() -> None:
    incomplete = {
        "receipt_version": "talon.milestone-2-verification/1.0",
        "source_commit": "abc",
        "generated_at": "now",
        "passed": True,
        "checks": {
            "dynamic_offline_rl": {
                "passed": True,
                "checks": {
                    "self_consistent_rewrite_rejected": True,
                },
            },
            "physical_response_boundary": {"passed": True},
            "milestone_1_receipt_unchanged": {"passed": True, "integrity_method": "git_blob_identity"},
            "td_backup_documentation": {"passed": True},
            "frontier_integrity": {"passed": True, "integrity_method": "git_blob_identity"},
            "playwright": {
                "passed": True,
                "browser": "chromium",
                "workers": 1,
                "skipped": 0,
                "result": "listed_only",
                "talon": {"count": 1, "result": "listed_only", "command": "x", "skipped": 0},
                "frontier": {"count": 1, "result": "listed_only", "command": "y", "skipped": 0},
                "complete": {"count": 2, "result": "listed_only", "command": "z", "skipped": 0},
            },
            "product_hardenings": {
                "passed": True,
                "checks": {
                    "policy_client_signature_absent": {
                        "passed": True,
                        "classification": "static_source_inspection",
                    },
                    "product_policy_client_injection_rejected": {
                        "passed": True,
                        "classification": "dynamically_executed",
                    },
                    "for_tests_helper_not_used_by_product": {
                        "passed": True,
                        "classification": "static_source_inspection",
                    },
                    "expected_offline_dataset_digest_binding": {
                        "passed": True,
                        "classification": "dynamically_executed",
                    },
                },
            },
            "bc_checkpoint_compatibility": _valid_bc_checkpoint_compatibility_block(),
            "receipt_completeness": {"passed": True},
        },
        "limitations": [],
    }
    result = verifier._receipt_completeness(incomplete)
    assert result["passed"] is False
    assert "immutable_record_rewrite_rejected" in result["missing_dynamic_proof_keys"]
    assert "caller_supplied_digest_is_not_provenance" in result["missing_dynamic_proof_keys"]
    assert "cross_run_substitution_rejected" in result["missing_dynamic_proof_keys"]
    assert "cross_dataset_substitution_rejected" in result["missing_dynamic_proof_keys"]
    assert "self_consistent_rewrite_rejected" not in verifier.REQUIRED_DYNAMIC_PROOF_KEYS


def _valid_product_hardenings_block() -> dict:
    return {
        "passed": True,
        "checks": {
            "policy_client_signature_absent": {
                "passed": True,
                "classification": "static_source_inspection",
            },
            "product_policy_client_injection_rejected": {
                "passed": True,
                "classification": "dynamically_executed",
                "probes": {},
            },
            "for_tests_helper_not_used_by_product": {
                "passed": True,
                "classification": "static_source_inspection",
            },
            "expected_offline_dataset_digest_binding": {
                "passed": True,
                "classification": "dynamically_executed",
            },
        },
    }


def _base_checks_for_receipt() -> dict:
    return {
        "dynamic_offline_rl": {
            "passed": True,
            "checks": {
                "immutable_record_rewrite_rejected": True,
                "caller_supplied_digest_is_not_provenance": True,
                "cross_run_substitution_rejected": True,
                "cross_dataset_substitution_rejected": True,
            },
        },
        "physical_response_boundary": {"passed": True},
        "milestone_1_receipt_unchanged": {"passed": True, "integrity_method": "git_blob_identity"},
        "td_backup_documentation": {"passed": True},
        "frontier_integrity": {"passed": True, "integrity_method": "git_blob_identity"},
        "playwright": {
            "passed": True,
            "browser": "chromium",
            "workers": 1,
            "skipped": 0,
            "result": "listed_only",
            "talon": {"count": 1, "result": "listed_only", "command": "x", "skipped": 0},
            "frontier": {"count": 1, "result": "listed_only", "command": "y", "skipped": 0},
            "complete": {"count": 2, "result": "listed_only", "command": "z", "skipped": 0},
        },
        "product_hardenings": _valid_product_hardenings_block(),
        "bc_checkpoint_compatibility": _valid_bc_checkpoint_compatibility_block(),
        "receipt_completeness": {"passed": True},
    }


def test_receipt_completeness_rejects_missing_product_policy_client_injection() -> None:
    incomplete_hardenings = _valid_product_hardenings_block()
    del incomplete_hardenings["checks"]["product_policy_client_injection_rejected"]
    incomplete = {
        "receipt_version": "talon.milestone-2-verification/1.0",
        "source_commit": "abc",
        "generated_at": "now",
        "passed": True,
        "checks": {**_base_checks_for_receipt(), "product_hardenings": incomplete_hardenings},
        "limitations": [],
    }
    result = verifier._receipt_completeness(incomplete)
    assert result["passed"] is False
    assert "product_policy_client_injection_rejected" in result["missing_product_hardening_keys"]


def test_receipt_completeness_rejects_wrong_product_hardening_classification() -> None:
    base_checks = _base_checks_for_receipt()
    wrong = _valid_product_hardenings_block()
    wrong["checks"]["policy_client_signature_absent"]["classification"] = "dynamically_executed"
    wrong["checks"]["product_policy_client_injection_rejected"]["classification"] = "static_source_inspection"
    incomplete = {
        "receipt_version": "talon.milestone-2-verification/1.0",
        "source_commit": "abc",
        "generated_at": "now",
        "passed": True,
        "checks": {**base_checks, "product_hardenings": wrong},
        "limitations": [],
    }
    result = verifier._receipt_completeness(incomplete)
    assert result["passed"] is False
    problems = result["product_hardening_classification_problems"]
    assert any("policy_client_signature_absent" in item for item in problems)
    assert any("product_policy_client_injection_rejected" in item for item in problems)

    sole_dynamic = _valid_product_hardenings_block()
    sole_dynamic["classification"] = "dynamically_executed"
    sole = {
        "receipt_version": "talon.milestone-2-verification/1.0",
        "source_commit": "abc",
        "generated_at": "now",
        "passed": True,
        "checks": {**base_checks, "product_hardenings": sole_dynamic},
        "limitations": [],
    }
    result = verifier._receipt_completeness(sole)
    assert result["passed"] is False
    assert any("sole top-level" in item for item in result["product_hardening_classification_problems"])


def test_receipt_completeness_rejects_incomplete_playwright_schema() -> None:
    base_checks = _base_checks_for_receipt()
    missing_component = {
        "receipt_version": "talon.milestone-2-verification/1.0",
        "source_commit": "abc",
        "generated_at": "now",
        "passed": True,
        "checks": {
            **base_checks,
            "playwright": {
                "passed": True,
                "browser": "chromium",
                "workers": 1,
                "skipped": 0,
                "result": "listed_only",
                "talon": {"count": 10, "result": "listed_only", "command": "talon"},
                # frontier / complete missing
            },
        },
        "limitations": [],
    }
    result = verifier._receipt_completeness(missing_component)
    assert result["passed"] is False
    assert any("frontier" in item or "complete" in item for item in result["playwright_schema_problems"])

    inconsistent = {
        "receipt_version": "talon.milestone-2-verification/1.0",
        "source_commit": "abc",
        "generated_at": "now",
        "passed": True,
        "checks": {
            **base_checks,
            "playwright": {
                "passed": True,
                "browser": "chromium",
                "workers": 1,
                "skipped": 0,
                "result": "listed_only",
                "talon": {"count": 10, "result": "listed_only", "command": "talon", "skipped": 0},
                "frontier": {"count": 12, "result": "listed_only", "command": "frontier", "skipped": 0},
                "complete": {"count": 24, "result": "listed_only", "command": "all", "skipped": 0},
            },
        },
        "limitations": [],
    }
    result = verifier._receipt_completeness(inconsistent)
    assert result["passed"] is False
    assert any("talon+frontier" in item for item in result["playwright_schema_problems"])

    skipped_nonzero = {
        "receipt_version": "talon.milestone-2-verification/1.0",
        "source_commit": "abc",
        "generated_at": "now",
        "passed": True,
        "checks": {
            **base_checks,
            "playwright": {
                "passed": True,
                "browser": "chromium",
                "workers": 1,
                "skipped": 0,
                "result": "listed_only",
                "talon": {"count": 10, "result": "listed_only", "command": "talon", "skipped": 1},
                "frontier": {"count": 12, "result": "listed_only", "command": "frontier", "skipped": 0},
                "complete": {"count": 22, "result": "listed_only", "command": "all", "skipped": 0},
            },
        },
        "limitations": [],
    }
    result = verifier._receipt_completeness(skipped_nonzero)
    assert result["passed"] is False
    assert any("skipped nonzero" in item for item in result["playwright_schema_problems"])


def test_receipt_completeness_rejects_incomplete_bc_checkpoint_compatibility() -> None:
    base = _base_checks_for_receipt()
    incomplete_bc = _valid_bc_checkpoint_compatibility_block()
    del incomplete_bc["gru"]["environment_mismatch_rejected"]
    incomplete_bc["gru"]["passed"] = True  # falsely claim pass while probe missing
    report = {
        "receipt_version": "talon.milestone-2-verification/1.0",
        "source_commit": "abc",
        "generated_at": "now",
        "passed": True,
        "checks": {**base, "bc_checkpoint_compatibility": incomplete_bc},
        "limitations": [],
    }
    result = verifier._receipt_completeness(report)
    assert result["passed"] is False
    assert any("environment_mismatch_rejected" in item for item in result["bc_checkpoint_compatibility_problems"])

    false_probe = _valid_bc_checkpoint_compatibility_block()
    false_probe["decision_transformer"]["valid_load"] = False
    report["checks"]["bc_checkpoint_compatibility"] = false_probe
    result = verifier._receipt_completeness(report)
    assert result["passed"] is False
    assert any("decision_transformer.valid_load" in item for item in result["bc_checkpoint_compatibility_problems"])

    wrong_class = _valid_bc_checkpoint_compatibility_block()
    wrong_class["classification"] = "static_source_inspection"
    report["checks"]["bc_checkpoint_compatibility"] = wrong_class
    result = verifier._receipt_completeness(report)
    assert result["passed"] is False
    assert any("dynamically_executed" in item for item in result["bc_checkpoint_compatibility_problems"])


def test_product_path_scan_covers_required_modules() -> None:
    names = {path.name for path in verifier.PRODUCT_PATH_SCAN}
    assert names >= {
        "api.py",
        "orchestration.py",
        "worker.py",
        "cli.py",
        "persistence.py",
        "offline_evaluation.py",
        "offline_policy_isolation.py",
    }
    scan = verifier._scan_product_paths_for_symbol("evaluate_offline_checkpoint_for_tests")
    assert scan["passed"] is True
    assert scan["classification"] == "static_source_inspection"
    assert scan["product_path_hits"] == []


def test_bc_checkpoint_compatibility_probe_passes_dynamically() -> None:
    result = verifier._bc_checkpoint_compatibility()
    assert result["classification"] == "dynamically_executed"
    assert result["passed"] is True
    for architecture in ("gru", "decision_transformer"):
        block = result[architecture]
        assert block["passed"] is True
        for key in verifier.REQUIRED_BC_PROBE_KEYS:
            assert block[key] is True, f"{architecture}.{key}"


def test_validate_playwright_section_requires_structure() -> None:
    problems = verifier._validate_playwright_section({"browser": "firefox"})
    assert any("chromium" in item for item in problems)
    assert any("workers" in item for item in problems)


def test_parse_playwright_list_count() -> None:
    assert verifier._parse_playwright_list_count("Total: 12 tests in 1 file\n") == 12
    with pytest.raises(ValueError):
        verifier._parse_playwright_list_count("no totals here")


def test_required_dynamic_proof_keys_renamed() -> None:
    assert "self_consistent_rewrite_rejected" not in verifier.REQUIRED_DYNAMIC_PROOF_KEYS
    assert "immutable_record_rewrite_rejected" in verifier.REQUIRED_DYNAMIC_PROOF_KEYS
    assert "caller_supplied_digest_is_not_provenance" in verifier.REQUIRED_DYNAMIC_PROOF_KEYS
    assert "cross_run_substitution_rejected" in verifier.REQUIRED_DYNAMIC_PROOF_KEYS
    assert "cross_dataset_substitution_rejected" in verifier.REQUIRED_DYNAMIC_PROOF_KEYS


def test_required_product_hardening_keys_and_classifications() -> None:
    assert "policy_client_signature_absent" in verifier.REQUIRED_PRODUCT_HARDENING_KEYS
    assert "product_policy_client_injection_rejected" in verifier.REQUIRED_PRODUCT_HARDENING_KEYS
    assert "for_tests_helper_not_used_by_product" in verifier.REQUIRED_PRODUCT_HARDENING_KEYS
    assert "expected_offline_dataset_digest_binding" in verifier.REQUIRED_PRODUCT_HARDENING_KEYS
    assert (
        verifier.REQUIRED_PRODUCT_HARDENING_CLASSIFICATIONS["policy_client_signature_absent"]
        == "static_source_inspection"
    )
    assert (
        verifier.REQUIRED_PRODUCT_HARDENING_CLASSIFICATIONS["product_policy_client_injection_rejected"]
        == "dynamically_executed"
    )
    assert (
        verifier.REQUIRED_PRODUCT_HARDENING_CLASSIFICATIONS["for_tests_helper_not_used_by_product"]
        == "static_source_inspection"
    )
    assert (
        verifier.REQUIRED_PRODUCT_HARDENING_CLASSIFICATIONS["expected_offline_dataset_digest_binding"]
        == "dynamically_executed"
    )


def test_frontier_integrity_records_git_blob_method(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verifier, "_git_quiet", lambda *args: True)
    monkeypatch.setattr(
        verifier,
        "_m1_receipt_blob_identity",
        lambda _commit: {
            "passed": True,
            "integrity_method": "git_blob_identity",
            "classification": "git_blob_identity",
        },
    )
    result = verifier._frontier_integrity("deadbeef")
    assert result["passed"] is True
    assert result["integrity_method"] == "git_blob_identity"
    assert result["frontier_scoring_freeze"]["passed"] is True
    assert "src/training_ground" in result["frontier_scoring_freeze"]["paths"]
