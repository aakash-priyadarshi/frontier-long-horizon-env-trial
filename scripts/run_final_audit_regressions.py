"""Run only the executable regressions derived from the final adversarial audit."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pytest_args", nargs="*")
    args = parser.parse_args(argv)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/final_audit",
        "-q",
        "--tb=no",
        "-ra",
        *args.pytest_args,
    ]
    print("command:", subprocess.list2cmdline(command), flush=True)
    completed = subprocess.run(command, cwd=REPOSITORY_ROOT, check=False)
    outcome = "PASS" if completed.returncode == 0 else "FAIL"
    print(f"final-audit regressions: {outcome} (exit {completed.returncode})")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
