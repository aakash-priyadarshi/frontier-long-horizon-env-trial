#!/usr/bin/env python3
"""Scripted APEX agent entrypoint — no paid model calls."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from training_adapters.apex_compat import (  # noqa: E402
    format_apex_test_stdout,
    sanitize_apex_trial_result,
    write_json,
)
from training_adapters.rollout import ScriptedRecoveryPolicy, run_rollout  # noqa: E402


def main() -> int:
    fixture_index = int(os.environ.get("FRONTIER_ADAPTER_FIXTURE_INDEX", "0"))
    out_dir = Path(os.environ.get("FRONTIER_ADAPTER_OUT", "/logs"))
    out_dir.mkdir(parents=True, exist_ok=True)

    result = run_rollout(profile=fixture_index, policy=ScriptedRecoveryPolicy(), max_steps=16)
    trial = sanitize_apex_trial_result(
        task_id="frontier-incident-smoke",
        success=result.success,
        step_count=len(result.steps),
        metadata={"truncated": result.truncated},
    )
    write_json(out_dir / "trial_result.json", trial)
    write_json(out_dir / "rollout.json", result.to_dict())
    marker = out_dir / "smoke_verdict.txt"
    marker.write_text(format_apex_test_stdout(result.success), encoding="utf-8")
    print(marker.read_text(encoding="utf-8"), end="")
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
