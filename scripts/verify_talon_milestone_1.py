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
import tempfile
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
EXPECTED_ACTION_SCHEMA_VERSION = "talon.action/3.0"
EXPECTED_DATASET_SCHEMA_VERSION = "talon.private-dataset/3.0"


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


def _render_command(command: list[str]) -> str:
    executable = Path(command[0]).name
    lower = executable.lower()
    if lower.endswith(".exe") or lower.endswith(".cmd"):
        executable = executable.rsplit(".", 1)[0]
    if executable.lower().startswith("python"):
        executable = "python"
    return subprocess.list2cmdline([executable, *command[1:]])


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
    return {
        "name": name,
        "command": _render_command(command),
        "exit_code": result.returncode,
        "passed": result.returncode == 0,
        "test_count": _test_count(output),
        "duration_seconds": round(time.monotonic() - started, 3),
        "classification": classification,
    }


def _playwright_report(output: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(output, index)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("stats"), dict):
            return value
    raise ValueError("Playwright JSON report was not produced")


def _run_playwright(name: str, npm: str, *, spec: str | None = None) -> dict[str, Any]:
    command = [npm, "run", "test:e2e", "--", "--browser=chromium", "--reporter=json"]
    if spec is not None:
        command.append(spec)
    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT / "apps" / "dashboard",
        capture_output=True,
        text=True,
        check=False,
    )
    output = (result.stdout or "") + (result.stderr or "")
    try:
        stats = _playwright_report(output)["stats"]
        expected = int(stats.get("expected", 0))
        unexpected = int(stats.get("unexpected", 0))
        flaky = int(stats.get("flaky", 0))
        skipped = int(stats.get("skipped", 0))
        report_valid = True
    except (TypeError, ValueError):
        expected = unexpected = flaky = skipped = 0
        report_valid = False
    journeys = expected + unexpected + flaky + skipped
    return {
        "name": name,
        "command": _render_command(command),
        "exit_code": result.returncode,
        "passed": result.returncode == 0 and report_valid and skipped == 0,
        "test_count": journeys,
        "executed_count": journeys - skipped,
        "skipped_count": skipped,
        "duration_seconds": round(time.monotonic() - started, 3),
        "classification": "real_browser",
        "browser": "chromium",
        "spec": spec or "e2e",
    }


def _schema_versions() -> dict[str, Any]:
    from drone_decision_ground.actions import ACTION_SCHEMA_VERSION
    from drone_training.datasets import DATASET_SCHEMA_VERSION

    checks = {
        "action_schema_matches_expected": ACTION_SCHEMA_VERSION
        == EXPECTED_ACTION_SCHEMA_VERSION,
        "private_dataset_schema_matches_expected": DATASET_SCHEMA_VERSION
        == EXPECTED_DATASET_SCHEMA_VERSION,
    }
    return {
        "classification": "runtime_import_and_static_assertion",
        "passed": all(checks.values()),
        "checks": checks,
        "action_schema_version": ACTION_SCHEMA_VERSION,
        "private_dataset_schema_version": DATASET_SCHEMA_VERSION,
        "sources": {
            "action": "drone_decision_ground.actions.ACTION_SCHEMA_VERSION",
            "private_dataset": "drone_training.datasets.DATASET_SCHEMA_VERSION",
        },
    }


def _policy_worker_isolation() -> dict[str, Any]:
    import torch

    from drone_training.checkpoints import save_checkpoint
    from drone_training.features import FEATURE_DIM, FEATURE_SCHEMA_VERSION
    from drone_training.gru_policy import GRUPolicy
    from drone_training.manifests import NormalizationStats
    from drone_training.policy_isolation import IsolatedPolicyClient

    with tempfile.TemporaryDirectory(prefix="talon-isolation-verification-") as directory:
        checkpoint = Path(directory) / "policy.pt"
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(0)
            model = GRUPolicy(hidden_dim=8, layers=1, dropout=0.0)
        normalization = NormalizationStats(
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            mean=(0.0,) * FEATURE_DIM,
            scale=(1.0,) * FEATURE_DIM,
            normalization_mask=(True,) * FEATURE_DIM,
            sample_count=1,
        )
        digest = save_checkpoint(
            checkpoint,
            model=model,
            architecture="gru",
            dataset_digest="sha256:" + "0" * 64,
            context_length=2,
            normalization=normalization,
            training_instance_digests=("sha256:" + "1" * 64,),
            seed_domain_digest="sha256:" + "2" * 64,
            return_conditioning_target=0.0,
        )
        with IsolatedPolicyClient(checkpoint, expected_digest=digest) as client:
            checks = client.probe()
        for probe in ("malformed_output", "oversized_output", "timeout"):
            with IsolatedPolicyClient(
                checkpoint,
                expected_digest=digest,
                timeout_seconds=5.0,
            ) as client:
                if probe == "timeout":
                    client.timeout_seconds = 0.25
                outcome = client.protocol_fault_probe(probe)
                checks[f"{probe}_rejected"] = outcome["rejected"]
                checks[f"{probe}_public_error_sanitized"] = outcome[
                    "public_error_sanitized"
                ]
        checkpoint.chmod(0o600)
    checks["public_errors_sanitized"] = all(
        checks[f"{probe}_public_error_sanitized"]
        for probe in ("malformed_output", "oversized_output", "timeout")
    )
    return {
        "classification": "dynamically_executed",
        "passed": all(checks.values()),
        "checks": checks,
        "raw_probe_output_retained": False,
    }


def _git_output(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _frontier_baseline(repository: Path = REPOSITORY_ROOT) -> str:
    introduction = _git_output(
        repository,
        "log",
        "--diff-filter=A",
        "--format=%H",
        "--",
        "scripts/verify_talon_milestone_1.py",
    ).splitlines()
    if len(introduction) != 1:
        raise RuntimeError("Talon source introduction commit could not be resolved uniquely")
    return _git_output(repository, "rev-parse", f"{introduction[0]}^")


def _git_paths_unchanged(
    repository: Path,
    baseline: str,
    source_commit: str,
    paths: tuple[str, ...],
) -> bool:
    committed = subprocess.run(
        ["git", "diff", "--quiet", baseline, source_commit, "--", *paths],
        cwd=repository,
        check=False,
    ).returncode == 0
    working = subprocess.run(
        ["git", "diff", "--quiet", source_commit, "--", *paths],
        cwd=repository,
        check=False,
    ).returncode == 0
    return committed and working


def _verification_by_name(commands: list[dict[str, Any]], name: str) -> dict[str, Any]:
    matches = [item for item in commands if item["name"] == name]
    if len(matches) != 1:
        raise RuntimeError(f"verification result {name!r} is missing or duplicated")
    return matches[0]


def _browser_verification(commands: list[dict[str, Any]]) -> dict[str, Any]:
    total = _verification_by_name(commands, "dashboard_playwright")
    talon = _verification_by_name(commands, "talon_playwright")
    frontier = _verification_by_name(commands, "frontier_playwright")
    consistent = total["test_count"] == talon["test_count"] + frontier["test_count"]
    passed = (
        all(item["passed"] for item in (total, talon, frontier))
        and consistent
        and total["test_count"] == 22
        and talon["test_count"] == 10
        and frontier["test_count"] == 12
        and all(item["skipped_count"] == 0 for item in (total, talon, frontier))
    )
    return {
        "classification": "dynamically_executed_real_browser",
        "passed": passed,
        "browser": "chromium",
        "execution": "real_browser_not_mocked",
        "component_count_consistent": consistent,
        "total": {
            "verification_name": total["name"],
            "journey_count": total["test_count"],
            "skipped_count": total["skipped_count"],
            "duration_seconds": total["duration_seconds"],
        },
        "talon": {
            "verification_name": talon["name"],
            "journey_count": talon["test_count"],
            "skipped_count": talon["skipped_count"],
            "duration_seconds": talon["duration_seconds"],
        },
        "frontier": {
            "verification_name": frontier["name"],
            "journey_count": frontier["test_count"],
            "skipped_count": frontier["skipped_count"],
            "duration_seconds": frontier["duration_seconds"],
        },
    }


def _frontier_integrity(
    source_commit: str,
    commands: list[dict[str, Any]],
    *,
    repository: Path = REPOSITORY_ROOT,
    baseline: str | None = None,
) -> dict[str, Any]:
    baseline_sha = baseline or _frontier_baseline(repository)
    scoring_paths = ("src/training_ground", "src/strict_verifier")
    evidence_files = tuple(
        line
        for line in _git_output(
            repository,
            "ls-tree",
            "-r",
            "--name-only",
            baseline_sha,
            "--",
            "evidence",
        ).splitlines()
        if line
    )
    training_unchanged = _git_paths_unchanged(
        repository, baseline_sha, source_commit, (scoring_paths[0],)
    )
    verifier_unchanged = _git_paths_unchanged(
        repository, baseline_sha, source_commit, (scoring_paths[1],)
    )
    evidence_unchanged = bool(evidence_files) and _git_paths_unchanged(
        repository, baseline_sha, source_commit, evidence_files
    )
    python_result = _verification_by_name(commands, "full_python_regression")
    playwright_result = _verification_by_name(commands, "frontier_playwright")
    passed = (
        training_unchanged
        and verifier_unchanged
        and evidence_unchanged
        and python_result["passed"]
        and playwright_result["passed"]
        and playwright_result["test_count"] == 12
    )
    return {
        "classification": "git_integrity_and_executed_regression",
        "passed": passed,
        "baseline_sha": baseline_sha,
        "source_commit": source_commit,
        "source_integrity": {
            "classification": "git_integrity_verified",
            "checked_paths": list(scoring_paths),
            "training_ground_unchanged": training_unchanged,
            "strict_verifier_unchanged": verifier_unchanged,
            "passed": training_unchanged and verifier_unchanged,
        },
        "evidence_integrity": {
            "classification": "git_integrity_verified",
            "checked_pre_existing_files": list(evidence_files),
            "talon_receipt_excluded_as_new_evidence": RECEIPT_PATH,
            "pre_existing_frontier_evidence_unchanged": evidence_unchanged,
            "passed": evidence_unchanged,
        },
        "python_tests": {
            "classification": "executed_with_complete_python_suite",
            "verification_name": python_result["name"],
            "passed": python_result["passed"],
        },
        "playwright": {
            "classification": "dynamically_executed_real_browser",
            "verification_name": playwright_result["name"],
            "journey_count": playwright_result["test_count"],
            "skipped_count": playwright_result["skipped_count"],
            "passed": playwright_result["passed"],
        },
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


def _validate_receipt_completeness(
    receipt: dict[str, Any], *, expected_source_commit: str
) -> None:
    failures: list[str] = []

    def require(condition: bool, label: str) -> None:
        if not condition:
            failures.append(label)

    require(
        bool(re.fullmatch(r"[0-9a-f]{40}", receipt.get("source_commit", ""))),
        "full source commit SHA",
    )
    require(receipt.get("source_commit") == expected_source_commit, "source commit binding")
    schema_versions = receipt.get("schema_versions", {})
    require(schema_versions.get("passed") is True, "schema version verification")
    require(
        schema_versions.get("action_schema_version") == EXPECTED_ACTION_SCHEMA_VERSION,
        "action schema version",
    )
    require(
        schema_versions.get("private_dataset_schema_version")
        == EXPECTED_DATASET_SCHEMA_VERSION,
        "private dataset schema version",
    )

    verification = {
        item.get("name"): item
        for item in receipt.get("verification", [])
        if isinstance(item, dict)
    }
    for name in (
        "talon_python",
        "full_python_regression",
        "dashboard_unit",
        "dashboard_lint",
        "dashboard_typecheck",
        "dashboard_build",
        "talon_playwright",
        "frontier_playwright",
        "dashboard_playwright",
        "npm_audit",
        "uv_lock",
        "diff_check",
    ):
        require(verification.get(name, {}).get("passed") is True, f"{name} result")
    for name in ("talon_python", "full_python_regression", "dashboard_unit"):
        require(verification.get(name, {}).get("test_count", 0) > 0, f"{name} count")

    browser = receipt.get("browser_verification", {})
    require(browser.get("passed") is True, "browser verification")
    require(browser.get("browser") == "chromium", "Chromium execution")
    require(browser.get("execution") == "real_browser_not_mocked", "real browser execution")
    require(browser.get("total", {}).get("journey_count") == 22, "total Playwright count")
    require(browser.get("talon", {}).get("journey_count") == 10, "Talon Playwright count")
    require(browser.get("frontier", {}).get("journey_count") == 12, "Frontier Playwright count")
    require(
        browser.get("component_count_consistent") is True,
        "Playwright component count consistency",
    )
    require(
        browser.get("total", {}).get("journey_count")
        == browser.get("talon", {}).get("journey_count", -1)
        + browser.get("frontier", {}).get("journey_count", -1),
        "Playwright count arithmetic",
    )
    require(
        all(
            browser.get(scope, {}).get("skipped_count") == 0
            for scope in ("total", "talon", "frontier")
        ),
        "Playwright skipped count",
    )

    isolation = receipt.get("policy_worker_isolation", {})
    isolation_checks = isolation.get("checks", {})
    required_isolation = (
        "python_isolated",
        "simulator_import_blocked",
        "training_import_blocked",
        "verifier_import_blocked",
        "hidden_scenario_import_blocked",
        "privileged_source_read_blocked",
        "private_dataset_read_blocked",
        "verifier_storage_read_blocked",
        "metadata_environment_absent",
        "malformed_output_rejected",
        "oversized_output_rejected",
        "timeout_rejected",
        "public_errors_sanitized",
    )
    require(isolation.get("classification") == "dynamically_executed", "isolation classification")
    require(isolation.get("passed") is True, "policy-worker isolation")
    require(
        all(isolation_checks.get(name) is True for name in required_isolation),
        "policy-worker isolation probes",
    )

    frontier = receipt.get("frontier_regression", {})
    require(frontier.get("passed") is True, "Frontier regression integrity")
    require(
        frontier.get("source_integrity", {}).get("training_ground_unchanged") is True,
        "Frontier training_ground integrity",
    )
    require(
        frontier.get("source_integrity", {}).get("strict_verifier_unchanged") is True,
        "Frontier strict_verifier integrity",
    )
    require(
        frontier.get("evidence_integrity", {}).get(
            "pre_existing_frontier_evidence_unchanged"
        )
        is True,
        "pre-existing Frontier evidence integrity",
    )
    require(frontier.get("python_tests", {}).get("passed") is True, "Frontier Python tests")
    require(frontier.get("playwright", {}).get("passed") is True, "Frontier Playwright")

    contract_checks = receipt.get("dynamic_contract", {}).get("checks", {})
    for name in (
        "command_link_requires_dedicated_request",
        "dataset_mutation_rejected",
        "approval_replay_rejected",
        "partition_instance_disjointness",
    ):
        require(contract_checks.get(name) is True, name)
    physical = receipt.get("physical_boundary", {})
    require(physical.get("passed") is True, "physical boundary")
    require(physical.get("action_count") == 13, "13-action vocabulary")
    claims = receipt.get("learned_model_claims", {})
    require(claims.get("smoke_baselines_only") is True, "smoke-baseline qualification")
    require(claims.get("safety_ready") is False, "no learned-model safety-readiness claim")
    serialized = json.dumps(receipt, sort_keys=True, ensure_ascii=False).lower()
    sensitive_patterns = (
        r"[a-z]:\\\\users\\\\",
        r"/(?:users|home)/[^/\"]+/",
        r'"approval_(?:nonce|secret)"',
        r'"hmac_(?:key|material|secret)"',
        r'"hidden_scenario_truth"',
        r'"expert_trajectories"',
        r'"chain_of_thought"',
        r'"private_reasoning"',
        r"private-quarantine",
    )
    require(
        not any(re.search(pattern, serialized) for pattern in sensitive_patterns),
        "receipt sensitive-content scan",
    )
    require(receipt.get("passed") is True, "overall receipt result")
    if failures:
        raise AssertionError("incomplete Talon receipt: " + ", ".join(failures))


def _build_receipt(
    *,
    source_commit: str,
    commands: list[dict[str, Any]],
    contract: dict[str, Any],
    physical_boundary: dict[str, Any],
    schema_versions: dict[str, Any],
    browser_verification: dict[str, Any],
    policy_worker_isolation: dict[str, Any],
    frontier_regression: dict[str, Any],
) -> dict[str, Any]:
    passed = (
        all(item["passed"] for item in commands)
        and contract["passed"]
        and physical_boundary["passed"]
        and schema_versions["passed"]
        and browser_verification["passed"]
        and policy_worker_isolation["passed"]
        and frontier_regression["passed"]
    )
    verification = {item["name"]: item for item in commands}
    receipt = {
        "schema_version": "talon.milestone-1-evidence/3.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_commit": source_commit,
        "passed": passed,
        "verification": commands,
        "test_counts": {
            "talon_python": verification["talon_python"]["test_count"],
            "complete_python": verification["full_python_regression"]["test_count"],
            "dashboard_unit": verification["dashboard_unit"]["test_count"],
            "playwright_total": browser_verification["total"]["journey_count"],
            "playwright_talon": browser_verification["talon"]["journey_count"],
            "playwright_frontier": browser_verification["frontier"]["journey_count"],
        },
        "schema_versions": schema_versions,
        "browser_verification": browser_verification,
        "policy_worker_isolation": policy_worker_isolation,
        "frontier_regression": frontier_regression,
        "dynamic_contract": contract,
        "physical_boundary": physical_boundary,
        "scope": {
            "simulation_only": True,
            "decision_support_only": True,
            "human_approval_mandatory": True,
            "external_effect": False,
        },
        "learned_model_claims": {
            "classification": "scope_statement",
            "smoke_baselines_only": True,
            "safety_ready": False,
        },
        "deferred": [
            "online reinforcement learning",
            "hardware or live sensor integration",
            "external response controls",
            "operational deployment",
        ],
    }
    _validate_receipt_completeness(receipt, expected_source_commit=source_commit)
    return receipt


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
        _run_playwright("talon_playwright", npm, spec="e2e/talon.spec.ts"),
        _run_playwright(
            "frontier_playwright", npm, spec="e2e/scripted-evaluation.spec.ts"
        ),
        _run_playwright("dashboard_playwright", npm),
        _run("npm_audit", [npm, "audit", "--audit-level=high"], cwd=dashboard, classification="dependency_scan"),
        _run("uv_lock", [uv, "lock", "--check"], classification="dependency_scan"),
        _run("diff_check", ["git", "diff", "--check"], classification="static"),
    ]
    contract = _dynamic_contract()
    physical_boundary = _physical_boundary()
    schema_versions = _schema_versions()
    browser_verification = _browser_verification(commands)
    policy_worker_isolation = _policy_worker_isolation()
    frontier_regression = _frontier_integrity(source_commit, commands)
    receipt = _build_receipt(
        source_commit=source_commit,
        commands=commands,
        contract=contract,
        physical_boundary=physical_boundary,
        schema_versions=schema_versions,
        browser_verification=browser_verification,
        policy_worker_isolation=policy_worker_isolation,
        frontier_regression=frontier_regression,
    )
    if not args.check_only:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
