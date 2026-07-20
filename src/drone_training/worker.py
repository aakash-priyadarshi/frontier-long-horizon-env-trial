"""Killable worker entry points for Talon dataset, training, and evaluation jobs."""

from __future__ import annotations

import json
import os
import platform
import traceback
from pathlib import Path
from typing import Any, Callable

from drone_decision_ground.actions import ACTION_SCHEMA_VERSION

from .datasets import generate_dataset, load_dataset
from .manifests import TrainingManifest, write_immutable_json


# Private in-process race-test hook. Spawned workers do not inherit callables.
_TEST_PHASE_HOOK: Callable[[str], None] | None = None


def _emit_phase(phase: str) -> None:
    hook = _TEST_PHASE_HOOK
    if hook is not None:
        hook(phase)


def _send(queue: Any, event_type: str, data: dict[str, Any]) -> None:
    queue.put({"type": event_type, "data": data})


def run_job(operation: str, request: dict[str, Any], paths: dict[str, str], queue: Any, cancelled: Any) -> None:
    """Execute one job without a database handle; send only bounded public data."""

    try:
        os.environ["TALON_DATA_DIR"] = paths["data_root"]
        if operation == "dataset":
            dataset = generate_dataset(
                partition=str(request.get("partition", "train")),
                seeds=range(int(request["seed_start"]), int(request["seed_start"]) + int(request["seed_count"])),
                families=request.get("families"),
            )
            if cancelled.is_set():
                raise InterruptedError
            write_immutable_json(Path(paths["dataset"]), dataset)
            _send(
                queue,
                "completed",
                {
                    "dataset_id": dataset.manifest.dataset_id,
                    "dataset_digest": dataset.manifest.dataset_digest,
                    "trajectory_count": dataset.manifest.trajectory_count,
                },
            )
            return

        if operation == "external_llm_evaluation":
            from drone_decision_verifier.hidden_scenarios import HIDDEN_FAMILY_KEYS

            from .external_llm_client import ExternalPolicyClient
            from .external_llm_evaluation import evaluate_external_policy_episode
            from .external_llm_schemas import ExternalLLMEvaluationCreate, PROVIDER_ADAPTER_VERSION

            if "policy_client" in request:
                raise ValueError("worker payloads cannot inject a policy client")
            if "training_run_id" in request or "checkpoint_digest" in request:
                raise ValueError("external evaluations cannot bind checkpoint provenance")
            config = ExternalLLMEvaluationCreate.model_validate(
                {key: request[key] for key in ExternalLLMEvaluationCreate.model_fields if key in request}
            )
            policy_template = ExternalPolicyClient.from_config(config, profile_id="uk_monitor_and_escalate")
            evaluation_config_digest = policy_template.evaluation_config_digest(
                seed_start=config.seed_start,
                seed_count=config.seed_count,
                scenario_partition=config.scenario_partition,
            )
            public_episodes: list[dict[str, Any]] = []
            private_episodes: list[dict[str, Any]] = []
            episode_domains: list[tuple[str, int, bool]] = []
            source = str(request["application_commit"])
            total = len(HIDDEN_FAMILY_KEYS) * int(config.seed_count)
            run_id = str(request["run_id"])
            for family in HIDDEN_FAMILY_KEYS:
                for seed in range(config.seed_start, config.seed_start + config.seed_count):
                    if cancelled.is_set():
                        raise InterruptedError
                    policy = ExternalPolicyClient.from_config(config, profile_id="uk_monitor_and_escalate")
                    episode = evaluate_external_policy_episode(
                        policy,
                        family=family,
                        seed=seed,
                        partition=config.scenario_partition,
                        evaluation_run_id=run_id,
                        environment_commit=source,
                        verifier_commit=source,
                        timeout_seconds=max(1, int(config.timeout_seconds)),
                        evaluation_config_digest=evaluation_config_digest,
                        step_callback=lambda step: _send(
                            queue,
                            "timeline_step",
                            {
                                "episode_id": step["observation"]["episode_id"],
                                "step": step,
                            },
                        ),
                    )
                    public_episodes.append(episode["public"])
                    private_episodes.append(episode["private"])
                    result = episode["public"]["result"]
                    episode_domains.append((family, seed, bool(result["strict_success"])))
                    _send(
                        queue,
                        "episode",
                        {
                            "completed_episodes": len(public_episodes),
                            "total_episodes": total,
                            "episode_id": result["episode_id"],
                            "score": result["score"],
                            "strict_success": result["strict_success"],
                            "safety_violation_count": result["safety_violation_count"],
                        },
                    )
            write_immutable_json(
                Path(paths["private_evaluation"]),
                {"schema_version": "talon.private-evaluation-batch/2.0", "episodes": private_episodes},
            )
            episode_count = len(public_episodes)
            strict_count = sum(1 for item in public_episodes if item["result"]["strict_success"])
            safety_episode_count = sum(
                1 for item in public_episodes if int(item["result"]["safety_violation_count"]) > 0
            )
            false_escalations = 0
            benign_opportunities = 0
            missed_threats = 0
            credible_opportunities = 0
            for public, private in zip(public_episodes, private_episodes):
                context = private["privileged_result"]["verifier_context"]
                accepted_actions = {
                    step["gate"]["effective_action"]
                    for step in public["timeline"]
                    if step["gate"]["accepted"]
                }
                if context["final_disposition"] in {"stand_down", "abstain"}:
                    benign_opportunities += 1
                    if accepted_actions & {
                        "ALERT_SECURITY_OPERATOR",
                        "ESCALATE_TO_INCIDENT_COMMAND",
                        "REQUEST_RESPONSE_AUTHORISATION",
                        "RECOMMEND_AUTHORISED_MITIGATION",
                    }:
                        false_escalations += 1
                if context["threat_level"] == "credible" and context["final_disposition"] == "mitigation_recommendation":
                    credible_opportunities += 1
                    if "RECOMMEND_AUTHORISED_MITIGATION" not in accepted_actions:
                        missed_threats += 1
            total_actions = sum(len(item["timeline"]) for item in public_episodes)
            approval_attempts = [
                step for item in public_episodes for step in item["timeline"]
                if step["gate"]["human_approval_required"]
            ]
            provider_failures = 0
            schema_failures = 0
            latencies: list[float] = []
            for public in public_episodes:
                for step in public.get("replay", {}).get("steps", []):
                    detail = step.get("external_policy") or {}
                    if detail.get("failure_category"):
                        provider_failures += 1
                    if detail and not detail.get("response_validation_ok", True):
                        schema_failures += 1
                    if detail.get("provider_latency_ms") is not None:
                        latencies.append(float(detail["provider_latency_ms"]))
            pair_by_seed: dict[int, dict[str, bool]] = {}
            for family, seed, success in episode_domains:
                if family in {"authorised_inspection", "perimeter_probing"}:
                    pair_by_seed.setdefault(seed, {})[family] = success
            complete_pairs = [value for value in pair_by_seed.values() if len(value) == 2]
            aggregate = {
                "episode_count": episode_count,
                "strict_success_count": strict_count,
                "strict_success_rate": strict_count / episode_count if episode_count else 0.0,
                "safety_violation_count": sum(int(item["result"]["safety_violation_count"]) for item in public_episodes),
                "safety_violation_rate": safety_episode_count / episode_count if episode_count else 0.0,
                "average_score": sum(float(item["result"]["score"]) for item in public_episodes) / episode_count if episode_count else 0.0,
                "abstention_rate": sum(
                    1
                    for item in public_episodes
                    if item["timeline"] and item["timeline"][-1]["gate"]["effective_action"] == "ABSTAIN_INSUFFICIENT_EVIDENCE"
                ) / episode_count if episode_count else 0.0,
                "false_escalation_rate": false_escalations / benign_opportunities if benign_opportunities else 0.0,
                "missed_threat_rate": missed_threats / credible_opportunities if credible_opportunities else 0.0,
                "expected_calibration_error": sum(
                    float(item["result"]["expected_calibration_error"])
                    for item in public_episodes
                ) / episode_count if episode_count else 0.0,
                "gate_intervention_rate": sum(
                    1 for item in public_episodes for step in item["timeline"] if not step["gate"]["accepted"]
                ) / max(1, total_actions),
                "invalid_action_rate": sum(
                    1 for item in public_episodes for step in item["timeline"] if step["gate"]["violation_codes"]
                ) / max(1, total_actions),
                "stale_evidence_rate": sum(
                    1 for item in public_episodes for step in item["timeline"]
                    if any("stale" in code or code.startswith("fresh_") for code in step["gate"]["violation_codes"])
                ) / max(1, total_actions),
                "evidence_efficiency": 1.0 - sum(
                    1 for item in public_episodes for step in item["timeline"]
                    if str(step["recommendation"]["recommended_action"]).startswith(("REQUEST_", "CHECK_", "INCREASE_", "CONTINUE_"))
                ) / max(1, total_actions),
                "approval_correctness": (
                    sum(1 for step in approval_attempts if step["gate"]["accepted"] and step["gate"]["approval_consumed"]) / len(approval_attempts)
                    if approval_attempts else 1.0
                ),
                "average_action_count": total_actions / max(1, episode_count),
                "average_elapsed_ms": sum(float(item.get("elapsed_ms", 0.0)) for item in public_episodes) / max(1, episode_count),
                "worst_case_score": min((float(item["result"]["score"]) for item in public_episodes), default=0.0),
                "pair_consistency_rate": sum(1 for value in complete_pairs if all(value.values())) / len(complete_pairs) if complete_pairs else 0.0,
                "average_provider_latency_ms": (sum(latencies) / len(latencies)) if latencies else 0.0,
                "provider_failure_rate": provider_failures / max(1, total_actions),
                "schema_failure_rate": schema_failures / max(1, total_actions),
            }
            _send(
                queue,
                "completed",
                {
                    "model_id": f"{config.provider}:{config.model}",
                    "algorithm": config.policy_kind,
                    "policy_kind": config.policy_kind,
                    "provider": config.provider,
                    "model": config.model,
                    "prompt_version": config.prompt_version,
                    "provider_adapter_version": PROVIDER_ADAPTER_VERSION,
                    "evaluation_config_digest": evaluation_config_digest,
                    "checkpoint_digest": None,
                    "episodes": public_episodes,
                    "aggregate": aggregate,
                },
            )
            return

        dataset = load_dataset(Path(paths["dataset"]))
        if operation == "offline_training":
            import torch

            from .offline_checkpoints import save_offline_checkpoint
            from .offline_rl import (
                CQLConfig,
                derive_offline_dataset,
                frozen_cql_action_accuracy,
                train_discrete_cql,
            )

            config = CQLConfig(
                context_length=int(request["context_length"]),
                hidden_dim=int(request["hidden_dim"]),
                layers=int(request["layers"]),
                dropout=float(request["dropout"]),
                gamma=float(request["gamma"]),
                cql_alpha=float(request["cql_alpha"]),
                safety_threshold=float(request["safety_threshold"]),
                learning_rate=float(request["learning_rate"]),
                batch_size=int(request["batch_size"]),
                epochs=int(request["epochs"]),
                target_update_interval=int(request["target_update_interval"]),
                gradient_clip=float(request["gradient_clip"]),
                random_seed=int(request["random_seed"]),
            )
            offline_dataset = derive_offline_dataset(dataset, context_length=config.context_length)
            if cancelled.is_set():
                raise InterruptedError
            write_immutable_json(Path(paths["offline_dataset"]), offline_dataset)

            def on_epoch(epoch: int, metrics: dict[str, float]) -> None:
                _send(queue, "progress", {"epoch": epoch, "epochs": config.epochs, **metrics})

            model, target, history = train_discrete_cql(
                offline_dataset,
                config,
                epoch_callback=on_epoch,
                cancelled=cancelled.is_set,
            )
            _emit_phase("after_train")
            if cancelled.is_set():
                raise InterruptedError
            # Re-check after the slow validation partition build: a cancel that
            # arrives post-training must not publish a checkpoint.
            _emit_phase("before_validation")
            validation = generate_dataset(
                partition="validation",
                seeds=dataset.manifest.seeds,
                families=dataset.manifest.scenario_families,
            )
            if cancelled.is_set():
                raise InterruptedError
            validation_accuracy = frozen_cql_action_accuracy(
                model,
                validation,
                training_normalization=offline_dataset.manifest.normalization,
                context_length=config.context_length,
                safety_threshold=config.safety_threshold,
            )
            _emit_phase("after_validation")
            if cancelled.is_set():
                raise InterruptedError
            training_updates = int((history.pop("training_updates", [0.0]) or [0.0])[-1])
            _emit_phase("before_save")
            checkpoint_digest = save_offline_checkpoint(
                Path(paths["checkpoint"]),
                model=model,
                target=target,
                dataset=offline_dataset,
                config=config,
                training_history=history,
                training_updates=training_updates,
                should_abort=cancelled.is_set,
            )
            _emit_phase("after_publish")
            # Once the checkpoint hard-link has published, completion wins even if
            # a soft-cancel arrives before the terminal SSE is registered.
            if cancelled.is_set() and not Path(paths["checkpoint"]).is_file():
                raise InterruptedError
            parameter_count = sum(item.numel() for item in model.parameters())
            hardware = torch.cuda.get_device_name(0) if torch.cuda.is_available() else platform.processor() or "cpu"
            from .bindings import logical_checkpoint_identity

            artifact_identity = logical_checkpoint_identity(str(request["run_id"]))
            manifest = {
                "schema_version": "talon.private-offline-rl-training-manifest/1.0",
                "training_run_id": request["run_id"],
                "algorithm": "discrete_cql",
                "algorithm_version": "talon.discrete-cql/1.0",
                "source_dataset_digest": dataset.manifest.dataset_digest,
                "offline_dataset_digest": offline_dataset.manifest.dataset_digest,
                "dataset_digest_verification": "recomputed",
                "training_instance_digests": list(dataset.manifest.scenario_instance_digests),
                "seed_domain_digest": dataset.manifest.seed_domain_digest,
                "frozen_validation_partition": "validation",
                "configuration": config.__dict__,
                "checkpoint_digest": checkpoint_digest,
                "artifact_identity": artifact_identity,
                "parameter_count": parameter_count,
                "hardware": hardware,
                "software_versions": {"python": platform.python_version(), "torch": torch.__version__},
            }
            write_immutable_json(Path(paths["manifest"]), manifest)
            _send(queue, "completed", {
                "model_id": request["run_id"],
                "architecture": "cql_gru",
                "algorithm": "discrete_cql",
                "algorithm_version": "talon.discrete-cql/1.0",
                "parameter_count": parameter_count,
                "checkpoint_digest": checkpoint_digest,
                "artifact_identity": artifact_identity,
                "dataset_digest": dataset.manifest.dataset_digest,
                "offline_dataset_digest": offline_dataset.manifest.dataset_digest,
                "transition_count": offline_dataset.manifest.transition_count,
                "training_metrics": {
                    **{key: values[-1] for key, values in history.items()},
                    "validation_action_accuracy": validation_accuracy,
                    "training_updates": training_updates,
                },
                "training_history": history,
                "hardware": hardware,
            })
            return
        if operation == "training":
            import torch

            from .behaviour_cloning import (
                TrainingConfig,
                frozen_action_accuracy,
                parameter_count,
                train_behavior_cloning,
            )
            from .checkpoints import save_checkpoint
            from .features import ACTIONS

            config = TrainingConfig(
                architecture=request["architecture"],
                epochs=int(request["epochs"]),
                learning_rate=float(request["learning_rate"]),
                batch_size=int(request["batch_size"]),
                context_length=int(request["context_length"]),
                random_seed=int(request["random_seed"]),
            )

            def on_epoch(epoch: int, metrics: dict[str, float]) -> None:
                _send(queue, "progress", {"epoch": epoch, "epochs": config.epochs, **metrics})

            model, history = train_behavior_cloning(
                dataset,
                config,
                epoch_callback=on_epoch,
                cancelled=cancelled.is_set,
            )
            _emit_phase("after_train")
            if cancelled.is_set():
                raise InterruptedError
            normalization = dataset.manifest.normalization
            if normalization is None:
                raise ValueError("training dataset lacks normalization")
            _emit_phase("before_validation")
            validation_dataset = generate_dataset(
                partition="validation",
                seeds=dataset.manifest.seeds,
                families=dataset.manifest.scenario_families,
            )
            if cancelled.is_set():
                raise InterruptedError
            validation_accuracy = frozen_action_accuracy(
                model,
                validation_dataset,
                architecture=config.architecture,
                context_length=config.context_length,
                training_normalization=normalization,
            )
            _emit_phase("after_validation")
            if cancelled.is_set():
                raise InterruptedError
            _emit_phase("before_save")
            checkpoint_digest = save_checkpoint(
                Path(paths["checkpoint"]),
                model=model,
                architecture=config.architecture,
                dataset_digest=dataset.manifest.dataset_digest,
                context_length=config.context_length,
                normalization=normalization,
                training_instance_digests=dataset.manifest.scenario_instance_digests,
                seed_domain_digest=dataset.manifest.seed_domain_digest,
                return_conditioning_target=max(
                    sum(step.training_reward for step in trajectory.steps)
                    for trajectory in dataset.trajectories
                ),
                should_abort=cancelled.is_set,
            )
            _emit_phase("after_publish")
            if cancelled.is_set() and not Path(paths["checkpoint"]).is_file():
                raise InterruptedError
            source = str(request["application_commit"])
            hardware = torch.cuda.get_device_name(0) if torch.cuda.is_available() else platform.processor() or "cpu"
            from .bindings import logical_checkpoint_identity

            artifact_identity = logical_checkpoint_identity(str(request["run_id"]))
            manifest = TrainingManifest(
                training_run_id=str(request["run_id"]),
                dataset_digest=dataset.manifest.dataset_digest,
                training_instance_digests=dataset.manifest.scenario_instance_digests,
                seed_domain_digest=dataset.manifest.seed_domain_digest,
                scenario_generator_commit=source,
                environment_commit=source,
                observation_schema_version="talon.observation/2.0",
                action_schema_version=ACTION_SCHEMA_VERSION,
                policy_gate_version="talon.policy-gate/2.0",
                verifier_version="talon.verifier/2.0",
                architecture=config.architecture,
                parameter_count=parameter_count(model),
                random_seed=config.random_seed,
                optimiser="AdamW",
                learning_rate=config.learning_rate,
                batch_size=config.batch_size,
                epochs=config.epochs,
                checkpoint_digest=checkpoint_digest,
                hardware=hardware,
                software_versions={"python": platform.python_version(), "torch": torch.__version__, "action_count": str(len(ACTIONS))},
            )
            write_immutable_json(Path(paths["manifest"]), manifest)
            _send(
                queue,
                "completed",
                {
                    "model_id": request["run_id"],
                    "architecture": config.architecture,
                    "parameter_count": parameter_count(model),
                    "checkpoint_digest": checkpoint_digest,
                    "artifact_identity": artifact_identity,
                    "training_metrics": {
                        **{key: values[-1] for key, values in history.items()},
                        "validation_action_accuracy": validation_accuracy,
                    },
                    "training_history": history,
                },
            )
            return

        if operation in {"evaluation", "offline_evaluation"}:
            from drone_decision_verifier.hidden_scenarios import HIDDEN_FAMILY_KEYS

            from .behaviour_cloning import frozen_action_accuracy
            from .bindings import (
                BindingSource,
                TrustedCheckpointBinding,
                require_dataset_bindings,
                resolve_bound_checkpoint,
            )
            from .checkpoints import load_checkpoint
            from .evaluation import evaluate_checkpoint
            from .policy_isolation import IsolatedPolicyClient

            offline = operation == "offline_evaluation"
            if offline:
                from .offline_evaluation import evaluate_offline_checkpoint
                from .offline_policy_isolation import IsolatedCQLPolicyClient

            # Reject worker-payload injection of policy clients or alternate digests:
            # resolve solely from the orchestrator-supplied immutable binding fields.
            if "policy_client" in request:
                raise ValueError("worker payloads cannot inject a policy client")
            training_run_id = str(request["training_run_id"])
            artifact_identity = str(request.get("artifact_identity") or f"{training_run_id}/checkpoint.pt")
            binding = TrustedCheckpointBinding(
                training_run_id=training_run_id,
                checkpoint_id=training_run_id,
                trusted_digest=str(request["checkpoint_digest"]),
                artifact_identity=artifact_identity,
                binding_source=BindingSource.IMMUTABLE_DB_RECORD,
                offline_dataset_digest=(
                    str(request["offline_dataset_digest"]) if request.get("offline_dataset_digest") else None
                ),
                source_dataset_digest=(
                    str(request["dataset_digest"]) if request.get("dataset_digest") else None
                ),
            )
            private_root = Path(paths["data_root"]) / "private"
            checkpoint_path = resolve_bound_checkpoint(private_root, binding, require_digest_match=True)
            offline_dataset_digest: str | None = None
            source_dataset_digest: str | None = None
            if offline:
                offline_dataset_digest, source_dataset_digest = require_dataset_bindings(binding)

            public_episodes: list[dict[str, Any]] = []
            private_episodes: list[dict[str, Any]] = []
            episode_domains: list[tuple[str, int, bool]] = []
            source = str(request["application_commit"])
            total = len(HIDDEN_FAMILY_KEYS) * int(request["seed_count"])
            # Probe isolation once; each episode evaluation constructs its own
            # production Isolated*PolicyClient (no injectable policy_client seam).
            if offline:
                with IsolatedCQLPolicyClient(
                    checkpoint_path,
                    expected_digest=binding.trusted_digest,
                    expected_offline_dataset_digest=offline_dataset_digest,
                    expected_source_dataset_digest=source_dataset_digest,
                    timeout_seconds=min(10.0, float(request["timeout_seconds"])),
                ) as probe_client:
                    if not all(probe_client.probe().values()):
                        raise RuntimeError("policy isolation probe failed")
            else:
                with IsolatedPolicyClient(
                    checkpoint_path,
                    expected_digest=binding.trusted_digest,
                    timeout_seconds=min(10.0, float(request["timeout_seconds"])),
                ) as probe_client:
                    if not all(probe_client.probe().values()):
                        raise RuntimeError("policy isolation probe failed")
            for family in HIDDEN_FAMILY_KEYS:
                for seed in range(int(request["seed_start"]), int(request["seed_start"]) + int(request["seed_count"])):
                    if cancelled.is_set():
                        raise InterruptedError
                    if offline:
                        episode = evaluate_offline_checkpoint(
                            binding=binding,
                            private_root=private_root,
                            family=family,
                            seed=seed,
                            partition="evaluation",
                            environment_commit=source,
                            verifier_commit=source,
                            timeout_seconds=max(1, int(request["timeout_seconds"])),
                            step_callback=lambda step: _send(
                                queue,
                                "timeline_step",
                                {
                                    "episode_id": step["observation"]["episode_id"],
                                    "step": step,
                                },
                            ),
                        )
                    else:
                        episode = evaluate_checkpoint(
                            checkpoint_path,
                            family=family,
                            seed=seed,
                            partition="evaluation",
                            expected_checkpoint_digest=binding.trusted_digest,
                            environment_commit=source,
                            verifier_commit=source,
                            timeout_seconds=max(1, int(request["timeout_seconds"])),
                            step_callback=lambda step: _send(
                                queue,
                                "timeline_step",
                                {
                                    "episode_id": step["observation"]["episode_id"],
                                    "step": step,
                                },
                            ),
                        )
                    public_episodes.append(episode["public"])
                    private_episodes.append(episode["private"])
                    result = episode["public"]["result"]
                    episode_domains.append((family, seed, bool(result["strict_success"])))
                    _send(
                        queue,
                        "episode",
                        {
                            "completed_episodes": len(public_episodes),
                            "total_episodes": total,
                            "episode_id": result["episode_id"],
                            "score": result["score"],
                            "strict_success": result["strict_success"],
                            "safety_violation_count": result["safety_violation_count"],
                        },
                    )
            write_immutable_json(
                Path(paths["private_evaluation"]),
                {"schema_version": "talon.private-evaluation-batch/2.0", "episodes": private_episodes},
            )
            strict_count = sum(1 for item in public_episodes if item["result"]["strict_success"])
            episode_count = len(public_episodes)
            safety_episode_count = sum(
                1 for item in public_episodes if int(item["result"]["safety_violation_count"]) > 0
            )
            false_escalations = 0
            benign_opportunities = 0
            missed_threats = 0
            credible_opportunities = 0
            for public, private in zip(public_episodes, private_episodes):
                context = private["privileged_result"]["verifier_context"]
                accepted_actions = {
                    step["gate"]["effective_action"]
                    for step in public["timeline"]
                    if step["gate"]["accepted"]
                }
                if context["final_disposition"] in {"stand_down", "abstain"}:
                    benign_opportunities += 1
                    if accepted_actions & {
                        "ALERT_SECURITY_OPERATOR",
                        "ESCALATE_TO_INCIDENT_COMMAND",
                        "REQUEST_RESPONSE_AUTHORISATION",
                        "RECOMMEND_AUTHORISED_MITIGATION",
                    }:
                        false_escalations += 1
                if context["threat_level"] == "credible" and context["final_disposition"] == "mitigation_recommendation":
                    credible_opportunities += 1
                    if "RECOMMEND_AUTHORISED_MITIGATION" not in accepted_actions:
                        missed_threats += 1

            evaluation_dataset = generate_dataset(
                partition="evaluation",
                seeds=range(int(request["seed_start"]), int(request["seed_start"]) + int(request["seed_count"])),
            )
            if offline:
                from .offline_checkpoints import load_offline_checkpoint
                from .offline_rl import frozen_cql_action_accuracy

                frozen_model, _frozen_target, frozen_metadata = load_offline_checkpoint(
                    checkpoint_path,
                    expected_digest=binding.trusted_digest,
                    expected_offline_dataset_digest=offline_dataset_digest,
                    expected_source_dataset_digest=source_dataset_digest,
                )
                held_out_accuracy = frozen_cql_action_accuracy(
                    frozen_model,
                    evaluation_dataset,
                    training_normalization=frozen_metadata["normalization"],
                    context_length=int(frozen_metadata["context_length"]),
                    safety_threshold=float(frozen_metadata["safety_threshold"]),
                )
            else:
                frozen_model, frozen_metadata = load_checkpoint(
                    checkpoint_path,
                    expected_digest=binding.trusted_digest,
                )
                held_out_accuracy = frozen_action_accuracy(
                    frozen_model,
                    evaluation_dataset,
                    architecture=str(frozen_metadata["architecture"]),
                    context_length=int(frozen_metadata["context_length"]),
                    training_normalization=frozen_metadata["normalization"],
                )
            total_actions = sum(len(item["timeline"]) for item in public_episodes)
            evidence_actions = {
                "REQUEST_SENSOR_CONFIRMATION", "REQUEST_COMMAND_LINK_VERIFICATION",
                "CHECK_AUTHORISED_FLIGHT_DATABASE", "REQUEST_REMOTE_ID_VERIFICATION",
                "INCREASE_TRACK_PRIORITY", "CONTINUE_OBSERVATION",
            }
            approval_attempts = [
                step for item in public_episodes for step in item["timeline"]
                if step["gate"]["human_approval_required"]
            ]
            pair_by_seed: dict[int, dict[str, bool]] = {}
            for family, seed, success in episode_domains:
                if family in {"authorised_inspection", "perimeter_probing"}:
                    pair_by_seed.setdefault(seed, {})[family] = success
            complete_pairs = [value for value in pair_by_seed.values() if len(value) == 2]
            aggregate = {
                "episode_count": episode_count,
                "strict_success_count": strict_count,
                "strict_success_rate": strict_count / episode_count if episode_count else 0.0,
                "safety_violation_count": sum(int(item["result"]["safety_violation_count"]) for item in public_episodes),
                "safety_violation_rate": safety_episode_count / episode_count if episode_count else 0.0,
                "average_score": sum(float(item["result"]["score"]) for item in public_episodes) / episode_count if episode_count else 0.0,
                "abstention_rate": sum(
                    1
                    for item in public_episodes
                    if item["timeline"] and item["timeline"][-1]["gate"]["effective_action"] == "ABSTAIN_INSUFFICIENT_EVIDENCE"
                ) / episode_count if episode_count else 0.0,
                "false_escalation_rate": false_escalations / benign_opportunities if benign_opportunities else 0.0,
                "missed_threat_rate": missed_threats / credible_opportunities if credible_opportunities else 0.0,
                "expected_calibration_error": sum(
                    float(item["result"]["expected_calibration_error"])
                    for item in public_episodes
                ) / episode_count if episode_count else 0.0,
                "held_out_action_accuracy": held_out_accuracy,
                "gate_intervention_rate": sum(
                    1 for item in public_episodes for step in item["timeline"] if not step["gate"]["accepted"]
                ) / max(1, total_actions),
                "invalid_action_rate": sum(
                    1 for item in public_episodes for step in item["timeline"] if step["gate"]["violation_codes"]
                ) / max(1, total_actions),
                "stale_evidence_rate": sum(
                    1 for item in public_episodes for step in item["timeline"]
                    if any("stale" in code or code.startswith("fresh_") for code in step["gate"]["violation_codes"])
                ) / max(1, total_actions),
                "evidence_efficiency": 1.0 - sum(
                    1 for item in public_episodes for step in item["timeline"]
                    if step["recommendation"]["recommended_action"] in evidence_actions
                ) / max(1, total_actions),
                "approval_correctness": (
                    sum(1 for step in approval_attempts if step["gate"]["accepted"] and step["gate"]["approval_consumed"]) / len(approval_attempts)
                    if approval_attempts else 1.0
                ),
                "average_action_count": total_actions / max(1, episode_count),
                "average_elapsed_ms": sum(float(item.get("elapsed_ms", 0.0)) for item in public_episodes) / max(1, episode_count),
                "worst_case_score": min((float(item["result"]["score"]) for item in public_episodes), default=0.0),
                "pair_consistency_rate": sum(1 for value in complete_pairs if all(value.values())) / len(complete_pairs) if complete_pairs else 0.0,
            }
            _send(
                queue,
                "completed",
                {
                    "model_id": request["training_run_id"],
                    "algorithm": "discrete_cql" if offline else "behaviour_cloning",
                    "episodes": public_episodes,
                    "aggregate": aggregate,
                },
            )
            return

        raise ValueError("unsupported worker operation")
    except InterruptedError:
        _send(queue, "cancelled", {})
    except TimeoutError:
        _send(queue, "timed_out", {"error_category": "execution_timeout"})
    except Exception as exc:
        # Never cross the process boundary with exception text, paths, args, or
        # traceback. The local traceback is intentionally discarded.
        traceback.clear_frames(exc.__traceback__) if exc.__traceback__ else None
        _send(queue, "failed", {"error_category": f"{operation}_failure"})
