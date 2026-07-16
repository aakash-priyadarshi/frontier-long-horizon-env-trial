"""SQLite persistence with immutable terminal run records and canonical digests."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from .candidate_artifacts import candidate_artifact_digest
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


class ActiveRunDeletionError(RuntimeError):
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

    def _run_directory(self, run_id: str) -> Path:
        base = self.runs_dir.resolve()
        target = (self.runs_dir / run_id).resolve()
        if target.parent != base or target.name != run_id:
            raise ValueError("invalid run storage path")
        return target

    def _candidate_artifact_path(self, run_id: str) -> Path:
        return self._run_directory(run_id) / "candidate-diff.json"

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

    def finalize_run(
        self,
        run_id: str,
        status: str,
        result_payload: dict[str, Any],
        *,
        candidate_artifact: dict[str, Any] | None = None,
    ) -> str:
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
            artifact_bytes: bytes | None = None
            if candidate_artifact is not None:
                declared_digest = candidate_artifact.get("artifact_digest")
                actual_digest = candidate_artifact_digest(candidate_artifact)
                if declared_digest != actual_digest:
                    raise ValueError("candidate artifact digest is invalid")
                artifact_bytes = (
                    json.dumps(candidate_artifact, indent=2, sort_keys=True) + "\n"
                ).encode("utf-8")
                payload["candidate_diff_summary"] = {
                    "changed_paths": list(candidate_artifact.get("changed_paths") or []),
                    "file_count": int(candidate_artifact.get("file_count") or 0),
                    "retention": {
                        "captured": True,
                        "artifact_digest": actual_digest,
                        "stored_bytes": len(artifact_bytes),
                        "redaction_count": int(candidate_artifact.get("redaction_count") or 0),
                        "truncated": bool(candidate_artifact.get("truncated")),
                    },
                }
            else:
                summary = payload.get("candidate_diff_summary")
                if not isinstance(summary, dict):
                    summary = {"changed_paths": [], "file_count": 0}
                payload["candidate_diff_summary"] = {
                    **summary,
                    "retention": {
                        "captured": False,
                        "artifact_digest": None,
                        "stored_bytes": 0,
                        "redaction_count": 0,
                        "truncated": False,
                    },
                }
            payload["status"] = status
            payload["ended_at"] = payload.get("ended_at") or utc_now()
            digest = record_digest(payload)
            payload["record_digest"] = digest
            artifact_path = self._candidate_artifact_path(run_id)
            if artifact_bytes is not None:
                if artifact_path.exists():
                    raise ImmutableRecordError("candidate artifact already exists")
                artifact_path.write_bytes(artifact_bytes)
            self._connection.execute(
                "UPDATE runs SET status=?, updated_at=?, instance_id=COALESCE(?,instance_id), payload_json=?, digest=? WHERE run_id=?",
                (status, utc_now(), payload.get("instance_id"), canonical_json(payload), digest, run_id),
            )
            artifact = self.runs_dir / run_id / "result.json"
            if artifact.exists():
                raise ImmutableRecordError("terminal run artifact already exists")
            artifact.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return digest

    def candidate_artifact(self, run_id: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        row = self._connection.execute(
            "SELECT payload_json FROM runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        payload = json.loads(row["payload_json"])
        summary = payload.get("candidate_diff_summary") or {}
        retention = summary.get("retention") if isinstance(summary, dict) else None
        if not isinstance(retention, dict) or not retention.get("captured"):
            return None, {"state": "not_captured", "stored_bytes": 0}
        expected_digest = retention.get("artifact_digest")
        artifact_path = self._candidate_artifact_path(run_id)
        if not artifact_path.is_file():
            return None, {
                "state": "deleted",
                "stored_bytes": 0,
                "artifact_digest": expected_digest,
            }
        try:
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            actual_digest = candidate_artifact_digest(artifact)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return None, {
                "state": "corrupt",
                "stored_bytes": artifact_path.stat().st_size,
                "artifact_digest": expected_digest,
            }
        if artifact.get("artifact_digest") != actual_digest or actual_digest != expected_digest:
            return None, {
                "state": "corrupt",
                "stored_bytes": artifact_path.stat().st_size,
                "artifact_digest": expected_digest,
            }
        return artifact, {
            "state": "available",
            "stored_bytes": artifact_path.stat().st_size,
            "artifact_digest": actual_digest,
        }

    def delete_candidate_artifact(self, run_id: str) -> dict[str, Any]:
        artifact, storage = self.candidate_artifact(run_id)
        artifact_path = self._candidate_artifact_path(run_id)
        reclaimed = artifact_path.stat().st_size if artifact_path.is_file() else 0
        if artifact is not None or artifact_path.is_file():
            artifact_path.unlink(missing_ok=True)
        return {
            "run_id": run_id,
            "deleted": reclaimed > 0,
            "reclaimed_bytes": reclaimed,
            "artifact_digest": storage.get("artifact_digest"),
        }

    def candidate_storage_summary(self) -> dict[str, Any]:
        rows = self._connection.execute(
            "SELECT run_id,provider,model,payload_json FROM runs ORDER BY created_at DESC"
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            summary = payload.get("candidate_diff_summary") or {}
            retention = summary.get("retention") if isinstance(summary, dict) else None
            if not isinstance(retention, dict) or not retention.get("captured"):
                continue
            _, storage = self.candidate_artifact(row["run_id"])
            items.append({
                "run_id": row["run_id"],
                "provider": row["provider"],
                "model": row["model"],
                "changed_paths": list(summary.get("changed_paths") or []),
                **storage,
            })
        return {
            "total_bytes": sum(int(item.get("stored_bytes") or 0) for item in items),
            "available_count": sum(item["state"] == "available" for item in items),
            "deleted_count": sum(item["state"] == "deleted" for item in items),
            "corrupt_count": sum(item["state"] == "corrupt" for item in items),
            "items": items,
        }

    def delete_all_candidate_artifacts(self) -> dict[str, Any]:
        summary = self.candidate_storage_summary()
        deleted_count = 0
        reclaimed_bytes = 0
        for item in summary["items"]:
            if item["state"] != "available":
                continue
            result = self.delete_candidate_artifact(item["run_id"])
            if result["deleted"]:
                deleted_count += 1
                reclaimed_bytes += int(result["reclaimed_bytes"])
        return {"deleted_count": deleted_count, "reclaimed_bytes": reclaimed_bytes}

    def delete_run(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT batch_id,status FROM runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            if row["status"] not in TERMINAL_RUN_STATUSES:
                raise ActiveRunDeletionError("active episodes cannot be deleted")
            batch_id = str(row["batch_id"])
            run_directory = self._run_directory(run_id)
            tombstone = self.runs_dir.resolve() / f".deleting-{run_id}-{uuid.uuid4().hex}"
            moved = False
            if run_directory.exists():
                run_directory.rename(tombstone)
                moved = True
            try:
                with self._connection:
                    self._connection.execute(
                        "DELETE FROM events WHERE scope_type='run' AND scope_id=?",
                        (run_id,),
                    )
                    batch_events = self._connection.execute(
                        "SELECT event_id,data_json FROM events WHERE scope_type='batch' AND scope_id=?",
                        (batch_id,),
                    ).fetchall()
                    event_ids = []
                    for event in batch_events:
                        try:
                            data = json.loads(event["data_json"])
                        except json.JSONDecodeError:
                            continue
                        if isinstance(data, dict) and data.get("run_id") == run_id:
                            event_ids.append(int(event["event_id"]))
                    if event_ids:
                        placeholders = ",".join("?" for _ in event_ids)
                        self._connection.execute(
                            f"DELETE FROM events WHERE event_id IN ({placeholders})",
                            tuple(event_ids),
                        )
                    self._connection.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
                    remaining = int(self._connection.execute(
                        "SELECT COUNT(*) FROM runs WHERE batch_id=?",
                        (batch_id,),
                    ).fetchone()[0])
                    if remaining == 0:
                        self._connection.execute(
                            "DELETE FROM events WHERE scope_type='batch' AND scope_id=?",
                            (batch_id,),
                        )
                        self._connection.execute("DELETE FROM batches WHERE batch_id=?", (batch_id,))
                    else:
                        self._connection.execute(
                            "UPDATE batches SET updated_at=? WHERE batch_id=?",
                            (utc_now(), batch_id),
                        )
            except Exception:
                if moved and tombstone.exists() and not run_directory.exists():
                    tombstone.rename(run_directory)
                raise
            if moved:
                resolved_tombstone = tombstone.resolve()
                if resolved_tombstone.parent != self.runs_dir.resolve():
                    raise RuntimeError("run deletion escaped storage directory")
                shutil.rmtree(resolved_tombstone)
            return {"run_id": run_id, "batch_id": batch_id, "deleted": True}

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
