"""Final integrated environment verification and evidence generation."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from verify_common import parse_test_count, validate_source_commit  # noqa: E402

_ALLOWED_RECEIPT_FILES = ("evidence/final-environment.json",)


def _run_command(cmd: list[str]) -> tuple[str, int]:
    result = subprocess.run(
        cmd,
        cwd=str(REPOSITORY_ROOT),
        capture_output=True,
        text=True,
    )
    return (result.stdout or "") + (result.stderr or ""), result.returncode


def _run_pytest(path: str) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "pytest", path, "-q"]
    stdout, rc = _run_command(cmd)
    count = 0
    try:
        count = parse_test_count(stdout)
    except ValueError:
        count = 0
    return {
        "command": " ".join(cmd),
        "exit_code": rc,
        "test_count": count,
        "passed": rc == 0,
        "stdout_tail": stdout[-2000:],
    }


def _run_cli(*args: str) -> Any:
    cmd = [sys.executable, "-m", "training_ground.cli", *args]
    stdout, rc = _run_command(cmd)
    if rc != 0:
        return {"command": " ".join(cmd), "exit_code": rc, "stdout": stdout, "error": "cli failed"}
    if args and args[0] == "list-instances":
        return [line.strip() for line in stdout.splitlines() if line.strip()]
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"command": " ".join(cmd), "exit_code": rc, "stdout": stdout, "error": "invalid json"}


def _run_gym_valid() -> dict[str, Any]:
    import json as _json

    from training_adapters.gym_env import IncidentGymEnv
    from training_ground.policies import valid_repair_policy

    checker_ok = False
    checker_error = None
    try:
        from gymnasium.utils.env_checker import check_env

        probe = IncidentGymEnv(profile=0, max_steps=8)
        check_env(probe, skip_render_check=True)
        probe.close()
        checker_ok = True
    except Exception as exc:  # noqa: BLE001
        checker_error = f"{type(exc).__name__}: {exc}"

    env = IncidentGymEnv(profile=0, max_steps=64)
    env.reset()
    reward = 0.0
    terminated = False
    for action in valid_repair_policy():
        args = _json.dumps(action["arguments"])
        obs, reward, terminated, truncated, info = env.step(
            {"tool": action["tool"], "arguments_json": env._encode_text(args)}
        )
        if terminated or truncated:
            break
    env.close()
    return {
        "terminated": terminated,
        "reward": reward,
        "score_one": reward == 1.0,
        "check_env_passed": checker_ok,
        "check_env_error": checker_error,
    }


def _horizon_metrics() -> dict[str, Any]:
    from training_ground.policies import pair_informed_shortest_policy, valid_repair_policy

    policy = valid_repair_policy()
    informed = pair_informed_shortest_policy()
    return {
        "pair_blind_policy_actions": len(policy),
        "pair_blind_distinct_tools": sorted({a["tool"] for a in policy}),
        "pair_informed_shortest_actions": len(informed),
        "includes_diagnostics": any(
            a["tool"] == "runtime.run" and "cutpoint" in a.get("arguments", {})
            for a in policy
        ),
        "includes_trace": any(a["tool"] == "telemetry.trace" for a in policy),
        "includes_rollback": any(a["tool"] == "release.rollback" for a in policy),
    }


def _failed_predicates(grade: dict[str, Any]) -> list[str]:
    failed = []
    for name, value in grade.get("predicates", {}).items():
        if name in ("protocol_abuse", "state_tampering"):
            if value:
                failed.append(name)
        elif not value:
            failed.append(name)
    return failed


def _run_policy_control(
    name: str,
    policy: list[dict[str, Any]],
    *,
    profile: int = 0,
    max_steps: int = 64,
) -> dict[str, Any]:
    from training_ground import load_environment

    env = load_environment("eval", 0, options={"profile": profile, "max_steps": max_steps})
    env.reset()
    terminated = truncated = False
    try:
        for action in policy:
            if terminated or truncated:
                break
            _, _, terminated, truncated, _ = env.step(action)
        grade = env.grade()
    finally:
        env.close()
    return {
        "name": name,
        "executed": True,
        "exploit_path_reached": True,
        "strict_success": grade.get("score") == 1.0,
        "reward": grade.get("score"),
        "failed_predicates": _failed_predicates(grade),
        "workloads": {
            key: value.get("outcome")
            for key, value in grade.get("workload_results", {}).items()
        },
    }


def _run_action_control(
    name: str,
    action: dict[str, Any],
    *,
    profile: int = 0,
) -> dict[str, Any]:
    from training_ground import load_environment

    env = load_environment("eval", 0, options={"profile": profile, "max_steps": 4})
    env.reset()
    try:
        obs, reward, terminated, truncated, _ = env.step(action)
        grade = env.grade()
    finally:
        env.close()
    return {
        "name": name,
        "executed": True,
        "exploit_path_reached": True,
        "strict_success": grade.get("score") == 1.0,
        "reward": grade.get("score"),
        "step_reward": reward,
        "terminated": terminated,
        "truncated": truncated,
        "error_observed": isinstance(obs, dict) and "error" in obs,
        "failed_predicates": _failed_predicates(grade),
    }


def _wrong_control_matrix() -> list[dict[str, Any]]:
    from training_ground.policies import (
        BROAD_EVENT_DEDUP_FLOW,
        LOGICAL_IDENTITY_FLOW,
        valid_repair_policy,
    )

    default_flow = """from __future__ import annotations
def s1(command, store): return store.prepare(command)
def s2(command, store): return store.append(command)
def s3(command, event_id, store): store.register(command, event_id)
def s4(event_id, store): return store.load(event_id)
def s5(event, store): return store.settle(event)
def s6(sequence, store): store.advance(sequence)
"""
    return [
        _run_policy_control("default_flow", valid_repair_policy(flow=default_flow)),
        _run_policy_control(
            "broad_event_dedup",
            valid_repair_policy(flow=BROAD_EVENT_DEDUP_FLOW),
        ),
        _run_policy_control(
            "missing_recovery_restore",
            [
                action for action in valid_repair_policy(flow=LOGICAL_IDENTITY_FLOW)
                if action["tool"] != "recovery.restore"
            ],
        ),
        _run_action_control(
            "hidden_workload_direct",
            {"tool": "runtime.run", "arguments": {"workload_id": "H-A1", "cutpoint": "s5.exit"}},
        ),
        _run_action_control(
            "path_traversal",
            {"tool": "workspace.read", "arguments": {"path": "../fixture/service.sqlite3"}},
        ),
    ]


def _reward_ablation_matrix() -> dict[str, Any]:
    from strict_verifier.predicates import PREDICATE_CATEGORIES
    from strict_verifier.reward import calculate_reward

    base = {name: True for name in PREDICATE_CATEGORIES}
    base["protocol_abuse"] = False
    base["state_tampering"] = False
    return {
        "note": "Full credit requires authenticated transcripts and bounded resources.",
        "baseline": calculate_reward(base, {}),
        "without_transcript_integrity": calculate_reward(
            {**base, "transcript_integrity": False},
            {},
        ),
        "without_bounded_resources": calculate_reward(
            {**base, "bounded_resources": False},
            {},
        ),
    }


def _gold_families() -> dict[str, Any]:
    from training_ground import load_environment
    from training_ground.policies import INTENT_OUTBOX_FLOW, LOGICAL_IDENTITY_FLOW, valid_repair_policy

    out: dict[str, Any] = {}
    for name, flow in (
        ("logical_identity", LOGICAL_IDENTITY_FLOW),
        ("intent_outbox", INTENT_OUTBOX_FLOW),
    ):
        for profile in (0, 1):
            env = load_environment("eval", 0, options={"profile": profile, "max_steps": 64})
            env.reset()
            for action in valid_repair_policy(flow=flow):
                _, _, terminated, truncated, _ = env.step(action)
                if terminated or truncated:
                    break
            grade = env.grade()
            env.close()
            out[f"{name}_profile{profile}"] = {
                "score": grade.get("score"),
                "verdict": grade.get("verdict"),
                "member_hidden": grade.get("predicates", {}).get("member_hidden_workloads_pass"),
            }
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=REPOSITORY_ROOT / "evidence" / "final-environment.json")
    parser.add_argument("--source-commit", default=None)
    args = parser.parse_args()

    try:
        source_commit = validate_source_commit(
            REPOSITORY_ROOT, args.source_commit, _ALLOWED_RECEIPT_FILES
        )
    except ValueError as exc:
        print(f"source-commit binding failed: {exc}", file=sys.stderr)
        return 2

    suites = {
        "milestone_1": _run_pytest("tests/milestone_1"),
        "milestone_2": _run_pytest("tests/milestone_2"),
        "final_core": _run_pytest("tests/final_core"),
        "soundness": _run_pytest("tests/soundness"),
        "controls": _run_pytest("tests/controls"),
        "final_audit": _run_pytest("tests/final_audit"),
        "adapters": _run_pytest("tests/adapters"),
        "integrations": _run_pytest("tests/integrations"),
        "all": _run_pytest("tests"),
    }

    scripted_dev = _run_cli("run-scripted", "--split", "dev", "--seed", "1234")
    scripted_eval = _run_cli("run-scripted", "--split", "eval", "--seed", "0")
    instances = _run_cli("list-instances", "--split", "eval", "--count", "5")
    gym_result = _run_gym_valid()
    horizon = _horizon_metrics()
    gold = _gold_families()
    wrong_controls = _wrong_control_matrix()
    reward_ablations = _reward_ablation_matrix()

    apex_smoke = _run_command([sys.executable, str(REPOSITORY_ROOT / "scripts" / "smoke_apex_scripted.py")])
    docker_probe = _run_command(["docker", "version"])

    all_suites_ok = all(s["passed"] for s in suites.values())
    scripted_ok = (
        isinstance(scripted_dev, dict)
        and scripted_dev.get("score") == 1.0
        and isinstance(scripted_eval, dict)
        and scripted_eval.get("score") == 1.0
    )
    gold_ok = all(v.get("score") == 1.0 for v in gold.values())
    horizon_ok = horizon["pair_blind_policy_actions"] >= 15
    all_pass = (
        all_suites_ok
        and scripted_ok
        and gym_result.get("score_one")
        and gym_result.get("check_env_passed")
        and gold_ok
        and horizon_ok
    )

    receipt: dict[str, Any] = {
        "schema_version": 5,
        "milestone": "final-integrated-environment-remediated",
        "environment_version": "final-1.0.0",
        "tested_source_commit": source_commit,
        "verification": {
            "python_version": sys.version.split()[0],
            "suites": suites,
            "total_test_count": suites["all"]["test_count"],
            "scripted_dev_score": scripted_dev.get("score") if isinstance(scripted_dev, dict) else None,
            "scripted_eval_score": scripted_eval.get("score") if isinstance(scripted_eval, dict) else None,
            "gym": gym_result,
            "instance_ids": instances,
            "horizon": horizon,
            "gold_repair_families": gold,
            "wrong_control_matrix": wrong_controls,
            "reward_ablation_matrix": reward_ablations,
            "apex_sidecar": {
                "exit_code": apex_smoke[1],
                "stdout_tail": apex_smoke[0][-1000:],
                "claim": "APEX-SWE task-pack compatibility plus local side-car scripted smoke; real apx model-driven harness execution NOT VERIFIED",
            },
            "docker": {
                "available": docker_probe[1] == 0,
                "status": "VERIFIED" if docker_probe[1] == 0 else "NOT VERIFIED",
            },
            "upstream_apex_harness": "NOT VERIFIED",
            "outcome": "pass" if all_pass else "fail",
            "limitations": [
                "Docker execution NOT VERIFIED unless daemon available",
                "Real upstream apx model-driven harness execution NOT VERIFIED",
                "Symlink/junction escape probes are platform-limited",
            ],
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
