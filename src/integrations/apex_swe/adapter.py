"""APEX-SWE integration harness over the training_ground environment."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from training_adapters.apex_compat import (
    format_apex_test_stdout,
    sanitize_apex_trial_result,
    write_json,
)
from training_ground.loader import load_environment


def _logger() -> logging.Logger:
    return logging.getLogger("integrations.apex_swe")


def run_apex_trial(
    task_id: str,
    policy: list[dict[str, Any]],
    *,
    split: str = "eval",
    seed: int = 0,
    profile: int | None = None,
    max_steps: int = 64,
    work_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Run one APEX-SWE trial using the training_ground environment.

    ``policy`` is a list of ``{"tool": ..., "arguments": ...}`` actions.
    If ``profile`` is omitted, the environment's private profile is derived from
    ``seed`` and ``split``.
    """
    options: dict[str, Any] = {"max_steps": max_steps}
    if profile is not None:
        options["profile"] = profile
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="apex-swe-"))
    else:
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

    env = load_environment(split, seed, options=options, work_dir=work_dir)
    try:
        env.reset()
        terminated = False
        truncated = False
        step_count = 0
        for action in policy:
            if terminated or truncated:
                break
            _, _, terminated, truncated, info = env.step(action)
            step_count += 1

        grade = env.grade()
        score = float(grade.get("score", 0.0))
        success = score >= 1.0

        _logger().info("APEX task completed", task_id=task_id, score=score)
        return sanitize_apex_trial_result(
            task_id=task_id,
            success=success,
            step_count=step_count,
            metadata={
                "score": score,
                "verdict": grade.get("verdict"),
                "predicates": grade.get("predicates"),
                "workload_results": grade.get("workload_results"),
                "roots": grade.get("roots"),
            },
        )
    except Exception as exc:
        _logger().error("APEX task failed", task_id=task_id, error=str(exc))
        return sanitize_apex_trial_result(
            task_id=task_id,
            success=False,
            step_count=0,
            metadata={"error": str(exc)},
        )
    finally:
        env.close()


def write_apex_result(result: dict[str, Any], output_dir: Path | str) -> None:
    """Write the APEX-style result and stdout marker to a task directory."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "result.json", result)
    passed = bool(result.get("success"))
    (out / "stdout.txt").write_text(format_apex_test_stdout(passed), encoding="utf-8")
