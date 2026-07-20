"""Isolated SQLite persistence for safe public records and private artifacts."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from evaluation_service.events import EvaluationEvent

from drone_decision_verifier.leak_detection import assert_public_safe

from .manifests import canonical_json, content_digest, write_immutable_json


# Additive: v3 records may carry external_llm / scripted_external_baseline
# configuration and provenance fields inside existing JSON payloads.
TALON_STORE_SCHEMA_VERSION = 3
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted", "timed_out"})
ACTIVE_STATUSES = frozenset({"queued", "running", "cancelling"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class TalonImmutableRecordError(RuntimeError):
    pass


class TalonIdempotencyConflict(RuntimeError):
    pass


class TalonStore:
    def __init__(self, path: Path | str, *, event_replay_limit: int = 1_000) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.records_dir = self.path.parent / "records"
        self.private_dir = self.path.parent / "private"
        self.quarantine_dir = self.path.parent / ".deletion-quarantine"
        for directory in (self.records_dir, self.private_dir, self.quarantine_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self._event_replay_limit = event_replay_limit
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._migrate()
        self.recover_deletions()

    def _migrate(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS talon_schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS talon_records (
                    record_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    digest TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_talon_records_kind
                    ON talon_records(kind, created_at DESC);
                CREATE TABLE IF NOT EXISTS talon_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope_type TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    data_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_talon_events_scope
                    ON talon_events(scope_type, scope_id, event_id);
                CREATE TABLE IF NOT EXISTS talon_terminal_events (
                    scope_id TEXT PRIMARY KEY,
                    event_id INTEGER NOT NULL REFERENCES talon_events(event_id)
                );
                CREATE TABLE IF NOT EXISTS talon_idempotency (
                    operation TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(operation, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS talon_dependencies (
                    record_id TEXT NOT NULL,
                    depends_on TEXT NOT NULL,
                    PRIMARY KEY(record_id, depends_on),
                    FOREIGN KEY(record_id) REFERENCES talon_records(record_id) ON DELETE CASCADE,
                    FOREIGN KEY(depends_on) REFERENCES talon_records(record_id) ON DELETE RESTRICT
                );
                CREATE TABLE IF NOT EXISTS talon_deletion_plans (
                    record_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    planned_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS talon_checkpoint_health (
                    record_id TEXT PRIMARY KEY,
                    available INTEGER NOT NULL,
                    reason TEXT,
                    checked_at TEXT NOT NULL
                );
                """
            )
            current = self._connection.execute(
                "SELECT value FROM talon_schema_meta WHERE key='schema_version'"
            ).fetchone()
            if current and int(current[0]) > TALON_STORE_SCHEMA_VERSION:
                raise RuntimeError("Talon database schema is newer than this application")
            self._connection.execute(
                "INSERT OR REPLACE INTO talon_schema_meta(key,value) VALUES('schema_version',?)",
                (str(TALON_STORE_SCHEMA_VERSION),),
            )

    @property
    def schema_version(self) -> int:
        return TALON_STORE_SCHEMA_VERSION

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _safe_directory(self, root: Path, record_id: str) -> Path:
        if not record_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in record_id):
            raise ValueError("invalid Talon record identifier")
        base = root.resolve()
        target = (root / record_id).resolve()
        if target.parent != base:
            raise ValueError("invalid Talon record identifier")
        return target

    def _record_directory(self, record_id: str) -> Path:
        return self._safe_directory(self.records_dir, record_id)

    def _private_directory(self, record_id: str) -> Path:
        return self._safe_directory(self.private_dir, record_id)

    def create_record(
        self,
        record_id: str,
        kind: str,
        payload: dict[str, Any],
        *,
        status: str = "queued",
        depends_on: tuple[str, ...] = (),
    ) -> None:
        assert_public_safe(payload)
        now = utc_now()
        record_payload = {**payload, "record_id": record_id, "kind": kind, "status": status, "created_at": now}
        public_directory = self._record_directory(record_id)
        private_directory = self._private_directory(record_id)
        public_directory.mkdir(parents=True, exist_ok=False)
        try:
            private_directory.mkdir(parents=True, exist_ok=False)
            try:
                private_directory.chmod(0o700)
            except OSError:
                pass
            with self._lock, self._connection:
                self._connection.execute(
                    "INSERT INTO talon_records VALUES(?,?,?,?,?,?,NULL)",
                    (record_id, kind, status, now, now, canonical_json(record_payload)),
                )
                for dependency in depends_on:
                    self._connection.execute(
                        "INSERT INTO talon_dependencies(record_id,depends_on) VALUES(?,?)",
                        (record_id, dependency),
                    )
        except Exception:
            shutil.rmtree(public_directory, ignore_errors=True)
            shutil.rmtree(private_directory, ignore_errors=True)
            raise

    def resolve_idempotency(
        self,
        operation: str,
        key: str | None,
        request_payload: dict[str, Any],
    ) -> str | None:
        if key is None:
            return None
        if not (8 <= len(key) <= 128) or any(ord(character) < 33 or ord(character) > 126 for character in key):
            raise ValueError("idempotency key must be 8-128 visible ASCII characters")
        digest = content_digest(request_payload)
        with self._lock:
            row = self._connection.execute(
                "SELECT request_digest,record_id FROM talon_idempotency WHERE operation=? AND idempotency_key=?",
                (operation, key),
            ).fetchone()
        if row is None:
            return None
        if row["request_digest"] != digest:
            raise TalonIdempotencyConflict("idempotency key was reused with a different request")
        return str(row["record_id"])

    def bind_idempotency(self, operation: str, key: str | None, request_payload: dict[str, Any], record_id: str) -> str:
        if key is None:
            return record_id
        digest = content_digest(request_payload)
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    "INSERT INTO talon_idempotency VALUES(?,?,?,?,?)",
                    (operation, key, digest, record_id, utc_now()),
                )
            return record_id
        except sqlite3.IntegrityError:
            existing = self.resolve_idempotency(operation, key, request_payload)
            if existing is None:
                raise
            return existing

    def update(self, record_id: str, status: str, updates: dict[str, Any]) -> None:
        assert_public_safe(updates)
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT status,payload_json FROM talon_records WHERE record_id=?", (record_id,)
            ).fetchone()
            if row is None:
                raise KeyError(record_id)
            if row["status"] in TERMINAL_STATUSES:
                raise TalonImmutableRecordError("terminal Talon records are immutable")
            payload = json.loads(row["payload_json"])
            payload.update(updates)
            payload["status"] = status
            self._connection.execute(
                "UPDATE talon_records SET status=?,updated_at=?,payload_json=? WHERE record_id=? AND status NOT IN ('completed','failed','cancelled','interrupted','timed_out')",
                (status, utc_now(), canonical_json(payload), record_id),
            )

    def finalize(self, record_id: str, status: str, result: dict[str, Any]) -> str:
        if status not in TERMINAL_STATUSES:
            raise ValueError("final Talon status must be terminal")
        with self._lock:
            row = self._connection.execute(
                "SELECT status FROM talon_records WHERE record_id=?", (record_id,)
            ).fetchone()
            if row is None:
                raise KeyError(record_id)
            if row["status"] in TERMINAL_STATUSES:
                raise TalonImmutableRecordError("terminal Talon records are immutable")
        digest = self._try_finalize(
            record_id,
            status,
            result,
            expected_statuses=ACTIVE_STATUSES,
        )
        if digest is None:
            raise TalonImmutableRecordError("another terminal outcome won the race")
        return digest

    def try_complete_with_checkpoint(
        self,
        record_id: str,
        *,
        result: dict[str, Any],
        expected_statuses: frozenset[str] | None = None,
    ) -> str | None:
        """Compare-and-set a run to ``completed`` with checkpoint metadata.

        Succeeds only when the current status is in ``expected_statuses``
        (default: all active statuses, including ``cancelling``). A worker that
        already published after its own cancel re-check can therefore still win
        over soft-cancel. Returns the record digest on success, or ``None`` when
        a terminal outcome already won / the status is outside the expected set.
        """

        allowed = ACTIVE_STATUSES if expected_statuses is None else frozenset(expected_statuses)
        if not allowed:
            raise ValueError("expected_statuses must not be empty")
        if allowed - ACTIVE_STATUSES:
            raise ValueError("expected_statuses may only include active Talon statuses")
        return self._try_finalize(record_id, "completed", result, expected_statuses=allowed)

    def _try_finalize(
        self,
        record_id: str,
        status: str,
        result: dict[str, Any],
        *,
        expected_statuses: frozenset[str],
    ) -> str | None:
        assert_public_safe(result)
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT status,payload_json FROM talon_records WHERE record_id=?", (record_id,)
            ).fetchone()
            if row is None:
                raise KeyError(record_id)
            if row["status"] in TERMINAL_STATUSES:
                return None
            if row["status"] not in expected_statuses:
                return None
            payload = json.loads(row["payload_json"])
            payload.update(result)
            payload["status"] = status
            payload["ended_at"] = utc_now()
            payload["payload_digest"] = content_digest(payload)
            record_digest = content_digest(payload)
            payload["record_digest"] = record_digest
            artifact = self._record_directory(record_id) / "result.json"
            if artifact.exists():
                # A prior process may have died after the atomic file write but
                # before the SQLite commit. The active database row remains the
                # authority, so the orphan cannot be treated as terminal.
                artifact.unlink()
            write_immutable_json(artifact, payload)
            placeholders = ",".join("?" for _ in expected_statuses)
            cursor = self._connection.execute(
                f"UPDATE talon_records SET status=?,updated_at=?,payload_json=?,digest=? "
                f"WHERE record_id=? AND status IN ({placeholders})",
                (status, utc_now(), canonical_json(payload), record_digest, record_id, *sorted(expected_statuses)),
            )
            if cursor.rowcount != 1:
                artifact.unlink(missing_ok=True)
                return None
            return record_digest

    def write_private_artifact(self, record_id: str, name: str, payload: dict[str, Any]) -> str:
        if not name.endswith(".json") or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in name):
            raise ValueError("invalid private artifact name")
        target = self._private_directory(record_id) / name
        write_immutable_json(target, payload)
        try:
            target.chmod(0o600)
        except OSError:
            pass
        return content_digest(payload)

    def read_private_artifact(self, record_id: str, name: str) -> dict[str, Any]:
        target = (self._private_directory(record_id) / name).resolve()
        if target.parent != self._private_directory(record_id).resolve() or not target.is_file():
            raise FileNotFoundError(name)
        return json.loads(target.read_text(encoding="utf-8"))

    def get(self, record_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload_json,digest FROM talon_records WHERE record_id=?", (record_id,)
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        if row["digest"] is not None:
            bound_digest = str(row["digest"])
            recomputed = content_digest({key: value for key, value in payload.items() if key != "record_digest"})
            if payload.get("record_digest") != bound_digest or recomputed != bound_digest:
                raise TalonImmutableRecordError("Talon record digest binding is corrupt")
            payload_without_digests = {key: value for key, value in payload.items() if key not in {"payload_digest", "record_digest"}}
            if payload.get("payload_digest") != content_digest(payload_without_digests):
                raise TalonImmutableRecordError("Talon terminal payload digest is corrupt")
        assert_public_safe(payload)
        if payload.get("kind") == "training" and payload.get("status") == "completed":
            # Health is stored outside the immutable payload digest so restart
            # reconciliation can mark missing/invalid files unavailable.
            if not self.checkpoint_is_available(record_id):
                payload = {**payload, "checkpoint_unavailable": True}
        return payload

    def list(self, *, kind: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        where = " WHERE kind=?" if kind is not None else ""
        params: tuple[Any, ...] = (kind,) if kind is not None else ()
        with self._lock:
            total = int(self._connection.execute(f"SELECT COUNT(*) FROM talon_records{where}", params).fetchone()[0])
            rows = self._connection.execute(
                f"SELECT record_id FROM talon_records{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        records = [self.get(str(row[0])) for row in rows]
        return [record for record in records if record is not None], total

    def append_event(self, scope_type: str, scope_id: str, event_type: str, data: dict[str, Any]) -> EvaluationEvent:
        assert_public_safe(data)
        now = utc_now()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "INSERT INTO talon_events(scope_type,scope_id,event_type,created_at,data_json) VALUES(?,?,?,?,?)",
                (scope_type, scope_id, event_type, now, canonical_json(data)),
            )
            event_id = int(cursor.lastrowid)
            cutoff = self._connection.execute(
                "SELECT event_id FROM talon_events WHERE scope_type=? AND scope_id=? ORDER BY event_id DESC LIMIT 1 OFFSET ?",
                (scope_type, scope_id, self._event_replay_limit),
            ).fetchone()
            if cutoff:
                self._connection.execute(
                    "DELETE FROM talon_events WHERE scope_type=? AND scope_id=? AND event_id<=? AND event_id NOT IN (SELECT event_id FROM talon_terminal_events)",
                    (scope_type, scope_id, cutoff[0]),
                )
        return EvaluationEvent(event_id, scope_type, scope_id, event_type, now, data)

    def append_terminal_event(self, scope_type: str, scope_id: str, data: dict[str, Any]) -> EvaluationEvent:
        assert_public_safe(data)
        with self._lock:
            existing = self._connection.execute(
                "SELECT e.* FROM talon_terminal_events t JOIN talon_events e ON e.event_id=t.event_id WHERE t.scope_id=?",
                (scope_id,),
            ).fetchone()
            if existing:
                return EvaluationEvent(existing["event_id"], existing["scope_type"], existing["scope_id"], existing["event_type"], existing["created_at"], json.loads(existing["data_json"]))
            event = self.append_event(scope_type, scope_id, "terminal", data)
            with self._connection:
                self._connection.execute(
                    "INSERT INTO talon_terminal_events(scope_id,event_id) VALUES(?,?)",
                    (scope_id, event.id),
                )
            return event

    def events_after(self, scope_type: str, scope_id: str, last_event_id: int = 0, *, limit: int = 200) -> list[EvaluationEvent]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM talon_events WHERE scope_type=? AND scope_id=? AND event_id>? ORDER BY event_id LIMIT ?",
                (scope_type, scope_id, last_event_id, limit),
            ).fetchall()
        return [
            EvaluationEvent(row["event_id"], row["scope_type"], row["scope_id"], row["event_type"], row["created_at"], json.loads(row["data_json"]))
            for row in rows
        ]

    def _remove_uncommitted_checkpoint_artifacts(self, record_id: str) -> None:
        """Remove ``.partial`` files and any published checkpoint with no completed record.

        Completed runs' checkpoints are never deleted. Callers must only invoke this
        for non-completed records (or after confirming the record is not completed).
        """

        record = self.get(record_id)
        if record is not None and record.get("status") == "completed":
            return
        private = self._private_directory(record_id)
        if not private.exists():
            return
        for partial in private.glob("*.partial"):
            try:
                partial.chmod(0o600)
            except OSError:
                pass
            partial.unlink(missing_ok=True)
        checkpoint = private / "checkpoint.pt"
        if checkpoint.exists() or checkpoint.is_symlink():
            try:
                checkpoint.chmod(0o600)
            except OSError:
                pass
            checkpoint.unlink(missing_ok=True)

    def _quarantine_path(self, path: Path) -> None:
        quarantine_root = self.quarantine_dir / "orphan-checkpoints"
        quarantine_root.mkdir(parents=True, exist_ok=True)
        target = quarantine_root / f"{path.name}.{utc_now().replace(':', '').replace('.', '')}"
        try:
            path.chmod(0o600)
        except OSError:
            pass
        try:
            os.replace(path, target)
        except OSError:
            path.unlink(missing_ok=True)

    def set_checkpoint_health(self, record_id: str, *, available: bool, reason: str | None = None) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO talon_checkpoint_health(record_id,available,reason,checked_at) VALUES(?,?,?,?)",
                (record_id, 1 if available else 0, reason, utc_now()),
            )

    def checkpoint_is_available(self, record_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT available FROM talon_checkpoint_health WHERE record_id=?",
                (record_id,),
            ).fetchone()
        if row is None:
            return True
        return bool(row["available"])

    def reconcile_orphan_checkpoints(self) -> dict[str, int]:
        """Restart-safe checkpoint reconciliation under the private artifact root.

        A. completed + valid file → keep (mark available)
        B. completed + missing/invalid → mark unavailable (do not silently accept)
        C. non-completed + checkpoint file → remove/quarantine
        D. checkpoint file with no DB record under private/ → quarantine/remove
        E. ``.partial`` → remove
        """

        from .bindings import BindingSource, TrustedCheckpointBinding, logical_checkpoint_identity, resolve_bound_checkpoint

        summary = {
            "kept_completed": 0,
            "marked_unavailable": 0,
            "removed_non_completed": 0,
            "quarantined_orphans": 0,
            "removed_partials": 0,
        }
        known_ids: set[str] = set()
        with self._lock:
            rows = self._connection.execute(
                "SELECT record_id,kind,status,payload_json FROM talon_records"
            ).fetchall()
        for row in rows:
            record_id = str(row["record_id"])
            known_ids.add(record_id)
            status = str(row["status"])
            private = self._private_directory(record_id)
            for partial in private.glob("*.partial") if private.exists() else ():
                try:
                    partial.chmod(0o600)
                except OSError:
                    pass
                partial.unlink(missing_ok=True)
                summary["removed_partials"] += 1
            checkpoint = private / "checkpoint.pt"
            if status == "completed" and row["kind"] == "training":
                payload = json.loads(row["payload_json"])
                payload["record_id"] = record_id
                payload["kind"] = "training"
                payload["status"] = "completed"
                digest = payload.get("checkpoint_digest")
                if not digest:
                    self.set_checkpoint_health(record_id, available=False, reason="missing_digest")
                    summary["marked_unavailable"] += 1
                    continue
                try:
                    identity = payload.get("artifact_identity") or logical_checkpoint_identity(record_id)
                    binding = TrustedCheckpointBinding(
                        training_run_id=record_id,
                        checkpoint_id=record_id,
                        trusted_digest=str(digest),
                        artifact_identity=str(identity),
                        binding_source=BindingSource.IMMUTABLE_DB_RECORD,
                        offline_dataset_digest=(
                            str(payload["offline_dataset_digest"])
                            if payload.get("offline_dataset_digest")
                            else None
                        ),
                    )
                    resolve_bound_checkpoint(self.private_dir, binding, require_digest_match=True)
                except (TypeError, ValueError):
                    self.set_checkpoint_health(record_id, available=False, reason="missing_or_invalid_file")
                    summary["marked_unavailable"] += 1
                    continue
                self.set_checkpoint_health(record_id, available=True, reason=None)
                summary["kept_completed"] += 1
                continue
            if checkpoint.exists() or checkpoint.is_symlink():
                self._quarantine_path(checkpoint)
                summary["removed_non_completed"] += 1
        if self.private_dir.exists():
            for entry in self.private_dir.iterdir():
                if not entry.is_dir():
                    continue
                record_id = entry.name
                for partial in entry.glob("*.partial"):
                    try:
                        partial.chmod(0o600)
                    except OSError:
                        pass
                    partial.unlink(missing_ok=True)
                    summary["removed_partials"] += 1
                checkpoint = entry / "checkpoint.pt"
                if not (checkpoint.exists() or checkpoint.is_symlink()):
                    continue
                if record_id not in known_ids:
                    self._quarantine_path(checkpoint)
                    summary["quarantined_orphans"] += 1
        return summary

    def mark_active_interrupted(self) -> int:
        with self._lock:
            rows = self._connection.execute(
                "SELECT record_id,kind FROM talon_records WHERE status IN ('queued','running','cancelling')"
            ).fetchall()
        count = 0
        for row in rows:
            record_id = str(row["record_id"])
            # Drop uncommitted partials / published checkpoints before terminalising so a
            # restart cannot leave an interrupted run's weights consumable.
            self._remove_uncommitted_checkpoint_artifacts(record_id)
            try:
                digest = self.finalize(record_id, "interrupted", {"error_category": "api_restart"})
            except TalonImmutableRecordError:
                continue
            # Re-clean after finalize in case a late publish raced the restart.
            self._remove_uncommitted_checkpoint_artifacts(record_id)
            scope = "talon_training" if row["kind"] == "training" else "talon_evaluation"
            self.append_terminal_event(scope, record_id, {"record_id": record_id, "status": "interrupted", "record_digest": digest})
            count += 1
        self.reconcile_orphan_checkpoints()
        return count

    def _has_dependents(self, record_id: str) -> bool:
        return self._connection.execute(
            "SELECT 1 FROM talon_dependencies WHERE depends_on=? LIMIT 1", (record_id,)
        ).fetchone() is not None

    def recover_deletions(self) -> None:
        with self._lock:
            rows = self._connection.execute("SELECT record_id,state FROM talon_deletion_plans").fetchall()
        for row in rows:
            record_id = str(row["record_id"])
            quarantine = self.quarantine_dir / record_id
            if self.get(record_id) is None:
                shutil.rmtree(quarantine, ignore_errors=True)
                shutil.rmtree(self._private_directory(record_id), ignore_errors=True)
                with self._connection:
                    self._connection.execute("DELETE FROM talon_deletion_plans WHERE record_id=?", (record_id,))
            else:
                # A plan that did not commit deletion is rolled back safely.
                public = self._record_directory(record_id)
                if quarantine.exists() and not public.exists():
                    os.replace(quarantine, public)
                with self._connection:
                    self._connection.execute("DELETE FROM talon_deletion_plans WHERE record_id=?", (record_id,))

    def prune_expired(self, retention_days: int) -> list[str]:
        if retention_days < 1:
            return []
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat().replace("+00:00", "Z")
        with self._lock:
            rows = self._connection.execute(
                "SELECT record_id FROM talon_records WHERE status IN ('completed','failed','cancelled','interrupted','timed_out') AND updated_at<? ORDER BY updated_at",
                (cutoff,),
            ).fetchall()
        removed: list[str] = []
        for row in rows:
            record_id = str(row["record_id"])
            with self._lock:
                if self._has_dependents(record_id):
                    continue
                with self._connection:
                    self._connection.execute(
                        "INSERT OR REPLACE INTO talon_deletion_plans VALUES(?,?,?)",
                        (record_id, "planned", utc_now()),
                    )
                public = self._record_directory(record_id)
                quarantine = self.quarantine_dir / record_id
                if public.exists():
                    os.replace(public, quarantine)
                try:
                    with self._connection:
                        self._connection.execute("DELETE FROM talon_terminal_events WHERE scope_id=?", (record_id,))
                        self._connection.execute("DELETE FROM talon_events WHERE scope_id=?", (record_id,))
                        self._connection.execute("DELETE FROM talon_idempotency WHERE record_id=?", (record_id,))
                        self._connection.execute("DELETE FROM talon_records WHERE record_id=?", (record_id,))
                        self._connection.execute("UPDATE talon_deletion_plans SET state='db_deleted' WHERE record_id=?", (record_id,))
                except Exception:
                    if quarantine.exists() and not public.exists():
                        os.replace(quarantine, public)
                    raise
            shutil.rmtree(quarantine, ignore_errors=True)
            shutil.rmtree(self._private_directory(record_id), ignore_errors=True)
            with self._connection:
                self._connection.execute("DELETE FROM talon_deletion_plans WHERE record_id=?", (record_id,))
            removed.append(record_id)
        return removed

    def delete_terminal(self, record_id: str) -> bool:
        """Delete one unreferenced terminal record using the restart-safe plan."""

        record = self.get(record_id)
        if record is None:
            return False
        if record.get("status") not in TERMINAL_STATUSES:
            raise TalonImmutableRecordError("active Talon records cannot be deleted")
        with self._lock:
            if self._has_dependents(record_id):
                raise TalonImmutableRecordError("referenced Talon records cannot be deleted")
            with self._connection:
                self._connection.execute(
                    "INSERT OR REPLACE INTO talon_deletion_plans VALUES(?,?,?)",
                    (record_id, "planned", utc_now()),
                )
            public = self._record_directory(record_id)
            quarantine = self.quarantine_dir / record_id
            if public.exists():
                os.replace(public, quarantine)
            try:
                with self._connection:
                    self._connection.execute("DELETE FROM talon_terminal_events WHERE scope_id=?", (record_id,))
                    self._connection.execute("DELETE FROM talon_events WHERE scope_id=?", (record_id,))
                    self._connection.execute("DELETE FROM talon_idempotency WHERE record_id=?", (record_id,))
                    self._connection.execute("DELETE FROM talon_records WHERE record_id=?", (record_id,))
                    self._connection.execute("UPDATE talon_deletion_plans SET state='db_deleted' WHERE record_id=?", (record_id,))
            except Exception:
                if quarantine.exists() and not public.exists():
                    os.replace(quarantine, public)
                raise
        shutil.rmtree(quarantine, ignore_errors=True)
        shutil.rmtree(self._private_directory(record_id), ignore_errors=True)
        with self._connection:
            self._connection.execute("DELETE FROM talon_deletion_plans WHERE record_id=?", (record_id,))
        return True
