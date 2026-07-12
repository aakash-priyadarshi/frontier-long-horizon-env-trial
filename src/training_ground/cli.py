"""Local CLI for the training ground."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .loader import load_environment
from .manifests import list_instance_ids
from .policies import valid_repair_policy


def _cmd_list_instances(args: argparse.Namespace) -> int:
    for instance_id in list_instance_ids(args.split, args.count):
        print(instance_id)
    return 0


def _cmd_run_scripted(args: argparse.Namespace) -> int:
    env = load_environment(args.split, args.seed, options={"max_steps": args.max_steps})
    obs, info = env.reset()
    for action in valid_repair_policy():
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
    return 0 if grade.get("score") == 1.0 else 1


def _cmd_grade_transcript(args: argparse.Namespace) -> int:
    print(
        "grade-transcript requires a fixture/session; not implemented in standalone CLI",
        file=sys.stderr,
    )
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
