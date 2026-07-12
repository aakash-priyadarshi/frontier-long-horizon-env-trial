from __future__ import annotations

import json

import pytest


SNAPSHOT_COLUMNS = (
    "snapshot_id",
    "state_root",
    "cursor_seq",
    "journal_root",
    "effect_root",
    "payload",
    "auth_tag",
    "created_tick",
)


def _copy_snapshot(source, target) -> None:
    row = source.store.rows(
        f"SELECT {', '.join(SNAPSHOT_COLUMNS)} FROM recovery_snapshots WHERE snapshot_id = 'S0'"
    )[0]
    with target.store.connection:
        target.store.connection.execute("DELETE FROM recovery_snapshots")
        target.store.connection.execute(
            f"INSERT INTO recovery_snapshots({', '.join(SNAPSHOT_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in SNAPSHOT_COLUMNS)})",
            row,
        )


def _reset_to_s0_by_direct_mutation(fixture) -> None:
    document = json.loads(
        fixture.store.rows(
            "SELECT payload FROM recovery_snapshots WHERE snapshot_id = 'S0'"
        )[0][0]
    )
    with fixture.store.connection:
        for table in reversed(document):
            fixture.store.connection.execute(f'DELETE FROM "{table["table"]}"')
        for table in document:
            if not table["rows"]:
                continue
            columns = table["columns"]
            fixture.store.connection.executemany(
                f'INSERT INTO "{table["table"]}" '
                f'({", ".join(columns)}) VALUES ({", ".join("?" for _ in columns)})',
                table["rows"],
            )


def test_restore_requires_pause_and_preserves_forensics(fixtures) -> None:
    first, _ = fixtures
    with pytest.raises(RuntimeError, match="paused intake"):
        first.restore()
    telemetry_before = first.store.rows(
        "SELECT seq, tick, channel, message FROM telemetry ORDER BY seq"
    )
    audit_before = first.store.count("audit_chain")
    expected_root = first.store.rows(
        "SELECT state_root FROM recovery_snapshots WHERE snapshot_id = 'S0'"
    )[0][0]
    first.pause_intake()
    assert first.restore() == expected_root
    assert first.store.rows(
        "SELECT seq, tick, channel, message FROM telemetry ORDER BY seq LIMIT ?",
        (len(telemetry_before),),
    ) == telemetry_before
    assert first.store.count("audit_chain") == audit_before + 2
    assert first.store.count("recovery_proofs") == 1
    assert first.store.audit_chain_valid()
    assert first.store.recovery_is_valid()


def test_snapshot_payload_modification_is_rejected(fixtures) -> None:
    first, _ = fixtures
    with first.store.connection:
        first.store.connection.execute(
            "UPDATE recovery_snapshots SET payload = payload || ' ' WHERE snapshot_id = 'S0'"
        )
    assert not first.store.snapshot_is_valid("S0")
    first.pause_intake()
    with pytest.raises(ValueError, match="authenticated snapshot"):
        first.restore()


def test_snapshot_authentication_tag_modification_is_rejected(fixtures) -> None:
    first, _ = fixtures
    with first.store.connection:
        first.store.connection.execute(
            "UPDATE recovery_snapshots SET auth_tag = ? WHERE snapshot_id = 'S0'",
            ("0" * 64,),
        )
    assert not first.store.snapshot_is_valid("S0")


def test_cross_fixture_snapshot_substitution_is_rejected(fixtures) -> None:
    first, second = fixtures
    assert first.store.snapshot_root() == second.store.snapshot_root()
    first_tag = first.store.rows(
        "SELECT auth_tag FROM recovery_snapshots WHERE snapshot_id = 'S0'"
    )[0][0]
    second_tag = second.store.rows(
        "SELECT auth_tag FROM recovery_snapshots WHERE snapshot_id = 'S0'"
    )[0][0]
    assert first_tag != second_tag
    _copy_snapshot(first, second)
    assert not second.store.snapshot_is_valid("S0")
    second.pause_intake()
    with pytest.raises(ValueError, match="authenticated snapshot"):
        second.restore()


def test_forged_snapshot_insertion_is_rejected(fixtures) -> None:
    first, _ = fixtures
    row = first.store.rows(
        """
        SELECT state_root, cursor_seq, journal_root, effect_root, payload, created_tick
        FROM recovery_snapshots WHERE snapshot_id = 'S0'
        """
    )[0]
    with first.store.connection:
        first.store.connection.execute(
            """
            INSERT INTO recovery_snapshots(
                snapshot_id, state_root, cursor_seq, journal_root, effect_root,
                payload, auth_tag, created_tick
            ) VALUES ('SX', ?, ?, ?, ?, ?, ?, ?)
            """,
            (*row[:-1], "f" * 64, row[-1]),
        )
    assert not first.store.snapshot_is_valid("SX")


def test_direct_mutation_and_forged_audit_cannot_create_recovery(fixtures) -> None:
    first, _ = fixtures
    _reset_to_s0_by_direct_mutation(first)
    assert first.store.state_root() == first.store.rows(
        "SELECT state_root FROM recovery_snapshots WHERE snapshot_id = 'S0'"
    )[0][0]
    entry_hash = first.store.append_audit(
        "snapshot_restore", first.store.state_root(), "operator", first.store.tick()
    )
    audit_seq = first.store.rows("SELECT MAX(seq) FROM audit_chain")[0][0]
    with first.store.connection:
        first.store.connection.execute(
            """
            INSERT INTO recovery_proofs(
                proof_id, snapshot_id, pre_state_root, post_state_root,
                prior_audit_root, action_kind, action_tick, actor_scope,
                audit_seq, audit_entry_hash, auth_tag
            ) VALUES (?, 'S0', ?, ?, ?, 'snapshot_restore', ?, ?, ?, ?, ?)
            """,
            (
                "proof-forged",
                first.store.state_root(),
                first.store.state_root(),
                first.store.audit_root(),
                first.store.tick(),
                "recovery-operator-v1",
                audit_seq,
                entry_hash,
                "0" * 64,
            ),
        )
    assert first.store.audit_chain_valid()
    assert not first.store.recovery_is_valid()


def test_corrupted_prior_audit_chain_blocks_restore_before_mutation(fixtures) -> None:
    first, _ = fixtures
    first.pause_intake()
    service_root_before = first.store.state_root()
    with first.store.connection:
        first.store.connection.execute(
            "UPDATE audit_chain SET entry_hash = ? WHERE seq = 1", ("0" * 64,)
        )
    assert not first.store.audit_chain_valid()
    with pytest.raises(RuntimeError, match="valid audit chain"):
        first.restore()
    assert first.store.state_root() == service_root_before
    assert first.store.count("recovery_proofs") == 0


def test_repeated_restore_produces_same_state_and_valid_latest_proof(fixtures) -> None:
    first, _ = fixtures
    first.pause_intake()
    snapshot_root = first.store.snapshot_root()
    first_state = first.restore()
    first_audit = first.store.audit_root()
    second_state = first.restore()
    assert second_state == first_state
    assert first.store.snapshot_root() == snapshot_root
    assert first.store.audit_root() != first_audit
    assert first.store.count("recovery_proofs") == 2
    assert first.store.recovery_is_valid()
    assert first.store.rows("SELECT seq FROM telemetry ORDER BY seq")[-2:] == [(7,), (8,)]
