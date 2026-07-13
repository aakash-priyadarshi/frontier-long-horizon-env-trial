"""SQLite persistence with immutable terminal run records and canonical digests."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .events import EvaluationEvent
from .schemas import EvaluationCreate, utc_now


SCHEMA_VERSION = 1
TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def record_digest(payload: dict[str, Any]) -> str:
    canonical_payload = {
        k: v
        for k, v in payload.items()
        if k not in {"record_digest", "exported_at", "updated_at"}
    }
    return "sha256:" + hashlib.sha256(canonical_json(canonical_payload).encode("utf-8")).hexdigest()


class ImmutableRecordError(RuntimeError):
    pass


class EvaluationStore:
    def __init__(self, path: Path | str, *, event_replay_limit: int = 1_000) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.runs_dir = self.path.parent / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._event_replay_limit = event_replay_limit
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._migrate()

    def close(self) -> None:
        self._connection.close()

    def _migrate(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS batches (
                    batch_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    split TEXT NOT NULL,
                    seed_start INTEGER NOT NULL,
                    seed_count INTEGER NOT NULL,
                    attempts INTEGER NOT NULL,
                    total_runs INTEGER NOT NULL,
                    configuration_json TEXT NOT NULL,
                    environment_commit TEXT NOT NULL,
                    application_commit TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    split TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    attempt INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    instance_id TEXT,
                    payload_json TEXT NOT NULL,
                    digest TEXT,
                    UNIQUE(batch_id, seed, attempt)
                );
                CREATE INDEX IF NOT EXISTS idx_runs_batch ON runs(batch_id, created_at);
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope_type TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    data_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_scope ON events(scope_type, scope_id, event_id);
                """
            )
            current = self._connection.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
            if current and int(current[0]) > SCHEMA_VERSION:
                raise RuntimeError("evaluation database schema is newer than this application")
            self._connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @property
    def schema_version(self) -> int:
        row = self._connection.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
        return int(row[0])

    def create_batch(self, batch_id: str, request: EvaluationCreate, *, environment_commit: str, application_commit: str) -> None:
        now = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO batches VALUES(?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    batch_id, now, now, request.provider, request.model, request.split,
                    request.seed_start, request.seed_count, request.attempts,
                    request.seed_count * request.attempts,
                    canonical_json(request.model_dump(mode="json")), environment_commit, application_commit,
                ),
            )

    def create_run(self, run_id: str, batch_id: str, *, split: str, seed: int, attempt: int, provider: str, model: str, payload: dict[str, Any]) -> None:
        now = utc_now()
        payload = {
            **payload,
            "run_id": run_id,
            "batch_id": batch_id,
            "created_at": now,
        }
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO runs(run_id,batch_id,created_at,updated_at,status,split,seed,attempt,provider,model,instance_id,payload_json,digest)
                VALUES(?,?,?,?,?,?,?,?,?,?,NULL,?,NULL)""",
                (run_id, batch_id, now, now, "queued", split, seed, attempt, provider, model, canonical_json(payload)),
            )
        (self.runs_dir / run_id).mkdir(parents=True, exist_ok=False)

    def update_batch_status(self, batch_id: str, status: str) -> None:
        with self._lock, self._connection:
            self._connection.execute("UPDATE batches SET status=?, updated_at=? WHERE batch_id=?", (status, utc_now(), batch_id))

    def update_run_progress(self, run_id: str, status: str, updates: dict[str, Any]) -> None:
        with self._lock, self._connection:
            row = self._connection.execute("SELECT status,payload_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            if row["status"] in TERMINAL_RUN_STATUSES:
                raise ImmutableRecordError("terminal run records are immutable")
            payload = json.loads(row["payload_json"])
            payload.update(updates)
            self._connection.execute(
                "UPDATE runs SET status=?, updated_at=?, instance_id=COALESCE(?,instance_id), payload_json=? WHERE run_id=?",
                (status, utc_now(), updates.get("instance_id"), canonical_json(payload), run_id),
            )

    def finalize_run(self, run_id: str, status: str, result_payload: dict[str, Any]) -> str:
        if status not in TERMINAL_RUN_STATUSES:
            raise ValueError("final run status must be terminal")
        with self._lock, self._connection:
            row = self._connection.execute("SELECT status,payload_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            if row["status"] in TERMINAL_RUN_STATUSES:
                raise ImmutableRecordError("terminal run records are immutable")
            payload = json.loads(row["payload_json"])
            payload.update(result_payload)
            payload["status"] = status
            payload["ended_at"] = payload.get("ended_at") or utc_now()
            digest = record_digest(payload)
            payload["record_digest"] = digest
            self._connection.execute(
                "UPDATE runs SET status=?, updated_at=?, instance_id=COALESCE(?,instance_id), payload_json=?, digest=? WHERE run_id=?",
                (status, utc_now(), payload.get("instance_id"), canonical_json(payload), digest, run_id),
            )
            artifact = self.runs_dir / run_id / "result.json"
            if artifact.exists():
                raise ImmutableRecordError("terminal run artifact already exists")
            artifact.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return digest

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return self._run_row(row) if row else None

    def _run_row(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(row["payload_json"])
        payload.update({
            "run_id": row["run_id"], "batch_id": row["batch_id"], "status": row["status"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        })
        return payload

    def list_runs(self, *, batch_id: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        where = " WHERE batch_id=?" if batch_id else ""
        params: tuple[Any, ...] = (batch_id,) if batch_id else ()
        total = int(self._connection.execute(f"SELECT COUNT(*) FROM runs{where}", params).fetchone()[0])
        rows = self._connection.execute(
            f"SELECT * FROM runs{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [self._run_row(row) for row in rows], total

    def get_batch(self, batch_id: str, *, include_runs: bool = True, run_limit: int = 100, run_offset: int = 0) -> dict[str, Any] | None:
        row = self._connection.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
        if row is None:
            return None
        runs, run_total = self.list_runs(batch_id=batch_id, limit=run_limit, offset=run_offset)
        counts = {name: 0 for name in ("completed", "failed", "cancelled", "interrupted", "running", "queued")}
        all_rows = self._connection.execute("SELECT status,payload_json FROM runs WHERE batch_id=?", (batch_id,)).fetchall()
        rewards: list[float] = []
        actions: list[int] = []
        costs: list[float] = []
        for run_row in all_rows:
            counts[run_row["status"]] = counts.get(run_row["status"], 0) + 1
            payload = json.loads(run_row["payload_json"])
            if isinstance(payload.get("authoritative_reward"), (int, float)):
                rewards.append(float(payload["authoritative_reward"]))
            if isinstance(payload.get("action_count"), int):
                actions.append(payload["action_count"])
            if isinstance(payload.get("estimated_cost"), (int, float)):
                costs.append(float(payload["estimated_cost"]))
        success_count = sum(1 for value in rewards if value == 1.0)
        aggregate = {
            "strict_success_rate": success_count / len(rewards) if rewards else None,
            "average_reward": sum(rewards) / len(rewards) if rewards else None,
            "average_actions": sum(actions) / len(actions) if actions else None,
            "estimated_total_cost": sum(costs) if costs else None,
            "average_cost_per_success": sum(costs) / success_count if costs and success_count else None,
        }
        result = {
            "batch_id": row["batch_id"], "created_at": row["created_at"], "updated_at": row["updated_at"],
            "status": row["status"], "provider": row["provider"], "model": row["model"], "split": row["split"],
            "seed_start": row["seed_start"], "seed_count": row["seed_count"], "attempts": row["attempts"],
            "total_runs": row["total_runs"], "completed_runs": counts["completed"], "failed_runs": counts["failed"] + counts["interrupted"],
            "cancelled_runs": counts["cancelled"], "running_runs": counts["running"], "queued_runs": counts["queued"],
            "configuration": json.loads(row["configuration_json"]), "aggregate_results": aggregate,
            "environment_commit": row["environment_commit"], "application_commit": row["application_commit"],
            "run_total": run_total, "run_limit": run_limit, "run_offset": run_offset,
        }
        if include_runs:
            result["runs"] = runs
        return result

    def list_batches(self, *, limit: int = 25, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        total = int(self._connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0])
        ids = self._connection.execute("SELECT batch_id FROM batches ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return [self.get_batch(row[0], include_runs=False) for row in ids], total  # type: ignore[list-item]

    def append_event(self, scope_type: str, scope_id: str, event_type: str, data: dict[str, Any]) -> EvaluationEvent:
        now = utc_now()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "INSERT INTO events(scope_type,scope_id,event_type,created_at,data_json) VALUES(?,?,?,?,?)",
                (scope_type, scope_id, event_type, now, canonical_json(data)),
            )
            event_id = int(cursor.lastrowid)
            cutoff = self._connection.execute(
                "SELECT event_id FROM events WHERE scope_type=? AND scope_id=? ORDER BY event_id DESC LIMIT 1 OFFSET ?",
                (scope_type, scope_id, self._event_replay_limit),
            ).fetchone()
            if cutoff:
                self._connection.execute("DELETE FROM events WHERE scope_type=? AND scope_id=? AND event_id<=?", (scope_type, scope_id, cutoff[0]))
        return EvaluationEvent(event_id, scope_type, scope_id, event_type, now, data)

    def events_after(self, scope_type: str, scope_id: str, last_event_id: int = 0, *, limit: int = 200) -> list[EvaluationEvent]:
        rows = self._connection.execute(
            "SELECT * FROM events WHERE scope_type=? AND scope_id=? AND event_id>? ORDER BY event_id LIMIT ?",
            (scope_type, scope_id, last_event_id, limit),
        ).fetchall()
        return [EvaluationEvent(row["event_id"], row["scope_type"], row["scope_id"], row["event_type"], row["created_at"], json.loads(row["data_json"])) for row in rows]

    def mark_active_interrupted(self) -> int:
        now = utc_now()
        with self._lock, self._connection:
            rows = self._connection.execute("SELECT run_id,payload_json FROM runs WHERE status IN ('queued','running')").fetchall()
            for row in rows:
                payload = json.loads(row["payload_json"])
                payload.update({"status": "interrupted", "ended_at": now, "error_category": "api_restart"})
                digest = record_digest(payload)
                payload["record_digest"] = digest
                self._connection.execute("UPDATE runs SET status='interrupted',updated_at=?,payload_json=?,digest=? WHERE run_id=?", (now, canonical_json(payload), digest, row["run_id"]))
                artifact = self.runs_dir / row["run_id"] / "result.json"
                if not artifact.exists():
                    artifact.write_text(
                        json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
            self._connection.execute("UPDATE batches SET status='interrupted',updated_at=? WHERE status IN ('queued','running','cancelling')", (now,))
        return len(rows)
