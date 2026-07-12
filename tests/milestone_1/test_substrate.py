from __future__ import annotations

import re
from pathlib import Path

import pytest

from event_service_substrate import build_fixture
from event_service_substrate.canonical import digest
from event_service_substrate.instance import TICKET, VISIBLE_LOGS
from event_service_substrate.store import SCHEMA_TABLES

from .conftest import authority_for_test


def test_required_schema_and_explicit_telemetry_sequence(fixtures) -> None:
    first, _ = fixtures
    table_names = {
        row[0]
        for row in first.store.rows(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
        if not row[0].startswith("sqlite_")
    }
    assert set(SCHEMA_TABLES) == table_names
    assert "sqlite_sequence" not in table_names
    telemetry_sql = first.store.rows(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'telemetry'"
    )[0][0]
    assert "AUTOINCREMENT" not in telemetry_sql.upper()
    assert first.store.rows("SELECT seq FROM telemetry ORDER BY seq") == [
        (1,),
        (2,),
        (3,),
        (4,),
        (5,),
    ]


def test_public_workspaces_and_initial_observations_are_byte_identical(fixtures) -> None:
    first, second = fixtures
    expected_paths = {
        "service/contract.md",
        "service/flow.py",
        "service/runtime.py",
        "service/settings.toml",
        "service/store.py",
    }
    for fixture in (first, second):
        assert {
            path.relative_to(fixture.workspace).as_posix()
            for path in fixture.workspace.rglob("*")
            if path.is_file()
        } == expected_paths
    for relative_path in expected_paths:
        assert (first.workspace / relative_path).read_bytes() == (
            second.workspace / relative_path
        ).read_bytes()
    assert first.public_bytes() == second.public_bytes()
    assert first.public_status()["ticket"] == second.public_status()["ticket"] == TICKET
    assert first.visible_logs() == second.visible_logs() == VISIBLE_LOGS
    assert first.revision_diff() == second.revision_diff()


def test_privileged_histories_use_opaque_identifiers(fixtures) -> None:
    first, second = fixtures
    identifier_pattern = re.compile(r"^(evt|efx|cmd|occ)_[0-9a-f]{32}$")
    first_events = [row[0] for row in first.store.rows("SELECT event_id FROM journal")]
    second_events = [row[0] for row in second.store.rows("SELECT event_id FROM journal")]
    effects = [
        row[0]
        for fixture in (first, second)
        for row in fixture.store.rows("SELECT effect_id FROM effects")
    ]
    lineage = [
        value
        for fixture in (first, second)
        for row in fixture.store.rows(
            "SELECT command_key, occurrence_id FROM journal ORDER BY seq"
        )
        for value in row
    ]
    assert len(first_events) == 1
    assert len(second_events) == 2
    assert first_events[0] == second_events[0]
    assert second_events[1] != second_events[0]
    assert all(identifier_pattern.fullmatch(value) for value in first_events + second_events)
    assert all(identifier_pattern.fullmatch(value) for value in effects + lineage)
    assert all(not re.search(r"-[ab]\d?$", value) for value in first_events + second_events + effects)
    assert first.store.rows("SELECT COUNT(DISTINCT source_event_id) FROM effects") == [(1,)]
    assert second.store.rows("SELECT COUNT(DISTINCT source_event_id) FROM effects") == [(2,)]


def test_roots_are_deterministic_and_only_service_state_diverges(tmp_path: Path) -> None:
    originals = (
        build_fixture(tmp_path / "original-1", 0, authority_for_test(0)),
        build_fixture(tmp_path / "original-2", 1, authority_for_test(1)),
    )
    repeats = (
        build_fixture(tmp_path / "repeat-1", 0, authority_for_test(0)),
        build_fixture(tmp_path / "repeat-2", 1, authority_for_test(1)),
    )
    try:
        assert originals[0].roots() == repeats[0].roots()
        assert originals[1].roots() == repeats[1].roots()
        for name in (
            "source",
            "config",
            "deployment",
            "runtime",
            "telemetry",
            "audit",
            "snapshot",
        ):
            assert originals[0].roots()[name] == originals[1].roots()[name]
        assert originals[0].roots()["service_state"] != originals[1].roots()[
            "service_state"
        ]
    finally:
        for fixture in (*originals, *repeats):
            fixture.close()


def test_revision_artifacts_have_matching_roots_and_candidate_placeholder(fixtures) -> None:
    first, second = fixtures
    query = """
        SELECT revision, code_root, config_root, config_bytes, activated_tick, status
        FROM deployments ORDER BY revision
    """
    assert first.store.rows(query) == second.store.rows(query)
    for revision, _, config_root, config_text, _, _ in first.store.rows(query):
        assert config_root == digest("config-v1", config_text.encode("utf-8")), revision
    candidate = [row for row in first.store.rows(query) if row[0] == "candidate"][0]
    assert candidate[-1] == "placeholder"
    assert candidate[3] == ""


def test_attempt_budget_and_revision_diff_are_artifact_derived(fixtures) -> None:
    first, _ = fixtures
    service_root_before = first.store.state_root()
    deployment_root_before = first.store.deployment_root()
    diff_before = first.revision_diff()
    config_text = first.store.rows(
        "SELECT config_bytes FROM deployments WHERE revision = 'r1'"
    )[0][0].replace("attempt_budget = 1", "attempt_budget = 2")
    config_root = digest("config-v1", config_text.encode("utf-8"))
    with first.store.connection:
        first.store.connection.execute(
            """
            UPDATE deployments SET config_bytes = ?, config_root = ? WHERE revision = 'r1'
            """,
            (config_text, config_root),
        )
    assert first.public_status()["attempt_budget"] == 2
    assert first.public_status()["active_config_root"] == config_root
    assert first.revision_diff() != diff_before
    assert first.store.deployment_root() != deployment_root_before
    assert first.store.state_root() == service_root_before


def test_mismatched_revision_root_is_rejected(fixtures) -> None:
    first, _ = fixtures
    with first.store.connection:
        first.store.connection.execute(
            "UPDATE deployments SET config_bytes = config_bytes || ' ' WHERE revision = 'r1'"
        )
    with pytest.raises(RuntimeError, match="root does not match"):
        first.public_status()


def test_deployment_and_runtime_roots_are_operationally_distinct(fixtures) -> None:
    first, _ = fixtures
    service_root = first.store.state_root()
    deployment_root = first.store.deployment_root()
    runtime_root = first.store.runtime_root()
    with first.store.connection:
        first.store.connection.execute(
            "UPDATE deployments SET status = 'available' WHERE revision = 'r1'"
        )
        first.store.connection.execute(
            "UPDATE deployments SET status = 'active' WHERE revision = 'r0'"
        )
    assert first.store.deployment_root() != deployment_root
    assert first.store.runtime_root() == runtime_root
    assert first.store.state_root() == service_root

    deployment_root = first.store.deployment_root()
    first.store.advance()
    first.store.set_runtime_value("intake_state", "paused")
    first.store.connection.commit()
    assert first.store.runtime_root() != runtime_root
    assert first.store.deployment_root() == deployment_root
    assert first.store.state_root() == service_root


def test_fake_clock_and_restore_have_exact_sequence_costs(fixtures) -> None:
    first, _ = fixtures
    assert first.store.tick() == 45
    assert first.pause_intake() == 46
    assert first.restore() == first.store.state_root()
    assert first.store.tick() == 47
    assert first.store.rows("SELECT seq FROM telemetry ORDER BY seq") == [
        (1,),
        (2,),
        (3,),
        (4,),
        (5,),
        (6,),
        (7,),
    ]


def test_snapshot_predates_incident_acceptance(fixtures) -> None:
    first, second = fixtures
    for fixture in (first, second):
        created_tick = fixture.store.rows(
            "SELECT created_tick FROM recovery_snapshots WHERE snapshot_id = 'S0'"
        )[0][0]
        accepted_tick = fixture.store.rows("SELECT MIN(accepted_tick) FROM journal")[0][0]
        assert created_tick < accepted_tick


def test_substrate_source_uses_no_wall_clock_or_sleep() -> None:
    package_root = Path(__file__).parents[2] / "src" / "event_service_substrate"
    source = "\n".join(path.read_text(encoding="utf-8") for path in package_root.glob("*.py"))
    forbidden_calls = (
        "time.time(",
        "time.sleep(",
        "datetime.now(",
        "datetime.utcnow(",
        "monotonic(",
    )
    assert all(call not in source for call in forbidden_calls)
