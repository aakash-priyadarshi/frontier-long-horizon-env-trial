from __future__ import annotations

from pathlib import Path

import pytest

from event_service_substrate import RecoveryAuthority, build_fixture


TEST_KEYS = (
    bytes.fromhex("03440fb77c3c8ade921d129c2af9ae1006a3e650396cc3af8b3fd7144f8c352f"),
    bytes.fromhex("f7058ef4f5f87d9dbf7ec3a65ce21eb6e19db436df92d4d26d6a3a86e3f2b075"),
)
TEST_SCOPES = (
    "scope-420fac5dc42d4d4b",
    "scope-92e6d8b5acfd47c6",
)


def authority_for_test(index: int) -> RecoveryAuthority:
    return RecoveryAuthority(TEST_KEYS[index], TEST_SCOPES[index])


@pytest.fixture
def fixtures(tmp_path: Path):
    first = build_fixture(tmp_path / "one", 0, authority_for_test(0))
    second = build_fixture(tmp_path / "two", 1, authority_for_test(1))
    try:
        yield first, second
    finally:
        first.close()
        second.close()
