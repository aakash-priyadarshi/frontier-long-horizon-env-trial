"""Comparison metrics derived only from immutable authoritative run records."""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any

from .persistence import EvaluationStore


COMPATIBILITY_FIELDS = (
    ("environment_commit", "environment commit"),
    ("split", "split"),
    ("seed_set", "seed set"),
    ("max_steps", "maximum steps"),
    ("attempts", "attempts"),
    ("prompt_version", "prompt version"),
    ("budgets", "budgets"),
)


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def compare_batches(store: EvaluationStore, batch_ids: list[str]) -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    compatibility: list[dict[str, Any]] = []
    for batch_id in batch_ids:
        batch = store.get_batch(batch_id)
        if batch is None:
            continue
        runs = [run for run in batch.get("runs", []) if run.get("status") == "completed"]
        rewards = [float(run["authoritative_reward"]) for run in runs if isinstance(run.get("authoritative_reward"), (int, float))]
        actions = [float(run["action_count"]) for run in runs if isinstance(run.get("action_count"), (int, float))]
        tokens = [float((run.get("input_tokens") or 0) + (run.get("output_tokens") or 0)) for run in runs]
        latency = [float(run.get("elapsed_ms") or 0) for run in runs]
        costs = [float(run["estimated_cost"]) for run in runs if isinstance(run.get("estimated_cost"), (int, float))]
        success = sum(1 for value in rewards if value == 1.0)
        predicates = Counter(name for run in runs for name in run.get("failed_predicates") or [])
        outcomes = Counter(str(run.get("authoritative_verdict") or "unknown") for run in runs)
        provider_errors = sum(1 for run in batch.get("runs", []) if run.get("status") == "failed")
        truncations = sum(1 for run in runs if run.get("truncation_reason"))
        rewards_by_seed: dict[int, list[float]] = {}
        for run in runs:
            if isinstance(run.get("authoritative_reward"), (int, float)):
                rewards_by_seed.setdefault(int(run["seed"]), []).append(float(run["authoritative_reward"]))
        repeated_seeds = [values for values in rewards_by_seed.values() if len(values) > 1]
        consistency = (
            sum(1 for values in repeated_seeds if len(set(values)) == 1) / len(repeated_seeds)
            if repeated_seeds else None
        )
        group = {
            "batch_id": batch_id, "provider": batch["provider"], "model": batch["model"],
            "environment_commit": batch["environment_commit"], "split": batch["split"],
            "run_count": len(runs), "strict_success_rate": success / len(rewards) if rewards else None,
            "average_reward": statistics.fmean(rewards) if rewards else None, "median_reward": _median(rewards),
            "average_actions": statistics.fmean(actions) if actions else None, "median_actions": _median(actions),
            "average_token_usage": statistics.fmean(tokens) if tokens else None,
            "average_latency_ms": statistics.fmean(latency) if latency else None,
            "estimated_total_cost": sum(costs) if costs else None,
            "cost_per_success": sum(costs) / success if costs and success else None,
            "truncation_rate": truncations / len(runs) if runs else None,
            "provider_error_rate": provider_errors / batch["total_runs"] if batch["total_runs"] else None,
            "consistency_across_attempts": consistency,
            "failed_predicate_frequency": dict(predicates), "outcome_distribution": dict(outcomes),
            "results_by_seed": [{"seed": run.get("seed"), "attempt": run.get("attempt"), "reward": run.get("authoritative_reward"), "actions": run.get("action_count"), "input_tokens": run.get("input_tokens") or 0, "output_tokens": run.get("output_tokens") or 0, "tokens": (run.get("input_tokens") or 0) + (run.get("output_tokens") or 0), "latency_ms": run.get("elapsed_ms"), "cost": run.get("estimated_cost")} for run in runs],
        }
        groups.append(group)
        config = batch["configuration"]
        compatibility.append({
            "environment_commit": batch["environment_commit"], "split": batch["split"],
            "seed_set": list(range(batch["seed_start"], batch["seed_start"] + batch["seed_count"])),
            "max_steps": config["limits"]["max_steps"], "attempts": batch["attempts"],
            "prompt_version": next((run.get("prompt_version") for run in runs), None),
            "budgets": {k: config["limits"].get(k) for k in ("input_token_budget", "output_token_budget", "cost_budget", "wall_clock_seconds")},
        })
    warnings: list[str] = []
    if len(compatibility) > 1:
        for key, label in COMPATIBILITY_FIELDS:
            normalized = {repr(item.get(key)) for item in compatibility}
            if len(normalized) > 1:
                warnings.append(f"Compared evaluations differ in {label}.")
    return {"groups": groups, "compatibility_warnings": warnings, "fair_comparison": not warnings}
