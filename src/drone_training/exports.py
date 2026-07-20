"""Explicit allowlisted serializers for Talon public exports."""

from __future__ import annotations

from typing import Any

from drone_decision_verifier.leak_detection import assert_public_safe


def public_record_summary(record: dict[str, Any]) -> dict[str, Any]:
    value = {
        key: record[key]
        for key in (
            "record_id",
            "kind",
            "status",
            "created_at",
            "ended_at",
            "record_digest",
            "application_commit",
            "progress",
            "model_id",
            "checkpoint_digest",
            "artifact_identity",
            "checkpoint_unavailable",
            "training_metrics",
            "training_history",
            "architecture",
            "parameter_count",
            "aggregate",
            "error_category",
            "dataset_digest",
            "trajectory_count",
            "offline_dataset_digest",
            "transition_count",
            "algorithm",
            "algorithm_version",
            "hardware",
            "models",
            "compatibility",
            "results",
            "aligned_instances",
            "policy_kind",
            "provider",
            "model",
            "prompt_version",
            "provider_adapter_version",
            "evaluation_config_digest",
        )
        if key in record
    }
    assert_public_safe(value)
    return value


def public_record_detail(record: dict[str, Any]) -> dict[str, Any]:
    value = public_record_summary(record)
    if record.get("kind") == "evaluation" and "episodes" in record:
        value["episodes"] = record["episodes"]
    assert_public_safe(value)
    return value


def public_evaluation_export(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("kind") != "evaluation" or record.get("status") != "completed":
        raise ValueError("only completed evaluations have a public reviewer export")
    payload = {
        "export_version": "talon.public-evaluation-export/2.0",
        "evaluation_id": record["record_id"],
        "status": record["status"],
        "record_digest": record["record_digest"],
        "application_commit": record.get("application_commit"),
        "checkpoint_digest": record.get("configuration", {}).get("checkpoint_digest"),
        "policy_kind": record.get("policy_kind") or record.get("configuration", {}).get("policy_kind"),
        "provider": record.get("provider") or record.get("configuration", {}).get("provider"),
        "model": record.get("model") or record.get("configuration", {}).get("model"),
        "prompt_version": record.get("prompt_version") or record.get("configuration", {}).get("prompt_version"),
        "evaluation_config_digest": record.get("evaluation_config_digest"),
        "aggregate": record.get("aggregate", {}),
        "episodes": record.get("episodes", []),
    }
    assert_public_safe(payload)
    return payload
