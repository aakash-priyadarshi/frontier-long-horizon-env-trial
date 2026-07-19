"""Frozen, overlap-safe evaluation of Talon discrete CQL checkpoints."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from drone_decision_ground.observation import PublicObservation
from drone_decision_ground.scenarios import ScenarioConfig
from drone_decision_verifier.hidden_scenarios import build_environment, scenario_instance_digest
from drone_decision_verifier.scoring import VERIFIER_VERSION

from .bindings import (
    TrustedCheckpointBinding,
    require_dataset_bindings,
    resolve_bound_checkpoint,
)
from .manifests import content_digest
from .offline_checkpoints import load_offline_checkpoint
from .offline_policy_isolation import IsolatedCQLPolicyClient
from .replay import build_privileged_replay, build_public_replay
from .scripted import SafeScriptedPolicy


def _resolve_evaluation_checkpoint(
    checkpoint: Path | None,
    *,
    binding: TrustedCheckpointBinding | None,
    expected_checkpoint_digest: str | None,
    private_root: Path | None,
) -> tuple[Path, str, TrustedCheckpointBinding | None]:
    if binding is not None:
        if private_root is None:
            raise ValueError("private_root is required when evaluating a trusted binding")
        resolved = resolve_bound_checkpoint(private_root, binding, require_digest_match=True)
        return resolved, binding.trusted_digest, binding
    if checkpoint is None or expected_checkpoint_digest is None:
        raise ValueError("checkpoint path and trusted digest are required without a binding")
    if not isinstance(expected_checkpoint_digest, str) or not expected_checkpoint_digest.startswith("sha256:"):
        raise ValueError("offline checkpoint digest is missing or malformed")
    return Path(checkpoint), expected_checkpoint_digest, None


def _resolve_dataset_expectations(
    binding: TrustedCheckpointBinding | None,
    *,
    expected_offline_dataset_digest: str | None,
    expected_source_dataset_digest: str | None,
) -> tuple[str | None, str | None]:
    if binding is not None:
        # Product bindings (DB or otherwise) always require both digests before load.
        return require_dataset_bindings(binding)
    if expected_offline_dataset_digest is None and expected_source_dataset_digest is None:
        return None, None
    if expected_offline_dataset_digest is None or expected_source_dataset_digest is None:
        raise ValueError("offline and source dataset digests must both be provided")
    return expected_offline_dataset_digest, expected_source_dataset_digest


def _evaluate_offline_checkpoint_impl(
    checkpoint: Path,
    *,
    family: str,
    seed: int,
    partition: str,
    expected_checkpoint_digest: str,
    environment_commit: str,
    verifier_commit: str,
    timeout_seconds: int,
    policy_client: Any | None,
    step_callback: Callable[[dict[str, Any]], None] | None,
    expected_offline_dataset_digest: str | None = None,
    expected_source_dataset_digest: str | None = None,
) -> dict[str, Any]:
    if partition not in {"validation", "evaluation"}:
        raise ValueError("frozen CQL evaluation requires validation or evaluation partition")
    config = ScenarioConfig(family_id=family, partition=partition)  # type: ignore[arg-type]
    instance_digest = scenario_instance_digest(config, seed)
    _, _, metadata = load_offline_checkpoint(
        checkpoint,
        expected_digest=expected_checkpoint_digest,
        expected_offline_dataset_digest=expected_offline_dataset_digest,
        expected_source_dataset_digest=expected_source_dataset_digest,
    )
    if instance_digest in set(metadata["training_instance_digests"]):
        raise ValueError("evaluation instance overlaps checkpoint training instances")
    owned = policy_client is None
    if policy_client is None:
        policy_client = IsolatedCQLPolicyClient(
            checkpoint,
            expected_digest=expected_checkpoint_digest,
            expected_offline_dataset_digest=expected_offline_dataset_digest,
            expected_source_dataset_digest=expected_source_dataset_digest,
            timeout_seconds=min(float(timeout_seconds), 10.0),
            profile_id=config.policy_profile,
        )
    else:
        # Test-only injection: the client must already be bound to this digest.
        client_digest = getattr(policy_client, "expected_digest", None)
        if client_digest is not None and not (
            isinstance(client_digest, str) and client_digest == expected_checkpoint_digest
        ):
            raise ValueError("injected policy client digest does not match the verified checkpoint")
        policy_client.profile_id = config.policy_profile
    policy_client.reset()
    started_at = time.monotonic()
    diagnostics: list[dict[str, Any]] = []
    env = build_environment(config)
    raw_observation, _ = env.reset(seed=seed, options={"scenario_config": config})
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("offline evaluation exceeded its execution deadline")
            recommendation = policy_client.recommend(PublicObservation.model_validate(raw_observation))
            diagnostics.append(dict(policy_client.last_diagnostics))
            raw_observation, _, terminated, truncated, _ = env.step(recommendation)
            if step_callback is not None:
                step_callback(env.transcript()[-1])
            if terminated or truncated:
                break
    finally:
        if owned:
            policy_client.close()
    result = env.grade()
    privileged = env.privileged_record()
    timeline = env.transcript()
    evaluation_id = "talon_eval_" + content_digest({
        "checkpoint": metadata["checkpoint_digest"],
        "instance": instance_digest,
        "algorithm": metadata["algorithm_version"],
    }).split(":", 1)[1][:24]
    public = {
        "schema_version": "talon.public-evaluation-episode/3.0",
        "evaluation_id": evaluation_id,
        "checkpoint_digest": metadata["checkpoint_digest"],
        "environment_version": "talon.environment/2.0",
        "verifier_version": VERIFIER_VERSION,
        "algorithm": "discrete_cql",
        "elapsed_ms": round((time.monotonic() - started_at) * 1_000, 3),
        "result": result,
        "timeline": timeline,
    }
    replay = build_public_replay(public, decision_diagnostics=diagnostics)
    expert_policy = SafeScriptedPolicy()
    expert_policy.reset()
    private_targets = [
        {
            "operational_reward": float(result["score"]) if index == len(timeline) - 1 else 0.0,
            "safety_cost": 1.0 if step["gate"]["violation_codes"] else 0.0,
            "expert_action": expert_policy.recommend(
                PublicObservation.model_validate(step["observation"])
            ).recommended_action.value,
        }
        for index, step in enumerate(timeline)
    ]
    privileged_replay = build_privileged_replay(
        replay,
        privileged_record=privileged,
        private_step_targets=private_targets,
    )
    return {
        "public": {**public, "replay": replay.model_dump(mode="json")},
        "private": {
            "schema_version": "talon.private-evaluation-episode/3.0",
            "manifest": {
                "model_checkpoint_digest": metadata["checkpoint_digest"],
                "offline_dataset_digest": metadata["offline_dataset_digest"],
                "evaluation_instance_digest": instance_digest,
                "environment_commit": environment_commit,
                "verifier_commit": verifier_commit,
                "frozen_weights": True,
                "optimizer_steps": 0,
            },
            "privileged_result": privileged,
            "privileged_replay": privileged_replay.model_dump(mode="json"),
            "decision_diagnostics": diagnostics,
        },
    }


def evaluate_offline_checkpoint(
    checkpoint: Path | None = None,
    *,
    family: str,
    seed: int,
    partition: str = "evaluation",
    expected_checkpoint_digest: str | None = None,
    binding: TrustedCheckpointBinding | None = None,
    private_root: Path | None = None,
    expected_offline_dataset_digest: str | None = None,
    expected_source_dataset_digest: str | None = None,
    environment_commit: str = "unknown",
    verifier_commit: str = "unknown",
    timeout_seconds: int = 30,
    step_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Evaluate a discrete CQL checkpoint with the isolated production policy client.

    Product API/worker paths must supply a ``TrustedCheckpointBinding`` (preferred)
    or a digest that originated from an immutable completed-run record. A foreign
    ``policy_client`` cannot be injected through this public entry point.

    When a binding is provided (including ``BindingSource.IMMUTABLE_DB_RECORD``),
    both offline and source dataset digests are required before checkpoint load.
    CLI operators may pass both digests explicitly when they have verified binding.
    """

    resolved, digest, bound = _resolve_evaluation_checkpoint(
        checkpoint,
        binding=binding,
        expected_checkpoint_digest=expected_checkpoint_digest,
        private_root=private_root,
    )
    offline_digest, source_digest = _resolve_dataset_expectations(
        bound,
        expected_offline_dataset_digest=expected_offline_dataset_digest,
        expected_source_dataset_digest=expected_source_dataset_digest,
    )
    return _evaluate_offline_checkpoint_impl(
        resolved,
        family=family,
        seed=seed,
        partition=partition,
        expected_checkpoint_digest=digest,
        environment_commit=environment_commit,
        verifier_commit=verifier_commit,
        timeout_seconds=timeout_seconds,
        policy_client=None,
        step_callback=step_callback,
        expected_offline_dataset_digest=offline_digest,
        expected_source_dataset_digest=source_digest,
    )


def evaluate_offline_checkpoint_for_tests(
    checkpoint: Path,
    *,
    family: str,
    seed: int,
    partition: str = "evaluation",
    expected_checkpoint_digest: str,
    environment_commit: str = "unknown",
    verifier_commit: str = "unknown",
    timeout_seconds: int = 30,
    policy_client: Any,
    step_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Test-only helper that injects a policy client. Not used by API or workers."""

    return _evaluate_offline_checkpoint_impl(
        Path(checkpoint),
        family=family,
        seed=seed,
        partition=partition,
        expected_checkpoint_digest=expected_checkpoint_digest,
        environment_commit=environment_commit,
        verifier_commit=verifier_commit,
        timeout_seconds=timeout_seconds,
        policy_client=policy_client,
        step_callback=step_callback,
    )
