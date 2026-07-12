"""SQLite persistence, snapshots, audit chaining, and canonical roots."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Final, Iterable

from .canonical import canonical_json, digest, table_document, table_root
from .clock import FakeClock


SERVICE_TABLES: Final[tuple[str, ...]] = (
    "journal",
    "cursor",
    "effects",
    "intents",
    "event_marks",
    "command_keys",
)

SCHEMA_TABLES: Final[tuple[str, ...]] = (
    *SERVICE_TABLES,
    "recovery_snapshots",
    "deployments",
    "audit_chain",
    "runtime_state",
    "telemetry",
)

AUDIT_TABLES: Final[tuple[str, ...]] = ("audit_chain",)
TELEMETRY_TABLES: Final[tuple[str, ...]] = ("telemetry",)
SNAPSHOT_TABLES: Final[tuple[str, ...]] = ("recovery_snapshots",)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE journal (
    seq INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    command_key TEXT NOT NULL,
    occurrence_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    accepted_tick INTEGER NOT NULL
);

CREATE TABLE cursor (
    stream TEXT PRIMARY KEY,
    committed_seq INTEGER NOT NULL
);

CREATE TABLE effects (
    effect_id TEXT PRIMARY KEY,
    occurrence_id TEXT NOT NULL,
    amount INTEGER NOT NULL,
    kind TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    committed_tick INTEGER NOT NULL
);

CREATE TABLE intents (
    intent_id TEXT PRIMARY KEY,
    source_event_id TEXT NOT NULL,
    occurrence_id TEXT NOT NULL,
    state TEXT NOT NULL
);

CREATE TABLE event_marks (
    event_id TEXT PRIMARY KEY,
    mark_state TEXT NOT NULL
);

CREATE TABLE command_keys (
    command_key TEXT NOT NULL,
    occurrence_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    state TEXT NOT NULL,
    PRIMARY KEY (command_key, occurrence_id)
);

CREATE TABLE recovery_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    signed_root TEXT NOT NULL,
    cursor_seq INTEGER NOT NULL,
    journal_root TEXT NOT NULL,
    effect_root TEXT NOT NULL,
    payload TEXT NOT NULL,
    signature TEXT NOT NULL,
    created_tick INTEGER NOT NULL
);

CREATE TABLE deployments (
    revision TEXT PRIMARY KEY,
    code_root TEXT NOT NULL,
    config_root TEXT NOT NULL,
    activated_tick INTEGER NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE audit_chain (
    seq INTEGER PRIMARY KEY,
    action_kind TEXT NOT NULL,
    prior_root TEXT NOT NULL,
    resulting_root TEXT NOT NULL,
    actor TEXT NOT NULL,
    entry_hash TEXT NOT NULL,
    at_tick INTEGER NOT NULL
);

CREATE TABLE runtime_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE telemetry (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    tick INTEGER NOT NULL,
    channel TEXT NOT NULL,
    message TEXT NOT NULL
);
"""


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self.connection.close()

    def initialize(self) -> None:
        self.connection.executescript(SCHEMA)
        self.connection.execute(
            "INSERT INTO cursor(stream, committed_seq) VALUES (?, ?)",
            ("settlement", 0),
        )
        self.connection.executemany(
            "INSERT INTO runtime_state(key, value) VALUES (?, ?)",
            (("fake_tick", "40"), ("intake_state", "open")),
        )
        self.connection.commit()

    def clock(self) -> FakeClock:
        row = self.connection.execute(
            "SELECT value FROM runtime_state WHERE key = 'fake_tick'"
        ).fetchone()
        if row is None:
            raise RuntimeError("fake clock is not initialized")
        return FakeClock(int(row[0]))

    def tick(self) -> int:
        return self.clock().tick

    def advance(self, transitions: int = 1) -> int:
        clock = self.clock()
        tick = clock.advance(transitions)
        self.connection.execute(
            "UPDATE runtime_state SET value = ? WHERE key = 'fake_tick'",
            (str(tick),),
        )
        return tick

    def runtime_value(self, key: str) -> str:
        row = self.connection.execute(
            "SELECT value FROM runtime_state WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            raise KeyError(key)
        return str(row[0])

    def set_runtime_value(self, key: str, value: str) -> None:
        self.connection.execute(
            "UPDATE runtime_state SET value = ? WHERE key = ?", (value, key)
        )

    def append_telemetry(self, tick: int, channel: str, message: str) -> None:
        self.connection.execute(
            "INSERT INTO telemetry(tick, channel, message) VALUES (?, ?, ?)",
            (tick, channel, message),
        )

    def service_document(self) -> list[dict[str, Any]]:
        return table_document(self.connection, SERVICE_TABLES)

    def state_root(self) -> str:
        return table_root(self.connection, SERVICE_TABLES, "service-state-v1")

    def telemetry_root(self) -> str:
        return table_root(self.connection, TELEMETRY_TABLES, "telemetry-v1")

    def audit_root(self) -> str:
        return table_root(self.connection, AUDIT_TABLES, "audit-v1")

    def snapshot_root(self) -> str:
        return table_root(self.connection, SNAPSHOT_TABLES, "snapshots-v1")

    def append_audit(
        self,
        action_kind: str,
        resulting_root: str,
        actor: str,
        at_tick: int,
    ) -> str:
        prior = self.connection.execute(
            "SELECT entry_hash FROM audit_chain ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prior_root = prior[0] if prior else digest("audit-genesis-v1", b"")
        next_seq = self.connection.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM audit_chain"
        ).fetchone()[0]
        fields = {
            "seq": next_seq,
            "action_kind": action_kind,
            "prior_root": prior_root,
            "resulting_root": resulting_root,
            "actor": actor,
            "at_tick": at_tick,
        }
        entry_hash = digest("audit-entry-v1", canonical_json(fields))
        self.connection.execute(
            """
            INSERT INTO audit_chain(
                seq, action_kind, prior_root, resulting_root, actor, entry_hash, at_tick
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                next_seq,
                action_kind,
                prior_root,
                resulting_root,
                actor,
                entry_hash,
                at_tick,
            ),
        )
        return entry_hash

    def audit_chain_valid(self) -> bool:
        expected_prior = digest("audit-genesis-v1", b"")
        rows = self.connection.execute(
            """
            SELECT seq, action_kind, prior_root, resulting_root, actor, entry_hash, at_tick
            FROM audit_chain ORDER BY seq
            """
        ).fetchall()
        for row in rows:
            seq, action_kind, prior_root, resulting_root, actor, entry_hash, at_tick = row
            fields = {
                "seq": seq,
                "action_kind": action_kind,
                "prior_root": prior_root,
                "resulting_root": resulting_root,
                "actor": actor,
                "at_tick": at_tick,
            }
            if prior_root != expected_prior:
                return False
            if entry_hash != digest("audit-entry-v1", canonical_json(fields)):
                return False
            expected_prior = entry_hash
        return True

    def create_snapshot(self, snapshot_id: str) -> str:
        payload_bytes = canonical_json(self.service_document())
        signed_root = digest("service-state-v1", payload_bytes)
        signature = digest("local-snapshot-signature-v1", payload_bytes)
        cursor_seq = self.connection.execute(
            "SELECT committed_seq FROM cursor WHERE stream = 'settlement'"
        ).fetchone()[0]
        journal_root = table_root(self.connection, ("journal",), "journal-v1")
        effect_root = table_root(self.connection, ("effects",), "effects-v1")
        self.connection.execute(
            """
            INSERT INTO recovery_snapshots(
                snapshot_id, signed_root, cursor_seq, journal_root, effect_root,
                payload, signature, created_tick
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                signed_root,
                cursor_seq,
                journal_root,
                effect_root,
                payload_bytes.decode("utf-8"),
                signature,
                self.tick(),
            ),
        )
        self.append_audit("snapshot_create", signed_root, "controller", self.tick())
        self.connection.commit()
        return signed_root

    def snapshot_is_valid(self, snapshot_id: str) -> bool:
        row = self.connection.execute(
            "SELECT signed_root, payload, signature FROM recovery_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            return False
        signed_root, payload, signature = row
        payload_bytes = payload.encode("utf-8")
        return (
            signed_root == digest("service-state-v1", payload_bytes)
            and signature == digest("local-snapshot-signature-v1", payload_bytes)
        )

    def pause_intake(self) -> int:
        if self.runtime_value("intake_state") != "open":
            raise RuntimeError("intake is not open")
        tick = self.advance()
        self.set_runtime_value("intake_state", "paused")
        self.append_audit("intake_pause", self.state_root(), "operator", tick)
        self.append_telemetry(tick, "control", "intake paused")
        self.connection.commit()
        return tick

    def restore_snapshot(self, snapshot_id: str) -> str:
        if self.runtime_value("intake_state") != "paused":
            raise RuntimeError("snapshot restoration requires paused intake")
        row = self.connection.execute(
            "SELECT payload FROM recovery_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if row is None or not self.snapshot_is_valid(snapshot_id):
            raise ValueError("snapshot is missing or invalid")
        document = json.loads(row[0])
        with self.connection:
            for table_name in reversed(SERVICE_TABLES):
                self.connection.execute(f'DELETE FROM "{table_name}"')
            for table in document:
                columns = table["columns"]
                if not table["rows"]:
                    continue
                column_sql = ", ".join(f'"{column}"' for column in columns)
                placeholders = ", ".join("?" for _ in columns)
                self.connection.executemany(
                    f'INSERT INTO "{table["table"]}" ({column_sql}) VALUES ({placeholders})',
                    table["rows"],
                )
            tick = self.advance()
            resulting_root = self.state_root()
            self.append_audit("snapshot_restore", resulting_root, "operator", tick)
            self.append_telemetry(tick, "control", "signed snapshot restored")
        return resulting_root

    def recovery_is_valid(self) -> bool:
        latest = self.connection.execute(
            """
            SELECT action_kind, resulting_root
            FROM audit_chain ORDER BY seq DESC LIMIT 1
            """
        ).fetchone()
        if latest is None or latest[0] != "snapshot_restore":
            return False
        matching_snapshot = self.connection.execute(
            "SELECT snapshot_id FROM recovery_snapshots WHERE signed_root = ?",
            (latest[1],),
        ).fetchone()
        return (
            latest[1] == self.state_root()
            and matching_snapshot is not None
            and self.snapshot_is_valid(matching_snapshot[0])
            and self.audit_chain_valid()
        )

    def count(self, table_name: str) -> int:
        if table_name not in SCHEMA_TABLES:
            raise ValueError("unknown table")
        return int(
            self.connection.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        )

    def rows(self, query: str, parameters: Iterable[Any] = ()) -> list[tuple[Any, ...]]:
        return self.connection.execute(query, tuple(parameters)).fetchall()

