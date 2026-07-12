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
    log_dir = Path(
        os.environ.get(
            "FRONTIER_ADAPTER_OUT",
            os.environ.get("APEX_CONTAINER_LOGS_PATH", "."),
        )
    )
    verdict = log_dir / "smoke_verdict.txt"
    if verdict.is_file():
        text = verdict.read_text(encoding="utf-8")
        print(text, end="")
        return 0 if "PASSED" in text else 1

    result = run_rollout(
        profile=0, policy=ScriptedRecoveryPolicy(), max_steps=64, require_strict=True
    )
    success = bool(result.success and result.strict_score == 1.0)
    print(format_apex_test_stdout(success), end="")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
