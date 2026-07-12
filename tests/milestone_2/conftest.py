from __future__ import annotations

from pathlib import Path

import pytest

from event_service_substrate import RecoveryAuthority, build_fixture
from agent_surface import ToolGateway


TEST_KEYS = (
    bytes.fromhex("03440fb77c3c8ade921d129c2af9ae1006a3e650396cc3af8b3fd7144f8c352f"),
    bytes.fromhex("f7058ef4f5f87d9dbf7ec3a65ce21eb6e19db436df92d4d26d6a3a86e3f2b075"),
)
TEST_SCOPES = (
    "scope-420fac5dc42d4d4b",
    "scope-92e6d8b5acfd47c6",
)


def _authority(index: int) -> RecoveryAuthority:
    return RecoveryAuthority(TEST_KEYS[index], TEST_SCOPES[index])


@pytest.fixture
def sessions(tmp_path: Path):
    session_0_dir = tmp_path / "session-0"
    fixture_0_dir = tmp_path / "fixture-0"
    session_1_dir = tmp_path / "session-1"
    fixture_1_dir = tmp_path / "fixture-1"
    with (
        ToolGateway(0, session_0_dir, fixture_0_dir, _authority(0)) as session_0,
        ToolGateway(1, session_1_dir, fixture_1_dir, _authority(1)) as session_1,
    ):
        yield session_0, session_1
