from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from event_service_substrate import RecoveryAuthority, build_fixture  # noqa: E402


KEYS = (
    bytes.fromhex("56b31d68369ba259e6cd87c663f7f3a1d4f1eb1cb1d086f824f42234fb10cb2a"),
    bytes.fromhex("dde3ad72715bf628156ac0932af09179d5af9d93ed871bd6d46a9e1a110d730d"),
)
SCOPES = ("scope-361e9098788346b0", "scope-a1631f1f6f8d43f0")


with tempfile.TemporaryDirectory(prefix="process-probe-") as directory:
    root = Path(directory)
    fixtures = (
        build_fixture(root / "one", 0, RecoveryAuthority(KEYS[0], SCOPES[0])),
        build_fixture(root / "two", 1, RecoveryAuthority(KEYS[1], SCOPES[1])),
    )
    try:
        print(json.dumps([fixture.roots() for fixture in fixtures], sort_keys=True))
    finally:
        for fixture in fixtures:
            fixture.close()
