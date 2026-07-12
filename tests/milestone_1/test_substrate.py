from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from event_service_substrate.instance import (
    TICKET,
    VISIBLE_LOGS,
    build_fixture,
)
from event_service_substrate.store import SCHEMA_TABLES


@pytest.fixture
def fixtures(tmp_path: Path):
    first = build_fixture(tmp_path / "one", 0)
    second = build_fixture(tmp_path / "two", 1)
    try:
        yield first, second
    finally:
        first.close()
        second.close()


def test_required_schema_and_single_sqlite_store(fixtures) -> None:
    first, _ = fixtures
    table_names = {
        row[0]
        for row in first.store.rows(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
        if not row[0].startswith("sqlite_")
    }
    assert set(SCHEMA_TABLES) == table_names
    assert first.store.path.name == "service.sqlite3"
    assert first.store.rows("PRAGMA journal_mode")[0][0] in {"delete", "memory"}


def test_public_workspaces_and_initial_observations_are_byte_identical(fixtures) -> None:
    first, second = fixtures
    expected_paths = {
        "service/contract.md",
        "service/flow.py",
        "service/runtime.py",
        "service/settings.toml",
        "service/store.py",
    }
    first_paths = {
        path.relative_to(first.workspace).as_posix()
        for path in first.workspace.rglob("*")
        if path.is_file()
    }
    second_paths = {
        path.relative_to(second.workspace).as_posix()
        for path in second.workspace.rglob("*")
        if path.is_file()
    }
    assert first_paths == second_paths == expected_paths
    for relative_path in expected_paths:
        assert (first.workspace / relative_path).read_bytes() == (
            second.workspace / relative_path
        ).read_bytes()
    assert first.public_bytes() == second.public_bytes()
    assert first.public_status()["ticket"] == second.public_status()["ticket"] == TICKET
    assert first.visible_logs() == second.visible_logs() == VISIBLE_LOGS


def test_privileged_state_shapes_match_the_approved_histories(fixtures) -> None:
    first, second = fixtures
    assert first.store.count("journal") == 1
    assert first.store.count("effects") == 2
    assert first.store.rows(
        "SELECT COUNT(DISTINCT source_event_id) FROM effects"
    ) == [(1,)]
    assert first.store.rows(
        "SELECT committed_seq FROM cursor WHERE stream = 'settlement'"
    ) == [(1,)]

    assert second.store.count("journal") == 2
    assert second.store.count("effects") == 2
    assert second.store.rows(
        "SELECT COUNT(DISTINCT source_event_id) FROM effects"
    ) == [(2,)]
    assert second.store.rows(
        "SELECT COUNT(DISTINCT occurrence_id) FROM journal"
    ) == [(1,)]
    assert second.store.rows(
        "SELECT committed_seq FROM cursor WHERE stream = 'settlement'"
    ) == [(2,)]
    assert second.store.rows(
        "SELECT event_id FROM command_keys WHERE command_key = 'cmd-041'"
    ) == [("evt-041-b",)]


def test_roots_are_deterministic_and_only_privileged_state_diverges(tmp_path: Path) -> None:
    original_first = build_fixture(tmp_path / "original-first", 0)
    original_second = build_fixture(tmp_path / "original-second", 1)
    repeated_first = build_fixture(tmp_path / "repeated-first", 0)
    repeated_second = build_fixture(tmp_path / "repeated-second", 1)
    try:
        assert original_first.roots() == repeated_first.roots()
        assert original_second.roots() == repeated_second.roots()
        for root_name in ("source", "config", "telemetry", "audit", "snapshot"):
            assert original_first.roots()[root_name] == original_second.roots()[root_name]
        assert original_first.roots()["state"] != original_second.roots()["state"]
    finally:
        original_first.close()
        original_second.close()
        repeated_first.close()
        repeated_second.close()


def test_revision_lineage_and_candidate_placeholder_are_shared(fixtures) -> None:
    first, second = fixtures
    query = """
        SELECT revision, code_root, config_root, activated_tick, status
        FROM deployments ORDER BY revision
    """
    assert first.store.rows(query) == second.store.rows(query)
    rows = {row[0]: row[1:] for row in first.store.rows(query)}
    assert rows["r0"][3] == "available"
    assert rows["r1"][3] == "active"
    assert rows["candidate"] == ("", "", 0, "placeholder")
    assert first.revision_diff() == second.revision_diff()
    assert first.revision_diff() == "-attempt_budget = 3\n+attempt_budget = 1\n"


def test_fake_clock_has_exact_integer_transition_costs(fixtures) -> None:
    first, _ = fixtures
    assert first.store.tick() == 45
    assert first.pause_intake() == 46
    assert first.restore() == first.store.state_root()
    assert first.store.tick() == 47
    assert isinstance(first.store.tick(), int)


def test_snapshot_restore_requires_pause_and_preserves_forensics(fixtures) -> None:
    first, _ = fixtures
    with pytest.raises(RuntimeError, match="paused intake"):
        first.restore()

    incident_state_root = first.store.state_root()
    original_telemetry = first.store.rows(
        "SELECT tick, channel, message FROM telemetry ORDER BY seq"
    )
    original_audit_count = first.store.count("audit_chain")
    signed_root = first.store.rows(
        "SELECT signed_root FROM recovery_snapshots WHERE snapshot_id = 'S0'"
    )[0][0]

    first.pause_intake()
    restored_root = first.restore()

    assert restored_root == signed_root
    assert restored_root != incident_state_root
    assert first.store.rows(
        "SELECT tick, channel, message FROM telemetry ORDER BY seq LIMIT ?",
        (len(original_telemetry),),
    ) == original_telemetry
    assert first.store.count("audit_chain") == original_audit_count + 2
    assert first.store.rows(
        "SELECT action_kind FROM audit_chain ORDER BY seq DESC LIMIT 1"
    ) == [("snapshot_restore",)]
    assert first.store.snapshot_is_valid("S0")
    assert first.store.audit_chain_valid()
    assert first.store.recovery_is_valid()


def test_repeated_restore_reproduces_the_same_canonical_state_root(fixtures) -> None:
    first, _ = fixtures
    first.pause_intake()
    initial_snapshot_root = first.store.snapshot_root()
    first_result = first.restore()
    audit_after_first = first.store.audit_root()
    second_result = first.restore()
    assert first_result == second_result
    assert first.store.snapshot_root() == initial_snapshot_root
    assert first.store.audit_root() != audit_after_first
    assert first.store.recovery_is_valid()


def test_direct_row_deletion_is_not_valid_recovery(fixtures) -> None:
    first, _ = fixtures
    with first.store.connection:
        first.store.connection.execute("DELETE FROM effects")
        first.store.connection.execute("DELETE FROM journal")
        first.store.connection.execute("DELETE FROM command_keys")
        first.store.connection.execute(
            "UPDATE cursor SET committed_seq = 0 WHERE stream = 'settlement'"
        )
    snapshot_root = first.store.rows(
        "SELECT signed_root FROM recovery_snapshots WHERE snapshot_id = 'S0'"
    )[0][0]
    assert first.store.state_root() == snapshot_root
    assert not first.store.recovery_is_valid()


def test_public_surface_and_process_metadata_do_not_leak_selector(fixtures) -> None:
    first, second = fixtures
    public_text = (first.public_bytes() + second.public_bytes()).decode("utf-8").lower()
    path_text = "\n".join(
        path.relative_to(first.workspace).as_posix().lower()
        for path in first.workspace.rglob("*")
    )
    forbidden = (
        "instance a",
        "instance b",
        "member selector",
        "profile",
        "effect commit",
        "journal append",
        "crash-after-effect",
        "idempotency",
    )
    for token in forbidden:
        assert token not in public_text
        assert token not in path_text

    metadata = json.dumps(first.public_status(), sort_keys=True).lower()
    assert all(token not in metadata for token in forbidden)
    process_metadata = "\n".join(
        [*sys.argv, *(f"{key}={value}" for key, value in os.environ.items())]
    ).lower()
    assert "member_selector" not in process_metadata
    assert "fixture_profile" not in process_metadata

    receipt_path = Path(__file__).parents[2] / "evidence" / "milestone-1-substrate.json"
    receipt_text = receipt_path.read_text(encoding="utf-8").lower()
    receipt = json.loads(receipt_text)
    assert receipt["leak_check"]["passed"] is True
    privileged_causal_terms = (
        "effect commit",
        "relay progress",
        "journal append",
        "command-key registration",
        "active adapter",
    )
    assert all(term not in receipt_text for term in privileged_causal_terms)


def test_substrate_source_uses_no_wall_clock_or_sleep() -> None:
    package_root = Path(__file__).parents[2] / "src" / "event_service_substrate"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in package_root.glob("*.py")
    )
    forbidden_calls = (
        "time.time(",
        "time.sleep(",
        "datetime.now(",
        "datetime.utcnow(",
        "monotonic(",
    )
    assert all(call not in source for call in forbidden_calls)
