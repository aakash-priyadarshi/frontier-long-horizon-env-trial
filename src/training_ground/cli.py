"""Local CLI for the training ground."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .authority import authority_for_profile
from .episode import IncidentEnv
from .loader import load_environment
from .manifests import build_manifest, list_instance_ids


def _default_scripted_policy() -> list[dict[str, Any]]:
    """A valid, pair-blind reference repair policy.

    It collects diagnostic evidence, restores the authenticated snapshot,
    edits the candidate, deploys, runs the public workloads, and resumes.
    """
    idempotent_flow = """from __future__ import annotations

def s1(command, store): return store.prepare(command)

def s2(command, store):
    existing = store.get_event_id(command.get("command_key"), command.get("occurrence_id"))
    return existing if existing else store.append(command)

def s3(command, event_id, store): store.register(command, event_id)

def s4(event_id, store): return store.load(event_id)

def s5(event, store):
    existing = store.effect_exists(event["event_id"])
    return existing if existing else store.settle(event)

def s6(sequence, store): store.advance(sequence)
"""
    settings = """[service]
intake_enabled = true
settlement_enabled = true
attempt_budget = 3
transient_behavior = "retry"
"""
    return [
        {"tool": "telemetry.logs", "arguments": {"alias": "Q-41"}},
        {"tool": "state.inspect", "arguments": {"source": "public", "selector": {"stream": "settlement"}, "view": "progress"}},
        {"tool": "recovery.pause", "arguments": {}},
        {"tool": "recovery.restore", "arguments": {"snapshot_id": "S0"}},
        {"tool": "workspace.read", "arguments": {"path": "service/flow.py"}},
        {"tool": "workspace.read", "arguments": {"path": "service/settings.toml"}},
        {"tool": "workspace.edit", "arguments": {"path": "service/flow.py", "content": idempotent_flow}},
        {"tool": "workspace.edit", "arguments": {"path": "service/settings.toml", "content": settings}},
        {"tool": "release.deploy", "arguments": {}},
        {"tool": "runtime.run", "arguments": {"workload_id": "P1"}},
        {"tool": "runtime.run", "arguments": {"workload_id": "P2"}},
        {"tool": "runtime.run", "arguments": {"workload_id": "P3"}},
        {"tool": "recovery.resume", "arguments": {}},
        {"tool": "release.status", "arguments": {}},
    ]


def _cmd_list_instances(args: argparse.Namespace) -> int:
    for instance_id in list_instance_ids(args.split, args.count):
        print(instance_id)
    return 0


def _cmd_run_scripted(args: argparse.Namespace) -> int:
    env = load_environment(args.split, args.seed, options={"max_steps": args.max_steps})
    obs, info = env.reset()
    policy = _default_scripted_policy()
    for action in policy:
        obs, reward, terminated, truncated, info = env.step(action)
        if terminated or truncated:
            break
    grade = env.grade()
    transcript = env.transcript()
    env.close()
    print(json.dumps(grade, indent=2, sort_keys=True))
    if args.transcript:
        Path(args.transcript).write_text(
            json.dumps(transcript, indent=2, sort_keys=True), encoding="utf-8"
        )
    return 0


def _cmd_grade_transcript(args: argparse.Namespace) -> int:
    print("grade-transcript requires a fixture/session; not implemented in standalone CLI", file=sys.stderr)
    return 1


def _cmd_inspect_result(args: argparse.Namespace) -> int:
    result_path = Path(args.result)
    if not result_path.is_file():
        print(f"result file not found: {result_path}", file=sys.stderr)
        return 1
    result = json.loads(result_path.read_text(encoding="utf-8"))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m training_ground.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list-instances", help="list deterministic instance ids")
    list_parser.add_argument("--split", default="train")
    list_parser.add_argument("--count", type=int, default=10)
    list_parser.set_defaults(func=_cmd_list_instances)

    run_parser = sub.add_parser("run-scripted", help="run the reference repair policy")
    run_parser.add_argument("--split", default="dev")
    run_parser.add_argument("--seed", type=int, default=1234)
    run_parser.add_argument("--max-steps", type=int, default=64)
    run_parser.add_argument("--transcript", default=None)
    run_parser.set_defaults(func=_cmd_run_scripted)

    grade_parser = sub.add_parser("grade-transcript", help="grade a saved transcript")
    grade_parser.add_argument("path")
    grade_parser.set_defaults(func=_cmd_grade_transcript)

    inspect_parser = sub.add_parser("inspect-result", help="inspect a saved result file")
    inspect_parser.add_argument("result")
    inspect_parser.set_defaults(func=_cmd_inspect_result)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
