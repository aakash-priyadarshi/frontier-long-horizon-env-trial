"""Docker smoke for the APEX task pack."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "integrations" / "apex_swe" / "tasks" / "frontier-incident-smoke"


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.returncode == 0


def main() -> int:
    if not docker_available():
        print(
            json.dumps(
                {
                    "status": "NOT VERIFIED",
                    "executed": False,
                    "reason": "docker daemon unavailable",
                }
            )
        )
        print("APEX_DOCKER_SMOKE_NOT_VERIFIED")
        return 0

    # Build from repository root using the task Dockerfile.
    build = subprocess.run(
        [
            "docker",
            "build",
            "-f",
            str(TASK / "Dockerfile"),
            "-t",
            "frontier-incident-smoke:local",
            str(ROOT),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if build.returncode != 0:
        print(build.stdout)
        print(build.stderr)
        print("APEX_DOCKER_SMOKE_FAILED_BUILD")
        return 1

    run = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-e",
            "FRONTIER_ADAPTER_OUT=/tmp/out",
            "frontier-incident-smoke:local",
            "python",
            "/app/integrations/apex_swe/tasks/frontier-incident-smoke/scripted_agent.py",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    print(run.stdout)
    if run.returncode != 0:
        print(run.stderr)
        print("APEX_DOCKER_SMOKE_FAILED")
        return 1
    if "PASSED" not in run.stdout:
        print("APEX_DOCKER_SMOKE_FAILED_MARKER")
        return 1
    print("APEX_DOCKER_SMOKE_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
