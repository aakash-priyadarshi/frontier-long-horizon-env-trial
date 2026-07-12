"""APEX-SWE result shaping and static task-pack compatibility helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .sanitize import sanitize_payload


# Fields read by apex-swe/integration/src/harness/executor.py::_load_task_context
APEX_TASK_YAML_KEYS = ("instruction", "max_agent_timeout_sec", "max_test_timeout_sec")

# Marker format expected by integration evaluator parsing.
APEX_RESULTS_START = "results starts here"
APEX_RESULTS_END = "results ends here"


def sanitize_apex_trial_result(
    *,
    task_id: str,
    success: bool,
    step_count: int,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a sanitized trial summary compatible with APEX-style receipts."""
    payload = {
        "task_id": task_id,
        "status": "completed" if success else "failed",
        "success": success,
        "metadata": {
            "test_passed": success,
            "step_count": step_count,
            "evaluation": {"passed": success},
            **(metadata or {}),
        },
    }
    return sanitize_payload(payload)


def format_apex_test_stdout(passed: bool) -> str:
    """Stdout block recognized by APEX integration evaluator heuristics."""
    verdict = "PASSED" if passed else "FAILED"
    return f"{APEX_RESULTS_START}\n{verdict}\n{APEX_RESULTS_END}\n"


def validate_apex_task_dir(task_dir: Path) -> list[str]:
    """Static compatibility checks for an APEX integration task directory."""
    problems: list[str] = []
    task_dir = Path(task_dir)
    yaml_path = task_dir / "task.yaml"
    if not yaml_path.is_file():
        problems.append("missing task.yaml")
        return problems
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        problems.append("task.yaml must be a mapping")
        return problems
    if not data.get("instruction"):
        problems.append("task.yaml missing instruction")
    compose = task_dir / "docker-compose.yaml"
    if not compose.is_file():
        compose = task_dir / "docker-compose.yml"
    if not compose.is_file():
        problems.append("missing docker-compose.yaml")
    else:
        compose_data = yaml.safe_load(compose.read_text(encoding="utf-8")) or {}
        services = (compose_data.get("services") or {}) if isinstance(compose_data, dict) else {}
        if "client" not in services:
            problems.append("docker-compose.yaml missing client service")
    verifier_names = (
        "run-tests.sh",
        "test.sh",
        "tests.sh",
        "run_tests.sh",
        "verify.sh",
        "run-tests.ps1",
        "run_tests.py",
    )
    if not any((task_dir / name).is_file() for name in verifier_names):
        problems.append("missing verifier script (run-tests.sh or run_tests.py)")
    return problems


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
