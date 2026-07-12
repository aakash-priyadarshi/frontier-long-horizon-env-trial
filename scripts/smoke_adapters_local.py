"""Local adapter smoke without APEX or Docker."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from training_adapters.protocol import ALLOWED_TOOLS  # noqa: E402
from training_adapters.rollout import ScriptedRecoveryPolicy, run_rollout  # noqa: E402
from training_adapters.tools import ToolFilter, ToolFilterError  # noqa: E402


def main() -> int:
    filt = ToolFilter()
    assert len(filt.allowed_tools) == 12
    try:
        filt.check("bash")
        print("FAIL: bash permitted")
        return 1
    except ToolFilterError:
        pass

    result = run_rollout(profile=0, policy=ScriptedRecoveryPolicy(), max_steps=64)
    payload = result.to_dict()
    print(json.dumps({"success": result.success, "steps": len(result.steps), "tools": list(ALLOWED_TOOLS)}, indent=2))
    if not result.success:
        print(json.dumps(payload, indent=2)[:2000])
        return 1
    print("LOCAL_ADAPTER_SMOKE_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
