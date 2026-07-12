"""SQLite persistence, authenticated recovery, audit chaining, and roots."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Final, Iterable

from .authority import RecoveryAuthority
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
    "recovery_proofs",
    "deployments",
    "audit_chain",
    "runtime_state",
    "telemetry",
    "trace_spans",
)

AUDIT_TABLES: Final[tuple[str, ...]] = ("audit_chain",)
DEPLOYMENT_TABLES: Final[tuple[str, ...]] = ("deployments",)
RUNTIME_TABLES: Final[tuple[str, ...]] = ("runtime_state",)
TELEMETRY_TABLES: Final[tuple[str, ...]] = ("telemetry",)
TRACE_TABLES: Final[tuple[str, ...]] = ("trace_spans",)

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
    logical_effect_key TEXT NOT NULL DEFAULT 'settlement',
    source_event_id TEXT NOT NULL,
    committed_tick INTEGER NOT NULL
);

CREATE TABLE intents (
    intent_id TEXT PRIMARY KEY,
    source_event_id TEXT NOT NULL,
    command_key TEXT NOT NULL,
    occurrence_id TEXT NOT NULL,
    logical_effect_key TEXT NOT NULL,
    created_tick INTEGER NOT NULL,
    state TEXT NOT NULL,
    effect_id TEXT
);

CREATE TABLE event_marks (
    event_id TEXT NOT NULL,
    mark_key TEXT NOT NULL,
    mark_state TEXT NOT NULL,
    PRIMARY KEY (event_id, mark_key)
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
    state_root TEXT NOT NULL,
    cursor_seq INTEGER NOT NULL,
    journal_root TEXT NOT NULL,
    effect_root TEXT NOT NULL,
    payload TEXT NOT NULL,
    auth_tag TEXT NOT NULL,
    created_tick INTEGER NOT NULL
);

CREATE TABLE recovery_proofs (
    proof_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL,
    pre_state_root TEXT NOT NULL,
    post_state_root TEXT NOT NULL,
    prior_audit_root TEXT NOT NULL,
    action_kind TEXT NOT NULL,
    action_tick INTEGER NOT NULL,
    actor_scope TEXT NOT NULL,
    audit_seq INTEGER NOT NULL,
    audit_entry_hash TEXT NOT NULL,
    auth_tag TEXT NOT NULL
);

CREATE TABLE deployments (
    revision TEXT PRIMARY KEY,
    code_root TEXT NOT NULL,
    config_root TEXT NOT NULL,
    config_bytes TEXT NOT NULL,
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
    seq INTEGER PRIMARY KEY,
    tick INTEGER NOT NULL,
    channel TEXT NOT NULL,
    message TEXT NOT NULL
);

CREATE TABLE trace_spans (
    seq INTEGER PRIMARY KEY,
    correlation_handle TEXT NOT NULL,
    span_id TEXT NOT NULL,
    parent_id TEXT,
    workload_id TEXT,
    alias TEXT,
    stage TEXT NOT NULL,
    event_id TEXT,
    command_key TEXT,
    occurrence_id TEXT,
    tick INTEGER NOT NULL
);
"""


class StateStore:
    def __init__(self, path: Path, authority: RecoveryAuthority) -> None:
        self.path = path
        self._authority = authority
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

    def append_telemetry(self, tick: int, channel: str, message: str) -> int:
        next_seq = int(
            self.connection.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM telemetry"
            ).fetchone()[0]
        )
        self.connection.execute(
            "INSERT INTO telemetry(seq, tick, channel, message) VALUES (?, ?, ?, ?)",
            (next_seq, tick, channel, message),
        )
        return next_seq

    def append_trace_span(
        self,
        *,
        correlation_handle: str,
        span_id: str,
        parent_id: str | None,
        workload_id: str | None,
        alias: str | None,
        stage: str,
        event_id: str | None,
        command_key: str | None,
        occurrence_id: str | None,
        tick: int,
    ) -> int:
        next_seq = int(
            self.connection.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM trace_spans"
            ).fetchone()[0]
        )
        self.connection.execute(
            """
            INSERT INTO trace_spans(
                seq, correlation_handle, span_id, parent_id, workload_id, alias,
                stage, event_id, command_key, occurrence_id, tick
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                next_seq,
                correlation_handle,
                span_id,
                parent_id,
                workload_id,
                alias,
                stage,
                event_id,
                command_key,
                occurrence_id,
                tick,
            ),
        )
        return next_seq

    def trace_spans_for_handle(self, correlation_handle: str) -> list[tuple[Any, ...]]:
        return self.rows(
            """
            SELECT seq, span_id, parent_id, workload_id, alias, stage, event_id,
                   command_key, occurrence_id, tick
            FROM trace_spans
            WHERE correlation_handle = ?
            ORDER BY seq
            """,
            (correlation_handle,),
        )

    def trace_handle_exists(self, correlation_handle: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM trace_spans WHERE correlation_handle = ? LIMIT 1",
            (correlation_handle,),
        ).fetchone()
        return row is not None

    def trace_selectors_for_handle(
        self, correlation_handle: str
    ) -> list[dict[str, str | None]]:
        rows = self.connection.execute(
            """
            SELECT DISTINCT event_id, command_key, occurrence_id
            FROM trace_spans
            WHERE correlation_handle = ?
            AND event_id IS NOT NULL
            """,
            (correlation_handle,),
        ).fetchall()
        return [
            {
                "event_id": event_id,
                "command_key": command_key,
                "occurrence_id": occurrence_id,
            }
            for event_id, command_key, occurrence_id in rows
        ]

    def service_document(self) -> list[dict[str, Any]]:
        return table_document(self.connection, SERVICE_TABLES)

    def state_root(self) -> str:
        """Return the canonical service-data root, excluding operational state."""

        return table_root(self.connection, SERVICE_TABLES, "service-state-v1")

    def deployment_root(self) -> str:
        return table_root(self.connection, DEPLOYMENT_TABLES, "deployment-state-v1")

    def runtime_root(self) -> str:
        return table_root(self.connection, RUNTIME_TABLES, "runtime-state-v1")

    def telemetry_root(self) -> str:
        return table_root(self.connection, TELEMETRY_TABLES, "telemetry-v1")

    def audit_root(self) -> str:
        return table_root(self.connection, AUDIT_TABLES, "audit-v1")

    def _audit_root_through(self, maximum_seq: int) -> str:
        columns = [
            row[1]
            for row in self.connection.execute(
                'PRAGMA table_info("audit_chain")'
            ).fetchall()
        ]
        order = ", ".join(f'"{column}"' for column in columns)
        rows = self.connection.execute(
            f'SELECT {order} FROM audit_chain WHERE seq <= ? ORDER BY {order}',
            (maximum_seq,),
        ).fetchall()
        document = [
            {
                "table": "audit_chain",
                "columns": columns,
                "rows": [list(row) for row in rows],
            }
        ]
        return digest("audit-v1", canonical_json(document))

    def snapshot_root(self) -> str:
        columns = (
            "snapshot_id",
            "state_root",
            "cursor_seq",
            "journal_root",
            "effect_root",
            "payload",
            "created_tick",
        )
        order = ", ".join(columns)
        rows = self.connection.execute(
            f"SELECT {order} FROM recovery_snapshots ORDER BY {order}"
        ).fetchall()
        document = [
            {
                "table": "authenticated_snapshot_semantics",
                "columns": list(columns),
                "rows": [list(row) for row in rows],
            }
        ]
        return digest("snapshot-semantics-v1", canonical_json(document))

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
        payload = canonical_json(self.service_document()).decode("utf-8")
        state_root = digest("service-state-v1", payload.encode("utf-8"))
        created_tick = self.tick()
        auth_tag = self._authority.snapshot_tag(
            snapshot_id=snapshot_id,
            state_root=state_root,
            payload=payload,
            created_tick=created_tick,
        )
        cursor_seq = self.connection.execute(
            "SELECT committed_seq FROM cursor WHERE stream = 'settlement'"
        ).fetchone()[0]
        journal_root = table_root(self.connection, ("journal",), "journal-v1")
        effect_root = table_root(self.connection, ("effects",), "effects-v1")
        self.connection.execute(
            """
            INSERT INTO recovery_snapshots(
                snapshot_id, state_root, cursor_seq, journal_root, effect_root,
                payload, auth_tag, created_tick
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                state_root,
                cursor_seq,
                journal_root,
                effect_root,
                payload,
                auth_tag,
                created_tick,
            ),
        )
        self.append_audit("snapshot_create", state_root, "controller", created_tick)
        self.connection.commit()
        return state_root

    def snapshot_is_valid(self, snapshot_id: str) -> bool:
        row = self.connection.execute(
            """
            SELECT state_root, payload, auth_tag, created_tick
            FROM recovery_snapshots WHERE snapshot_id = ?
            """,
            (snapshot_id,),
        ).fetchone()
        if row is None:
            return False
        state_root, payload, auth_tag, created_tick = row
        payload_bytes = payload.encode("utf-8")
        if state_root != digest("service-state-v1", payload_bytes):
            return False
        return self._authority.snapshot_tag_is_valid(
            snapshot_id=snapshot_id,
            state_root=state_root,
            payload=payload,
            created_tick=created_tick,
            auth_tag=auth_tag,
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
        if not self.audit_chain_valid():
            raise RuntimeError("snapshot restoration requires a valid audit chain")
        row = self.connection.execute(
            """
            SELECT state_root, payload FROM recovery_snapshots WHERE snapshot_id = ?
            """,
            (snapshot_id,),
        ).fetchone()
        if row is None or not self.snapshot_is_valid(snapshot_id):
            raise ValueError("authenticated snapshot is missing or invalid")
        snapshot_state_root, payload = row
        document = json.loads(payload)
        pre_state_root = self.state_root()
        prior_audit_root = self.audit_root()
        actor_scope = self._authority.actor_scope
        action_kind = "snapshot_restore"
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
            action_tick = self.advance()
            post_state_root = self.state_root()
            if post_state_root != snapshot_state_root:
                raise RuntimeError("restored state does not match authenticated snapshot")
            audit_entry_hash = self.append_audit(
                action_kind, post_state_root, actor_scope, action_tick
            )
            audit_seq = int(
                self.connection.execute("SELECT MAX(seq) FROM audit_chain").fetchone()[0]
            )
            proof_id = f"proof-{audit_seq:08d}"
            proof_fields = {
                "proof_id": proof_id,
                "snapshot_id": snapshot_id,
                "pre_state_root": pre_state_root,
                "post_state_root": post_state_root,
                "prior_audit_root": prior_audit_root,
                "action_kind": action_kind,
                "action_tick": action_tick,
                "actor_scope": actor_scope,
                "audit_seq": audit_seq,
                "audit_entry_hash": audit_entry_hash,
            }
            auth_tag = self._authority.recovery_tag(proof_fields)
            self.connection.execute(
                """
                INSERT INTO recovery_proofs(
                    proof_id, snapshot_id, pre_state_root, post_state_root,
                    prior_audit_root, action_kind, action_tick, actor_scope,
                    audit_seq, audit_entry_hash, auth_tag
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proof_id,
                    snapshot_id,
                    pre_state_root,
                    post_state_root,
                    prior_audit_root,
                    action_kind,
                    action_tick,
                    actor_scope,
                    audit_seq,
                    audit_entry_hash,
                    auth_tag,
                ),
            )
            self.append_telemetry(
                action_tick, "control", "authenticated snapshot restored"
            )
        return post_state_root

    def recovery_is_valid(self) -> bool:
        if not self.audit_chain_valid():
            return False
        proof = self.connection.execute(
            """
            SELECT proof_id, snapshot_id, pre_state_root, post_state_root,
                   prior_audit_root, action_kind, action_tick, actor_scope,
                   audit_seq, audit_entry_hash, auth_tag
            FROM recovery_proofs ORDER BY audit_seq DESC LIMIT 1
            """
        ).fetchone()
        if proof is None:
            return False
        (
            proof_id,
            snapshot_id,
            pre_state_root,
            post_state_root,
            prior_audit_root,
            action_kind,
            action_tick,
            actor_scope,
            audit_seq,
            audit_entry_hash,
            auth_tag,
        ) = proof
        latest_audit_seq = self.connection.execute(
            "SELECT MAX(seq) FROM audit_chain"
        ).fetchone()[0]
        if latest_audit_seq != audit_seq or self.state_root() != post_state_root:
            return False
        if not self.snapshot_is_valid(snapshot_id):
            return False
        snapshot_state = self.connection.execute(
            "SELECT state_root FROM recovery_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if snapshot_state is None or snapshot_state[0] != post_state_root:
            return False
        proof_fields = {
            "proof_id": proof_id,
            "snapshot_id": snapshot_id,
            "pre_state_root": pre_state_root,
            "post_state_root": post_state_root,
            "prior_audit_root": prior_audit_root,
            "action_kind": action_kind,
            "action_tick": action_tick,
            "actor_scope": actor_scope,
            "audit_seq": audit_seq,
            "audit_entry_hash": audit_entry_hash,
        }
        if not self._authority.recovery_tag_is_valid(proof_fields, auth_tag):
            return False
        audit_entry = self.connection.execute(
            """
            SELECT action_kind, resulting_root, actor, entry_hash, at_tick
            FROM audit_chain WHERE seq = ?
            """,
            (audit_seq,),
        ).fetchone()
        if audit_entry != (
            action_kind,
            post_state_root,
            actor_scope,
            audit_entry_hash,
            action_tick,
        ):
            return False
        return self._audit_root_through(audit_seq - 1) == prior_audit_root

    def recovery_provenance_exists(self) -> bool:
        """Verify a signed recovery proof exists and is internally consistent.

        Unlike ``recovery_is_valid`` this does not require the current service
        state to equal the proof's post-state root, so it remains useful after
        later verification workloads have mutated state.
        """
        if not self.audit_chain_valid():
            return False
        proof = self.connection.execute(
            """
            SELECT proof_id, snapshot_id, pre_state_root, post_state_root,
                   prior_audit_root, action_kind, action_tick, actor_scope,
                   audit_seq, audit_entry_hash, auth_tag
            FROM recovery_proofs ORDER BY audit_seq DESC LIMIT 1
            """
        ).fetchone()
        if proof is None:
            return False
        (
            proof_id,
            snapshot_id,
            pre_state_root,
            post_state_root,
            prior_audit_root,
            action_kind,
            action_tick,
            actor_scope,
            audit_seq,
            audit_entry_hash,
            auth_tag,
        ) = proof
        if not self.snapshot_is_valid(snapshot_id):
            return False
        snapshot_state = self.connection.execute(
            "SELECT state_root FROM recovery_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if snapshot_state is None or snapshot_state[0] != post_state_root:
            return False
        proof_fields = {
            "proof_id": proof_id,
            "snapshot_id": snapshot_id,
            "pre_state_root": pre_state_root,
            "post_state_root": post_state_root,
            "prior_audit_root": prior_audit_root,
            "action_kind": action_kind,
            "action_tick": action_tick,
            "actor_scope": actor_scope,
            "audit_seq": audit_seq,
            "audit_entry_hash": audit_entry_hash,
        }
        if not self._authority.recovery_tag_is_valid(proof_fields, auth_tag):
            return False
        audit_entry = self.connection.execute(
            """
            SELECT action_kind, resulting_root, actor, entry_hash, at_tick
            FROM audit_chain WHERE seq = ?
            """,
            (audit_seq,),
        ).fetchone()
        if audit_entry != (
            action_kind,
            post_state_root,
            actor_scope,
            audit_entry_hash,
            action_tick,
        ):
            return False
        return self._audit_root_through(audit_seq - 1) == prior_audit_root

    def count(self, table_name: str) -> int:
        if table_name not in SCHEMA_TABLES:
            raise ValueError("unknown table")
        return int(
            self.connection.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        )

    def rows(self, query: str, parameters: Iterable[Any] = ()) -> list[tuple[Any, ...]]:
        return self.connection.execute(query, tuple(parameters)).fetchall()

