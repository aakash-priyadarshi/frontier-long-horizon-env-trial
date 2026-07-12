#!/usr/bin/env python3
"""APEX-compatible verifier for the frontier incident smoke task."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from training_adapters.apex_compat import format_apex_test_stdout  # noqa: E402
from training_adapters.rollout import ScriptedRecoveryPolicy, run_rollout  # noqa: E402


def main() -> int:
    # Prefer an existing scripted receipt when the agent already ran.
    log_dir = Path(os.environ.get("FRONTIER_ADAPTER_OUT", os.environ.get("APEX_CONTAINER_LOGS_PATH", ".")))
    verdict = log_dir / "smoke_verdict.txt"
    if verdict.is_file():
        text = verdict.read_text(encoding="utf-8")
        print(text, end="")
        return 0 if "PASSED" in text else 1

    # Otherwise execute the scripted public recovery path in-process.
    result = run_rollout(profile=0, policy=ScriptedRecoveryPolicy(), max_steps=16)
    print(format_apex_test_stdout(result.success), end="")
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
