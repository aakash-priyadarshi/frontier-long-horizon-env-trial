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

from verify_common import parse_test_count  # noqa: E402


def _run_command(cmd: list[str]) -> tuple[str, int]:
    result = subprocess.run(
        cmd,
        cwd=str(REPOSITORY_ROOT),
        capture_output=True,
        text=True,
    )
    return result.stdout, result.returncode


def _run_pytest() -> tuple[str, int, str]:
    cmd = [sys.executable, "-m", "pytest", "tests", "-q"]
    stdout, rc = _run_command(cmd)
    return " ".join(cmd), rc, stdout


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
    import json

    from training_adapters.gym_env import IncidentGymEnv
    from training_ground.policies import valid_repair_policy

    env = IncidentGymEnv(profile=0, max_steps=20)
    env.reset()
    policy = [
        (action["tool"], action["arguments"])
        for action in valid_repair_policy()
    ]
    terminated = False
    reward = 0.0
    for tool, args in policy:
        obs, reward, terminated, truncated, info = env.step(
            {"tool": tool, "arguments_json": json.dumps(args)}
        )
        if terminated:
            break
    env.close()
    return {"terminated": terminated, "reward": reward, "score_one": reward == 1.0}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=REPOSITORY_ROOT / "evidence" / "final-environment.json")
    args = parser.parse_args()

    source_commit = _run_command(["git", "rev-parse", "HEAD"])[0].strip()
    pytest_cmd, pytest_rc, pytest_stdout = _run_pytest()
    pytest_count = parse_test_count(pytest_stdout)

    scripted_dev = _run_cli("run-scripted", "--split", "dev", "--seed", "1234")
    scripted_eval = _run_cli("run-scripted", "--split", "eval", "--seed", "0")
    instances = _run_cli("list-instances", "--split", "eval", "--count", "5")
    gym_result = _run_gym_valid()

    all_cli_ok = scripted_dev.get("score") == 1.0 and scripted_eval.get("score") == 1.0
    all_pass = pytest_rc == 0 and all_cli_ok and gym_result["score_one"]

    receipt: dict[str, Any] = {
        "schema_version": 3,
        "milestone": "final-integrated-environment",
        "tested_source_commit": source_commit,
        "verification": {
            "command": pytest_cmd,
            "python_version": sys.version.split()[0],
            "test_count": pytest_count,
            "pytest_exit_code": pytest_rc,
            "scripted_dev_score": scripted_dev.get("score"),
            "scripted_eval_score": scripted_eval.get("score"),
            "gym_reward": gym_result["reward"],
            "instance_ids": instances,
            "outcome": "pass" if all_pass else "fail",
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
