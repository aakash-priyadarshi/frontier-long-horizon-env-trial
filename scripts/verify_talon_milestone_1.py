"""Adversarial Talon Milestone 1 verification and source-bound receipt generation.

Use ``--check-only`` while developing. Evidence generation intentionally refuses
a dirty tree and binds the output to the exact source commit through
``verify_common.validate_source_commit``.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
for candidate in (str(SOURCE_ROOT), str(REPOSITORY_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from scripts.verify_common import validate_source_commit  # noqa: E402


RECEIPT_PATH = "evidence/talon-milestone-1.json"
ALLOWED_RECEIPTS = (RECEIPT_PATH,)


def _test_count(output: str) -> int:
    output = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output)
    patterns = (
        r"Tests\s+(\d+) passed",
        r"(\d+)\s+passed\s+\(",
        r"(\d+) passed",
    )
    for pattern in patterns:
        match = re.search(pattern, output)
        if match:
            return int(match.group(1))
    return 0


def _run(
    name: str,
    command: list[str],
    *,
    cwd: Path = REPOSITORY_ROOT,
    classification: str = "real",
) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    output = (result.stdout or "") + (result.stderr or "")
    rendered = ["python" if Path(command[0]).name.lower().startswith("python") else command[0], *command[1:]]
    return {
        "name": name,
        "command": subprocess.list2cmdline(rendered),
        "exit_code": result.returncode,
        "passed": result.returncode == 0,
        "test_count": _test_count(output),
        "duration_seconds": round(time.monotonic() - started, 3),
        "classification": classification,
    }


def _dynamic_contract() -> dict[str, Any]:
    """Run small independent probes in addition to the test-suite assertions."""

    from drone_decision_ground.actions import DecisionAction
    from drone_decision_ground.observation import EvidenceKind, PublicObservation
    from drone_decision_ground.scenarios import ScenarioConfig, list_public_capabilities
    from drone_decision_verifier.approval import SimulatedApprovalAuthority
    from drone_decision_verifier.hidden_scenarios import (
        HIDDEN_FAMILY_KEYS,
        behavioural_signature,
        build_environment,
        scenario_instance_digest,
    )
    from drone_decision_verifier.leak_detection import find_public_leaks
    from drone_training.behaviour_cloning import returns_to_go
    from drone_training.datasets import (
        generate_dataset,
        recompute_dataset_digest,
        verify_dataset_integrity,
    )
    from drone_training.features import encode_observation
    from drone_training.scripted import (
        AuthorityFirstSafePolicy,
        NoAuthorityCheckPolicy,
        NoCommandLinkCheckPolicy,
        OverEscalationPolicy,
        PublicPlausibleWrongHiddenPolicy,
        SafeScriptedPolicy,
        StaleTrackPolicy,
        UnderEscalationPolicy,
        recommendation,
        run_scripted,
    )

    public_probe_config = ScenarioConfig(family_id=HIDDEN_FAMILY_KEYS[0], partition="evaluation")
    public_env = build_environment(public_probe_config)
    raw, reset_info = public_env.reset(seed=41, options={"scenario_config": public_probe_config})
    observation = PublicObservation.model_validate(raw)
    next_raw, reward, *_rest, step_info = public_env.step(
        recommendation(DecisionAction.REQUEST_SENSOR_CONFIRMATION, observation)
    )
    public_leaks = find_public_leaks(
        {
            "capabilities": list_public_capabilities(),
            "reset_observation": raw,
            "reset_info": reset_info,
            "step_observation": next_raw,
            "step_info": step_info,
        }
    )

    paired_configs = (
        ScenarioConfig(family_id="authorised_inspection", partition="evaluation"),
        ScenarioConfig(family_id="perimeter_probing", partition="evaluation"),
    )
    paired_initial = [
        build_environment(config).reset(seed=7, options={"scenario_config": config})[0]
        for config in paired_configs
    ]
    paired_public_evidence = [
        {key: value for key, value in item.items() if key not in {"episode_id", "track_id"}}
        for item in paired_initial
    ]

    instance_sets = {
        partition: {
            scenario_instance_digest(
                ScenarioConfig(family_id=family, partition=partition),
                seed,
            )
            for family in HIDDEN_FAMILY_KEYS
            for seed in (0, 1)
        }
        for partition in ("train", "validation", "evaluation")
    }
    training = generate_dataset(partition="train", seeds=(3,))
    evaluation = generate_dataset(partition="evaluation", seeds=(3,))
    transition_sequences_differ = any(
        [step.observation.model_dump(mode="json") for step in training_item.steps]
        != [step.observation.model_dump(mode="json") for step in evaluation_item.steps]
        for training_item, evaluation_item in zip(
            training.trajectories,
            evaluation.trajectories,
        )
    )
    expert_sequences_differ = any(
        [step.expert_action for step in training_item.steps]
        != [step.expert_action for step in evaluation_item.steps]
        for training_item, evaluation_item in zip(
            training.trajectories,
            evaluation.trajectories,
        )
    )

    command_config = ScenarioConfig(family_id="lost_command_link", partition="evaluation")
    command_env = build_environment(command_config)
    command_raw, _ = command_env.reset(seed=23, options={"scenario_config": command_config})
    command_observation = PublicObservation.model_validate(command_raw)
    command_raw, *_ = command_env.step(
        recommendation(DecisionAction.REQUEST_SENSOR_CONFIRMATION, command_observation)
    )
    command_observation = PublicObservation.model_validate(command_raw)
    while EvidenceKind.SENSOR_CONFIRMATION in command_observation.pending_evidence:
        command_raw, *_ = command_env.step(
            recommendation(DecisionAction.CONTINUE_OBSERVATION, command_observation)
        )
        command_observation = PublicObservation.model_validate(command_raw)
    sensor_did_not_reveal_link = not any(
        item.kind is EvidenceKind.COMMAND_LINK for item in command_observation.evidence
    )
    command_raw, *_ = command_env.step(
        recommendation(
            DecisionAction.REQUEST_COMMAND_LINK_VERIFICATION,
            command_observation,
        )
    )
    command_observation = PublicObservation.model_validate(command_raw)
    while EvidenceKind.COMMAND_LINK in command_observation.pending_evidence:
        command_raw, *_ = command_env.step(
            recommendation(DecisionAction.CONTINUE_OBSERVATION, command_observation)
        )
        command_observation = PublicObservation.model_validate(command_raw)
    explicit_command_link_obtained = (
        command_observation.command_link_status.value == "lost"
        and any(
            item.kind is EvidenceKind.COMMAND_LINK
            for item in command_observation.evidence
        )
    )

    dataset_digest_recomputed = (
        recompute_dataset_digest(training) == training.manifest.dataset_digest
    )
    normalization = training.manifest.normalization
    if normalization is None:
        raise RuntimeError("dynamic training dataset lacks normalization")
    tampered_mean = list(normalization.mean)
    tampered_mean[0] += 0.01
    tampered_dataset = training.model_copy(
        update={
            "manifest": training.manifest.model_copy(
                update={
                    "normalization": normalization.model_copy(
                        update={"mean": tuple(tampered_mean)}
                    )
                }
            )
        }
    )
    try:
        verify_dataset_integrity(tampered_dataset)
        tampered_dataset_rejected = False
    except ValueError:
        tampered_dataset_rejected = True

    signatures = {
        behavioural_signature(family, partition="evaluation", seed=19)
        for family in HIDDEN_FAMILY_KEYS
    }
    positive_passes = []
    for policy_type in (SafeScriptedPolicy, AuthorityFirstSafePolicy):
        positive_passes.append(
            all(
                run_scripted(
                    policy_type(),
                    ScenarioConfig(family_id=family, partition="evaluation"),
                    seed=11,
                )[0]["strict_success"]
                for family in HIDDEN_FAMILY_KEYS
            )
        )
    negative_specs = (
        (OverEscalationPolicy(), "authorised_inspection"),
        (UnderEscalationPolicy(), "fast_unidentified_approach"),
        (NoAuthorityCheckPolicy(), "accidental_hobby_incursion"),
        (StaleTrackPolicy(), "stale_track_reappearance"),
        (PublicPlausibleWrongHiddenPolicy(), "perimeter_probing"),
        (NoCommandLinkCheckPolicy(), "lost_command_link"),
    )
    negative_rejected = all(
        not run_scripted(
            policy,
            ScenarioConfig(family_id=family, partition="evaluation"),
            seed=11,
        )[0]["strict_success"]
        for policy, family in negative_specs
    )

    approval = SimulatedApprovalAuthority(secret=b"v" * 32)
    record = approval.issue(
        now_ms=1_000,
        ttl_ms=1_000,
        episode_id="ep_" + "a" * 24,
        track_id="T-VERIFY",
        requested_action=DecisionAction.RECOMMEND_AUTHORISED_MITIGATION,
        authority_profile="uk_monitor_and_escalate",
        authority_profile_version="2.0",
        approver_scope="simulated_incident_commander",
        state_revision=4,
    )
    consume_args = {
        "approval_id": record.approval_id,
        "episode_id": record.episode_id,
        "track_id": record.track_id,
        "requested_action": record.requested_action,
        "authority_profile": record.authority_profile,
        "authority_profile_version": record.authority_profile_version,
        "state_revision": record.state_revision,
        "now_ms": 1_500,
    }
    first_use = approval.consume(**consume_args)
    replay = approval.consume(**consume_args)
    expiry_authority = SimulatedApprovalAuthority(secret=b"e" * 32)
    expired_record = expiry_authority.issue(
        now_ms=1_000,
        ttl_ms=1_000,
        episode_id="ep_" + "b" * 24,
        track_id="T-EXPIRE",
        requested_action=DecisionAction.RECOMMEND_AUTHORISED_MITIGATION,
        authority_profile="uk_monitor_and_escalate",
        authority_profile_version="2.0",
        approver_scope="simulated_incident_commander",
        state_revision=1,
    )
    expired = expiry_authority.consume(
        approval_id=expired_record.approval_id,
        episode_id=expired_record.episode_id,
        track_id=expired_record.track_id,
        requested_action=expired_record.requested_action,
        authority_profile=expired_record.authority_profile,
        authority_profile_version=expired_record.authority_profile_version,
        state_revision=expired_record.state_revision,
        now_ms=2_000,
    )

    zero_observation = PublicObservation.model_validate(
        {**raw, "critical_asset_proximity_m": 0.0}
    )
    missing_observation = zero_observation.model_copy(update={"critical_asset_proximity_m": None})
    zero_distinct = not (encode_observation(zero_observation) == encode_observation(missing_observation)).all()
    rtg_correct = returns_to_go([1.0, 0.0, -0.5]).tolist() == [0.5, -0.5, -0.5]

    checks = {
        "public_reset_step_leak_isolation": not public_leaks,
        "public_reward_non_probing": reward == 0.0,
        "paired_early_indistinguishability": (
            paired_initial[0]["episode_id"] != paired_initial[1]["episode_id"]
            and paired_initial[0]["track_id"] != paired_initial[1]["track_id"]
            and paired_public_evidence[0] == paired_public_evidence[1]
        ),
        "partition_instance_disjointness": (
            instance_sets["train"].isdisjoint(instance_sets["validation"])
            and instance_sets["train"].isdisjoint(instance_sets["evaluation"])
            and instance_sets["validation"].isdisjoint(instance_sets["evaluation"])
        ),
        "partition_transition_difference": transition_sequences_differ,
        "partition_expert_difference": expert_sequences_differ,
        "command_link_requires_dedicated_request": (
            sensor_did_not_reveal_link and explicit_command_link_obtained
        ),
        "dataset_digest_authoritatively_recomputed": dataset_digest_recomputed,
        "dataset_mutation_rejected": tampered_dataset_rejected,
        "scenario_signature_uniqueness": len(signatures) == len(HIDDEN_FAMILY_KEYS) == 15,
        "semantic_positive_flexibility": all(positive_passes),
        "semantic_negative_controls": negative_rejected,
        "approval_first_use": first_use.accepted and first_use.consumed,
        "approval_replay_rejected": not replay.accepted and replay.reason_code == "approval_already_consumed",
        "approval_expiry_rejected": not expired.accepted and expired.reason_code == "approval_expired",
        "return_to_go_correct": rtg_correct,
        "zero_missing_features_distinct": zero_distinct,
        "action_vocabulary_is_abstract": (
            len(DecisionAction) == 13
            and DecisionAction.REQUEST_COMMAND_LINK_VERIFICATION in DecisionAction
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "scenario_count": len(HIDDEN_FAMILY_KEYS),
        "public_leak_findings": public_leaks,
        "positive_control_count": len(positive_passes),
        "negative_control_count": len(negative_specs),
    }


def _physical_boundary() -> dict[str, Any]:
    from drone_decision_ground.actions import DecisionAction
    from drone_decision_ground.policy_gate import GateDecision

    action_names = [action.value for action in DecisionAction]
    forbidden_fragments = (
        "TAKE_DOWN",
        "JAM",
        "INTERCEPT",
        "DISABLE",
        "KINETIC",
        "WEAPON",
        "COUNTERMEASURE",
        "HARDWARE_TRIGGER",
    )
    vocabulary_safe = not any(
        fragment in action for action in action_names for fragment in forbidden_fragments
    )
    external_effect_locked = GateDecision.model_fields["external_effect"].default is False
    highest_is_abstract = "RECOMMEND_AUTHORISED_MITIGATION" in action_names
    source_roots = (
        REPOSITORY_ROOT / "src" / "drone_decision_ground",
        REPOSITORY_ROOT / "src" / "drone_decision_verifier",
        REPOSITORY_ROOT / "src" / "drone_training",
    )
    executable_patterns = re.compile(
        r"(?i)(activate|execute|trigger|select|control|command).{0,24}(jammer|intercept|weapon|kinetic|countermeasure|hardware)"
    )
    suspicious: list[str] = []
    for root in source_roots:
        for path in root.rglob("*.py"):
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if executable_patterns.search(line) and not line.lstrip().startswith("#"):
                    suspicious.append(f"{path.relative_to(REPOSITORY_ROOT)}:{line_number}")
    return {
        "passed": vocabulary_safe and external_effect_locked and highest_is_abstract and not suspicious,
        "action_count": len(action_names),
        "abstract_vocabulary": vocabulary_safe,
        "external_effect_default_false": external_effect_locked,
        "highest_action_is_abstract_recommendation": highest_is_abstract,
        "suspicious_implementation_lines": suspicious,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit")
    parser.add_argument("--output", type=Path, default=REPOSITORY_ROOT / RECEIPT_PATH)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="run verification without requiring a clean tree or writing evidence",
    )
    args = parser.parse_args()

    if args.check_only:
        source_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    else:
        source_commit = validate_source_commit(
            REPOSITORY_ROOT,
            args.source_commit,
            ALLOWED_RECEIPTS,
        )

    uv = shutil.which("uv")
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if uv is None or npm is None:
        raise RuntimeError("uv and npm are required for Talon verification")

    dashboard = REPOSITORY_ROOT / "apps" / "dashboard"
    commands = [
        _run("talon_python", [uv, "run", "--extra", "talon", "--extra", "test", "python", "-m", "pytest", "tests/talon", "-q"]),
        _run("full_python_regression", [uv, "run", "--extra", "talon", "--extra", "test", "python", "-m", "pytest", "tests", "-q"]),
        _run("dashboard_unit", [npm, "test", "--", "--run"], cwd=dashboard),
        _run("dashboard_lint", [npm, "run", "lint"], cwd=dashboard, classification="static"),
        _run("dashboard_typecheck", [npm, "run", "typecheck"], cwd=dashboard, classification="static"),
        _run("dashboard_build", [npm, "run", "build"], cwd=dashboard),
        _run("dashboard_playwright", [npm, "run", "test:e2e"], cwd=dashboard),
        _run("npm_audit", [npm, "audit", "--audit-level=high"], cwd=dashboard, classification="dependency_scan"),
        _run("uv_lock", [uv, "lock", "--check"], classification="dependency_scan"),
        _run("diff_check", ["git", "diff", "--check"], classification="static"),
    ]
    contract = _dynamic_contract()
    physical_boundary = _physical_boundary()
    passed = all(item["passed"] for item in commands) and contract["passed"] and physical_boundary["passed"]
    receipt = {
        "schema_version": "talon.milestone-1-evidence/2.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_commit": source_commit,
        "passed": passed,
        "verification": commands,
        "dynamic_contract": contract,
        "physical_boundary": physical_boundary,
        "scope": {
            "simulation_only": True,
            "decision_support_only": True,
            "human_approval_mandatory": True,
            "external_effect": False,
        },
        "deferred": [
            "online reinforcement learning",
            "hardware or live sensor integration",
            "external response controls",
            "operational deployment",
        ],
    }
    if not args.check_only:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
