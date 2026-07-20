"""Held-out evaluation loop for external / scripted-external TALON policies."""

from __future__ import annotations

import time
from typing import Any, Callable

from drone_decision_ground.actions import ACTION_SCHEMA_VERSION
from drone_decision_ground.observation import PublicObservation
from drone_decision_ground.scenarios import ScenarioConfig
from drone_decision_verifier.hidden_scenarios import build_environment, scenario_instance_digest
from drone_decision_verifier.scoring import VERIFIER_VERSION

from .external_llm_client import ExternalPolicyClient
from .external_llm_schemas import (
    EXTERNAL_POLICY_SCHEMA_VERSION,
    PROMPT_VERSION,
    PROVIDER_ADAPTER_VERSION,
    ExternalLLMEvaluationCreate,
)
from .manifests import content_digest
from .replay import build_privileged_replay, build_public_replay
from .scripted import SafeScriptedPolicy


def evaluate_external_policy_episode(
    policy: ExternalPolicyClient,
    *,
    family: str,
    seed: int,
    partition: str,
    evaluation_run_id: str,
    environment_commit: str,
    verifier_commit: str,
    timeout_seconds: int,
    evaluation_config_digest: str,
    step_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run one held-out episode with an external or scripted-external policy."""

    if partition not in {"validation", "evaluation"}:
        raise ValueError("external evaluation requires validation or evaluation partition")
    config = ScenarioConfig(family_id=family, partition=partition)  # type: ignore[arg-type]
    instance_digest = scenario_instance_digest(config, seed)
    policy.profile_id = config.policy_profile
    policy.reset()
    started_at = time.monotonic()
    traces: list[dict[str, Any]] = []
    env = build_environment(config)
    raw_observation, _ = env.reset(seed=seed, options={"scenario_config": config})
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("external evaluation exceeded its execution deadline")
            observation = PublicObservation.model_validate(raw_observation)
            recommendation = policy.recommend(observation)
            trace = policy.last_trace
            if trace is not None:
                traces.append(
                    {
                        "prompt_input_digest": trace.prompt_input_digest,
                        "raw_response_digest": trace.raw_response_digest,
                        "parsed_response_digest": trace.parsed_response_digest,
                        "provider_latency_ms": trace.provider_latency_ms,
                        "schema_validation_ok": trace.schema_validation_ok,
                        "failure_category": trace.failure_category,
                        "selected_action": trace.selected_action,
                        "confidence": trace.confidence,
                        "evidence_refs": list(trace.evidence_refs),
                        "decision_summary": trace.decision_summary,
                        "provider_outcome": trace.provider_outcome,
                    }
                )
            raw_observation, _, terminated, truncated, _ = env.step(recommendation)
            if step_callback is not None:
                step_callback(env.transcript()[-1])
            if terminated or truncated:
                break
    finally:
        policy.close()
    result = env.grade()
    privileged = env.privileged_record()
    timeline = env.transcript()
    episode_eval_id = "talon_eval_" + content_digest(
        {
            "run": evaluation_run_id,
            "policy_kind": policy.policy_kind,
            "provider": policy.provider,
            "model": policy.model,
            "instance": instance_digest,
        }
    ).split(":", 1)[1][:24]
    provenance = {
        "policy_kind": policy.policy_kind,
        "provider": policy.provider,
        "model": policy.model,
        "provider_adapter_version": PROVIDER_ADAPTER_VERSION,
        "prompt_version": policy.prompt_version,
        "evaluation_config_digest": evaluation_config_digest,
    }
    public = {
        "schema_version": "talon.public-evaluation-episode/4.0",
        "evaluation_id": episode_eval_id,
        "checkpoint_digest": None,
        "environment_version": "talon.environment/2.0",
        "verifier_version": VERIFIER_VERSION,
        "algorithm": policy.policy_kind,
        "policy_kind": policy.policy_kind,
        "external_policy": provenance,
        "scenario_domain_digest": instance_digest,
        "external_policy_schema_version": EXTERNAL_POLICY_SCHEMA_VERSION,
        "elapsed_ms": round((time.monotonic() - started_at) * 1_000, 3),
        "result": result,
        "timeline": timeline,
    }
    replay = build_public_replay(public, decision_diagnostics=None, step_traces=traces)
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
            "schema_version": "talon.private-evaluation-episode/4.0",
            "manifest": {
                "evaluation_instance_digest": instance_digest,
                "environment_commit": environment_commit,
                "verifier_commit": verifier_commit,
                "verifier_version": VERIFIER_VERSION,
                "observation_schema_version": "talon.observation/2.0",
                "action_schema_version": ACTION_SCHEMA_VERSION,
                "policy_kind": policy.policy_kind,
                "provider": policy.provider,
                "model": policy.model,
                "prompt_version": policy.prompt_version or PROMPT_VERSION,
                "provider_adapter_version": PROVIDER_ADAPTER_VERSION,
                "evaluation_config_digest": evaluation_config_digest,
                "frozen_weights": False,
                "checkpoint_provenance": False,
            },
            "privileged_result": privileged,
            "privileged_replay": privileged_replay.model_dump(mode="json"),
            "step_traces": traces,
        },
    }


def evaluate_external_from_request(
    request: ExternalLLMEvaluationCreate | dict[str, Any],
    *,
    family: str,
    seed: int,
    evaluation_run_id: str,
    environment_commit: str = "unknown",
    verifier_commit: str = "unknown",
    step_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    config = (
        request
        if isinstance(request, ExternalLLMEvaluationCreate)
        else ExternalLLMEvaluationCreate.model_validate(request)
    )
    # Temporary profile; overwritten per scenario inside the episode helper.
    policy = ExternalPolicyClient.from_config(config, profile_id="uk_monitor_and_escalate")
    digest = policy.evaluation_config_digest(
        seed_start=config.seed_start,
        seed_count=config.seed_count,
        scenario_partition=config.scenario_partition,
    )
    return evaluate_external_policy_episode(
        policy,
        family=family,
        seed=seed,
        partition=config.scenario_partition,
        evaluation_run_id=evaluation_run_id,
        environment_commit=environment_commit,
        verifier_commit=verifier_commit,
        timeout_seconds=int(config.timeout_seconds),
        evaluation_config_digest=digest,
        step_callback=step_callback,
    )
