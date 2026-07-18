"""Killable worker entry points for Talon dataset, training, and evaluation jobs."""

from __future__ import annotations

import json
import os
import platform
import traceback
from pathlib import Path
from typing import Any

from drone_decision_ground.actions import ACTION_SCHEMA_VERSION

from .datasets import generate_dataset, load_dataset
from .manifests import TrainingManifest, write_immutable_json


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

        dataset = load_dataset(Path(paths["dataset"]))
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
            if cancelled.is_set():
                raise InterruptedError
            normalization = dataset.manifest.normalization
            if normalization is None:
                raise ValueError("training dataset lacks normalization")
            validation_dataset = generate_dataset(
                partition="validation",
                seeds=dataset.manifest.seeds,
                families=dataset.manifest.scenario_families,
            )
            validation_accuracy = frozen_action_accuracy(
                model,
                validation_dataset,
                architecture=config.architecture,
                context_length=config.context_length,
                training_normalization=normalization,
            )
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
            )
            source = str(request["application_commit"])
            hardware = torch.cuda.get_device_name(0) if torch.cuda.is_available() else platform.processor() or "cpu"
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
                    "training_metrics": {
                        **{key: values[-1] for key, values in history.items()},
                        "validation_action_accuracy": validation_accuracy,
                    },
                    "training_history": history,
                },
            )
            return

        if operation == "evaluation":
            from drone_decision_verifier.hidden_scenarios import HIDDEN_FAMILY_KEYS

            from .behaviour_cloning import frozen_action_accuracy
            from .checkpoints import load_checkpoint
            from .evaluation import evaluate_checkpoint
            from .policy_isolation import IsolatedPolicyClient

            public_episodes: list[dict[str, Any]] = []
            private_episodes: list[dict[str, Any]] = []
            source = str(request["application_commit"])
            total = len(HIDDEN_FAMILY_KEYS) * int(request["seed_count"])
            with IsolatedPolicyClient(
                Path(paths["checkpoint"]),
                expected_digest=str(request["checkpoint_digest"]),
                timeout_seconds=min(10.0, float(request["timeout_seconds"])),
            ) as policy:
                if not all(policy.probe().values()):
                    raise RuntimeError("policy isolation probe failed")
                for family in HIDDEN_FAMILY_KEYS:
                    for seed in range(int(request["seed_start"]), int(request["seed_start"]) + int(request["seed_count"])):
                        if cancelled.is_set():
                            raise InterruptedError
                        episode = evaluate_checkpoint(
                            Path(paths["checkpoint"]),
                            family=family,
                            seed=seed,
                            partition="evaluation",
                            expected_checkpoint_digest=str(request["checkpoint_digest"]),
                            environment_commit=source,
                            verifier_commit=source,
                            timeout_seconds=max(1, int(request["timeout_seconds"])),
                            policy_client=policy,
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
                seeds=range(
                    int(request["seed_start"]),
                    int(request["seed_start"]) + int(request["seed_count"]),
                ),
            )
            frozen_model, frozen_metadata = load_checkpoint(
                Path(paths["checkpoint"]),
                expected_digest=str(request["checkpoint_digest"]),
            )
            held_out_accuracy = frozen_action_accuracy(
                frozen_model,
                evaluation_dataset,
                architecture=str(frozen_metadata["architecture"]),
                context_length=int(frozen_metadata["context_length"]),
                training_normalization=frozen_metadata["normalization"],
            )
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
            }
            _send(
                queue,
                "completed",
                {
                    "model_id": request["training_run_id"],
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
