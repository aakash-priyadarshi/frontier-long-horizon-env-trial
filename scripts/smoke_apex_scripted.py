"""Local APEX task smoke without paid models.

Success requires a real strict verifier score of 1.0 after a valid repair. This
script reports internal side-car execution only; upstream APEX-SWE harness and
Docker execution remain not verified.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from training_adapters.apex_compat import (  # noqa: E402
    sanitize_apex_trial_result,
    validate_apex_task_dir,
    write_json,
)
from training_adapters.rollout import ScriptedRecoveryPolicy, run_rollout  # noqa: E402

TASK = ROOT / "integrations" / "apex_swe" / "tasks" / "frontier-incident-smoke"


def main() -> int:
    problems = validate_apex_task_dir(TASK)
    if problems:
        print("TASK_LAYOUT_FAIL", problems)
        return 1

    result = run_rollout(
        profile=0, policy=ScriptedRecoveryPolicy(), max_steps=64, require_strict=True
    )
    success = bool(result.success and result.strict_score == 1.0)
    trial = sanitize_apex_trial_result(
        task_id="frontier-incident-smoke",
        success=success,
        step_count=len(result.steps),
        metadata={
            "execution": {
                "kind": "internal_sidecar",
                "upstream_harness": {"executed": False, "status": "NOT VERIFIED"},
                "docker": {"executed": False, "status": "NOT VERIFIED"},
            }
        },
    )
    trial["metadata"]["strict_score"] = result.strict_score
    trial["metadata"]["evaluation"] = {
        "passed": success,
        "mode": "strict_verifier",
    }
    with tempfile.TemporaryDirectory(prefix="apex-smoke-") as tmp:
        out = Path(tmp)
        write_json(out / "trial_result.json", trial)
        os.environ["FRONTIER_ADAPTER_OUT"] = str(out)
        print("INTERNAL_SIDE_CAR")
        print("upstream APEX-SWE harness: NOT VERIFIED")
        print("docker execution: NOT VERIFIED")
        print(json.dumps(trial, indent=2))
        if not success:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
