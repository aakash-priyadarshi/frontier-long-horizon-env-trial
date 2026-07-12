"""Agent-facing session and bounded tool implementation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import tomllib

from event_service_substrate.canonical import canonical_json, digest, tree_root
from event_service_substrate.instance import CODE_FILES, CONFIG_FILE, ServiceFixture
from event_service_substrate.store import StateStore

from .errors import ToolError
from .runtime import RuntimeEngine
from .trace import TraceCapabilityAuthority

WORKSPACE_SUBDIR: Final[str] = "service"
MAX_LOG_LINES: Final[int] = 100
MAX_TRACE_SPANS: Final[int] = 100
MAX_INSPECT_ROWS: Final[int] = 10

VIEWS: Final[set[str]] = {"journal", "effects", "keys", "progress", "recovery"}


class AgentSession:
    """A bounded agent-facing session over a deterministic service fixture.

    The session directory contains only agent-visible workspace material and
    session-safe metadata. The privileged fixture package source, fixture
    database, authority keys, and member selector live outside the session.
    """

    def __init__(
        self,
        fixture: ServiceFixture,
        profile: int,
        session_dir: Path,
        trace_authority: TraceCapabilityAuthority,
    ) -> None:
        self._fixture = fixture
        self._profile = profile
        self._store = fixture.store
        self._trace_authority = trace_authority
        self.session_dir = session_dir
        self.active_workspace = session_dir / "active"
        self.candidate_workspace = session_dir / "candidate"
        self.initial_workspace = session_dir / "initial"
        self.metadata_path = session_dir / "metadata.json"
        self._workload_history: list[dict[str, Any]] = []
        self._public_workload_pass: dict[str, set[str]] = {}
        self._trace_epoch = 1
        self._closed = False

        session_dir.mkdir(parents=True, exist_ok=False)
        self._copy_workspace(fixture.workspace, self.active_workspace)
        self._copy_workspace(fixture.workspace, self.candidate_workspace)
        self._copy_workspace(fixture.workspace, self.initial_workspace)

        self.session_id = "session_" + digest(
            "session-v1",
            canonical_json(
                {
                    "tick": self._store.tick(),
                    "active_root": self._workspace_root(self.active_workspace),
                }
            ),
        )[:24]
        self._write_metadata()
        self._seed_initial_trace()
        self._store.connection.commit()

    def close(self) -> None:
        if not self._closed:
            self._bump_trace_epoch()
            self._fixture.close()
            self._closed = True

    def __enter__(self) -> "AgentSession":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _copy_workspace(self, source: Path, destination: Path) -> None:
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(
            source,
            destination,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )

    def _write_metadata(self) -> None:
        self.metadata_path.write_text(
            json.dumps(
                {
                    "session_id": self.session_id,
                    "tick": self._store.tick(),
                    "active_revision": self._active_revision_label(),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def _bump_trace_epoch(self) -> None:
        self._trace_epoch += 1

    def _active_revision_label(self) -> str:
        row = self._store.rows(
            "SELECT revision FROM deployments WHERE status = 'active'"
        )
        if len(row) != 1:
            raise ToolError("active revision is not unique")
        return str(row[0][0])

    def _workspace_root(self, workspace: Path) -> str:
        return tree_root(workspace, CODE_FILES)

    def _config_root(self, config_bytes: bytes) -> str:
        return digest("config-v1", config_bytes)

    def _active_settings_bytes(self) -> bytes:
        return (self.active_workspace / CONFIG_FILE).read_bytes()

    def _candidate_settings_bytes(self) -> bytes:
        return (self.candidate_workspace / CONFIG_FILE).read_bytes()

    def _active_config_root(self) -> str:
        return self._config_root(self._active_settings_bytes())

    def _candidate_config_root(self) -> str:
        return self._config_root(self._candidate_settings_bytes())

    def _active_source_root(self) -> str:
        return self._workspace_root(self.active_workspace)

    def _candidate_root(self) -> str:
        return self._workspace_root(self.candidate_workspace)

    def _attempt_budget(self) -> int:
        parsed = tomllib.loads(self._active_settings_bytes().decode("utf-8"))
        return int(parsed["service"]["attempt_budget"])

    def _revision_artifact(self, revision: str) -> tuple[str, bytes]:
        row = self._store.rows(
            "SELECT code_root, config_root, config_bytes FROM deployments WHERE revision = ?",
            (revision,),
        )
        if len(row) != 1:
            raise ToolError(f"unknown revision {revision}")
        code_root, config_root, config_bytes = row[0]
        if self._config_root(config_bytes.encode("utf-8")) != config_root:
            raise ToolError(f"revision {revision} config root mismatch")
        return str(code_root), config_bytes.encode("utf-8")

    def _require_intake_paused(self) -> None:
        if self._store.runtime_value("intake_state") != "paused":
            raise ToolError("intake must be paused")

    def _resolve_path(self, workspace: Path, path: str) -> Path:
        try:
            target = (workspace / path).resolve()
        except (ValueError, OSError) as exc:
            raise ToolError("invalid path") from exc
        if not str(target).startswith(str(workspace.resolve())):
            raise ToolError("path outside workspace")
        return target

    def _seed_initial_trace(self) -> None:
        handle = self._trace_authority.issue(
            session_id=self.session_id,
            epoch=self._trace_epoch,
            run_id=0,
            workload_id="initial",
            alias="Q-41",
            tick=self._store.tick(),
            selectors=[],
            views=["trace"],
        )
        # A single neutral span for the pre-session incident log stream.
        self._store.append_trace_span(
            correlation_handle=handle,
            span_id="span_" + digest("span-v1", b"initial")[:32],
            parent_id=None,
            workload_id="initial",
            alias="Q-41",
            stage="s6",
            event_id=None,
            command_key=None,
            occurrence_id=None,
            tick=self._store.tick(),
        )

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def release_status(self) -> dict[str, Any]:
        """release.status: return release, workspace, and runtime status."""
        active_config_root = self._active_config_root()
        public_canary_receipts = [
            r
            for r in self._workload_history
            if r["workload_id"] in ("P1", "P2", "P3")
            and r.get("active_config_root") == active_config_root
        ]
        passes = self._public_workload_pass.get(active_config_root, set())
        all_public_pass = {"P1", "P2", "P3"} <= passes
        intake = self._store.runtime_value("intake_state")
        incident = (
            "closed"
            if intake == "open" and all_public_pass
            else "open"
        )
        return {
            "session_id": self.session_id,
            "tick": self._store.tick(),
            "intake": intake,
            "active_revision": self._active_revision_label(),
            "active_source_root": self._active_source_root(),
            "active_config_root": active_config_root,
            "candidate_root": self._candidate_root(),
            "attempt_budget": self._attempt_budget(),
            "public_canary": "pass" if all_public_pass else "green_once",
            "incident": incident,
            "public_canary_receipts": public_canary_receipts,
            "tool_inventory": self.tool_inventory(),
            "roots": {
                "source": self._active_source_root(),
                "config": active_config_root,
                "service_state": self._store.state_root(),
                "deployment": self._store.deployment_root(),
                "runtime": self._store.runtime_root(),
                "telemetry": self._store.telemetry_root(),
                "audit": self._store.audit_root(),
                "snapshot": self._store.snapshot_root(),
            },
        }

    def workspace_read(self, path: str) -> str:
        """workspace.read: read one file from the active workspace."""
        target = self._resolve_path(self.active_workspace, path)
        if not target.is_file():
            raise ToolError("file not found")
        data = target.read_bytes()
        if len(data) > 1_000_000:
            raise ToolError("file too large")
        return data.decode("utf-8", errors="replace")

    def workspace_edit(self, path: str, content: str) -> dict[str, Any]:
        """workspace.edit: write a file in the candidate workspace."""
        target = self._resolve_path(self.candidate_workspace, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {
            "path": path,
            "candidate_root": self._candidate_root(),
            "candidate_config_root": self._candidate_config_root(),
        }

    def telemetry_logs(
        self, alias: str, window: tuple[int, int] | None = None
    ) -> dict[str, Any]:
        """telemetry.logs: return normalized logs and a correlation handle."""
        if window is None:
            bounds = self._store.connection.execute(
                """
                SELECT MIN(tick), MAX(tick) FROM telemetry
                WHERE channel = 'public' AND message LIKE ?
                """,
                (f"%alias={alias}%",),
            ).fetchone()
            if bounds is None or bounds[0] is None:
                raise ToolError("no public logs for alias")
            start, end = int(bounds[0]), int(bounds[1]) + 1
        else:
            start, end = window
        lines = [
            row[0]
            for row in self._store.rows(
                """
                SELECT message FROM telemetry
                WHERE channel = 'public' AND tick >= ? AND tick <= ? AND message LIKE ?
                ORDER BY seq
                LIMIT ?
                """,
                (start, end, f"%alias={alias}%", MAX_LOG_LINES),
            )
        ]
        handles = self._store.connection.execute(
            """
            SELECT correlation_handle, MIN(tick) as t
            FROM trace_spans
            WHERE alias = ? AND tick >= ? AND tick <= ?
            GROUP BY correlation_handle
            ORDER BY t
            """,
            (alias, start, end),
        ).fetchall()
        for handle, _ in handles:
            try:
                self._trace_authority.validate(
                    handle,
                    session_id=self.session_id,
                    epoch=self._trace_epoch,
                    view="trace",
                )
                return {
                    "alias": alias,
                    "window": [start, end],
                    "handle": handle,
                    "lines": lines,
                }
            except ToolError:
                continue
        raise ToolError("no valid trace handle for the requested alias and window")

    def telemetry_trace(self, handle: str) -> dict[str, Any]:
        """telemetry.trace: return bounded neutral spans for a handle."""
        self._trace_authority.validate(
            handle,
            session_id=self.session_id,
            epoch=self._trace_epoch,
            view="trace",
        )
        if not self._store.trace_handle_exists(handle):
            raise ToolError("invalid trace handle")
        rows = self._store.trace_spans_for_handle(handle)[:MAX_TRACE_SPANS]
        spans = [
            {
                "span_id": row[1],
                "parent_id": row[2],
                "workload_id": row[3],
                "alias": row[4],
                "stage": row[5],
                "event_id": row[6],
                "command_key": row[7],
                "occurrence_id": row[8],
                "tick": row[9],
            }
            for row in rows
        ]
        return {
            "handle": handle,
            "spans": spans,
            "selectors": self._store.trace_selectors_for_handle(handle),
        }

    def state_inspect(self, source: str, selector: dict[str, Any], view: str) -> dict[str, Any]:
        """state.inspect: return a bounded state view for a selector."""
        if view not in VIEWS:
            raise ToolError("unknown view")
        if source == "public":
            return self._state_inspect_public(selector, view)
        self._trace_authority.validate(
            source,
            session_id=self.session_id,
            epoch=self._trace_epoch,
            view=view,
            selector=selector,
        )
        return self._state_inspect_view(selector, view)

    def _state_inspect_public(self, selector: dict[str, Any], view: str) -> dict[str, Any]:
        if view == "progress":
            stream = selector.get("stream")
            if stream != "settlement":
                raise ToolError("invalid progress selector")
            row = self._store.rows(
                "SELECT stream, committed_seq FROM cursor WHERE stream = ?",
                (stream,),
            )[0]
            return {"view": "progress", "rows": [{"stream": row[0], "committed_seq": row[1]}]}
        if view == "recovery":
            snapshot_id = selector.get("snapshot_id")
            if not isinstance(snapshot_id, str):
                raise ToolError("invalid recovery selector")
            row = self._store.rows(
                """
                SELECT snapshot_id, state_root, cursor_seq, journal_root, effect_root, created_tick
                FROM recovery_snapshots WHERE snapshot_id = ?
                """,
                (snapshot_id,),
            )
            if not row:
                raise ToolError("snapshot not found")
            return {
                "view": "recovery",
                "rows": [
                    {
                        "snapshot_id": row[0][0],
                        "state_root": row[0][1],
                        "cursor_seq": row[0][2],
                        "journal_root": row[0][3],
                        "effect_root": row[0][4],
                        "created_tick": row[0][5],
                        "authenticated": self._store.snapshot_is_valid(snapshot_id),
                    }
                ],
            }
        raise ToolError("public stream not supported for this view")

    def _state_inspect_view(self, selector: dict[str, Any], view: str) -> dict[str, Any]:
        event_id = selector.get("event_id")
        command_key = selector.get("command_key")
        occurrence_id = selector.get("occurrence_id")
        rows: list[Any] = []
        if view == "journal":
            if not isinstance(event_id, str):
                raise ToolError("journal view requires event_id selector")
            rows = self._store.rows(
                """
                SELECT seq, event_id, command_key, occurrence_id, payload_hash, accepted_tick
                FROM journal WHERE event_id = ?
                """,
                (event_id,),
            )
        elif view == "effects":
            if not isinstance(event_id, str):
                raise ToolError("effects view requires event_id selector")
            rows = self._store.rows(
                """
                SELECT effect_id, occurrence_id, amount, kind, logical_effect_key,
                       source_event_id, committed_tick
                FROM effects WHERE source_event_id = ?
                ORDER BY committed_tick
                LIMIT ?
                """,
                (event_id, MAX_INSPECT_ROWS),
            )
        elif view == "keys":
            if not isinstance(command_key, str) or not isinstance(occurrence_id, str):
                raise ToolError("keys view requires command_key and occurrence_id selectors")
            rows = self._store.rows(
                """
                SELECT command_key, occurrence_id, event_id, state
                FROM command_keys WHERE command_key = ? AND occurrence_id = ?
                """,
                (command_key, occurrence_id),
            )
        elif view == "progress":
            stream = selector.get("stream", "settlement")
            rows = self._store.rows(
                "SELECT stream, committed_seq FROM cursor WHERE stream = ?",
                (stream,),
            )
        elif view == "recovery":
            snapshot_id = selector.get("snapshot_id")
            if not isinstance(snapshot_id, str):
                raise ToolError("recovery view requires snapshot_id selector")
            rows = self._store.rows(
                """
                SELECT snapshot_id, state_root, cursor_seq, journal_root, effect_root, created_tick
                FROM recovery_snapshots WHERE snapshot_id = ?
                """,
                (snapshot_id,),
            )
        return {"view": view, "selector": selector, "rows": [list(r) for r in rows[:MAX_INSPECT_ROWS]]}

    def runtime_run(self, workload_id: str, cutpoint: str | None = None) -> dict[str, Any]:
        """runtime.run: execute a deterministic public workload or diagnostic cutpoint."""
        self._require_intake_paused()
        if workload_id.startswith("H-"):
            raise ToolError("unknown workload or missing cutpoint", code="unknown_workload")
        run_id = len(self._workload_history)
        active_config_root = self._active_config_root()
        engine = RuntimeEngine(
            self._store,
            self.active_workspace,
            self._profile,
            self._trace_authority,
            self.session_id,
            self._trace_epoch,
        )
        try:
            receipt = engine.run(workload_id, cutpoint, run_id=run_id)
        except (ValueError, TypeError, KeyError) as exc:
            raise ToolError("active workspace configuration invalid") from exc
        self._store.connection.commit()
        self._workload_history.append(receipt)
        if receipt["workload_id"] in ("P1", "P2", "P3") and receipt["outcome"] == "pass":
            self._public_workload_pass.setdefault(active_config_root, set()).add(
                receipt["workload_id"]
            )
        return receipt

    def recovery_pause(self) -> int:
        """recovery.pause: pause intake and return the tick."""
        try:
            return self._store.pause_intake()
        except RuntimeError as exc:
            raise ToolError(str(exc)) from exc

    def recovery_restore(self, snapshot_id: str = "S0") -> str:
        """recovery.restore: restore an authenticated snapshot."""
        self._require_intake_paused()
        try:
            result = self._store.restore_snapshot(snapshot_id)
        except (RuntimeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        self._public_workload_pass.pop(self._active_config_root(), None)
        self._bump_trace_epoch()
        return result

    def release_rollback(self, revision: str) -> dict[str, Any]:
        """release.rollback: activate a known revision (r0 or r1)."""
        self._require_intake_paused()
        if revision not in ("r0", "r1"):
            raise ToolError("rollback supports r0 or r1")
        try:
            code_root, config_bytes = self._revision_artifact(revision)
            self._copy_workspace(self.initial_workspace, self.active_workspace)
            settings_path = self.active_workspace / CONFIG_FILE
            settings_path.write_bytes(config_bytes)
            with self._store.connection:
                self._store.connection.execute(
                    "UPDATE deployments SET status = 'available'"
                )
                self._store.connection.execute(
                    """
                    UPDATE deployments SET status = 'active', activated_tick = ?
                    WHERE revision = ?
                    """,
                    (self._store.advance(), revision),
                )
            self._store.append_audit(
                "deployment_rollback",
                self._store.deployment_root(),
                "operator",
                self._store.tick(),
            )
            self._store.connection.commit()
            self._write_metadata()
            self._bump_trace_epoch()
            return {
                "revision": revision,
                "active_source_root": self._active_source_root(),
                "active_config_root": self._active_config_root(),
            }
        except RuntimeError as exc:
            raise ToolError(str(exc)) from exc
        except OSError as exc:
            raise ToolError("file operation failed") from exc

    def release_deploy(self) -> dict[str, Any]:
        """release.deploy: activate the candidate workspace."""
        self._require_intake_paused()
        candidate_source_root = self._candidate_root()
        candidate_config_bytes = self._candidate_settings_bytes()
        candidate_config_root = self._candidate_config_root()
        if (
            candidate_source_root == self._active_source_root()
            and candidate_config_root == self._active_config_root()
        ):
            raise ToolError("no candidate changes to deploy")
        try:
            self._copy_workspace(self.candidate_workspace, self.active_workspace)
            with self._store.connection:
                self._store.connection.execute(
                    """
                    UPDATE deployments
                    SET code_root = ?, config_root = ?, config_bytes = ?, activated_tick = ?
                    WHERE revision = 'candidate'
                    """,
                    (
                        candidate_source_root,
                        candidate_config_root,
                        candidate_config_bytes.decode("utf-8"),
                        self._store.advance(),
                    ),
                )
                self._store.connection.execute(
                    "UPDATE deployments SET status = 'available'"
                )
                self._store.connection.execute(
                    """
                    UPDATE deployments SET status = 'active' WHERE revision = 'candidate'
                    """
                )
            self._store.append_audit(
                "deployment_activate",
                self._store.deployment_root(),
                "operator",
                self._store.tick(),
            )
            self._store.connection.commit()
            self._write_metadata()
            self._bump_trace_epoch()
            return {
                "revision": "candidate",
                "active_source_root": self._active_source_root(),
                "active_config_root": self._active_config_root(),
            }
        except RuntimeError as exc:
            raise ToolError(str(exc)) from exc
        except OSError as exc:
            raise ToolError("file operation failed") from exc

    def recovery_resume(self) -> int:
        """recovery.resume: open intake after recovery and public checks."""
        self._require_intake_paused()
        if self._active_revision_label() != "candidate":
            raise ToolError("resume requires a deployed candidate")
        if not self._store.recovery_provenance_exists():
            raise ToolError("recovery provenance missing")
        passes = self._public_workload_pass.get(self._active_config_root(), set())
        if not {"P1", "P2", "P3"} <= passes:
            raise ToolError("public workloads not passed")
        tick = self._store.advance()
        self._store.set_runtime_value("intake_state", "open")
        self._store.append_audit(
            "intake_resume", self._store.state_root(), "operator", tick
        )
        self._store.append_telemetry(tick, "control", "intake resumed")
        self._store.connection.commit()
        self._write_metadata()
        self._bump_trace_epoch()
        return tick

    def tool_inventory(self) -> list[str]:
        return [
            "release.status",
            "workspace.read",
            "workspace.edit",
            "telemetry.logs",
            "telemetry.trace",
            "state.inspect",
            "runtime.run",
            "recovery.pause",
            "recovery.restore",
            "release.rollback",
            "release.deploy",
            "recovery.resume",
        ]

    def leak_probe(self) -> dict[str, Any]:
        """Executable probe that the session does not contain privileged material."""
        problems: list[str] = []
        forbidden_names = (
            ("service.sqlite3", "session contains fixture database"),
            ("tests", "session contains tests"),
            ("evidence", "session contains evidence"),
            ("src", "session contains privileged source"),
            (".git", "session contains repository"),
            ("agent_surface", "session contains agent package source"),
            ("event_service_substrate", "session contains substrate package source"),
        )
        for name, message in forbidden_names:
            if (self.session_dir / name).exists():
                problems.append(message)

        forbidden_tokens = [
            "profile",
            "member",
            "authority",
            "fixture_profile",
            "event_service_substrate",
            "agent_surface",
            "service.sqlite3",
            str(self._fixture.store.path),
            str(self._fixture.root),
        ]
        for path in self.session_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace").lower()
            except OSError:
                continue
            for token in forbidden_tokens:
                if token and token.lower() in text:
                    problems.append(f"session file {path.name} leaks {token!r}")

        for var_name in ("fixture_profile", "EVENT_SERVICE_MEMBER"):
            if var_name in os.environ:
                problems.append(f"process environment contains {var_name}")

        process_text = " ".join(sys.argv).lower()
        for token in ("fixture_profile",):
            if token in process_text:
                problems.append(f"process arguments leak token {token}")

        probe_path = self.session_dir / ".leak_probe_import.py"
        probe_path.write_text(
            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "try:\n"
            "    import event_service_substrate\n"
            "    print('reachable')\n"
            "except ImportError:\n"
            "    try:\n"
            "        import agent_surface\n"
            "        print('reachable')\n"
            "    except ImportError:\n"
            "        print('isolated')\n",
            encoding="utf-8",
        )
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        result = subprocess.run(
            [sys.executable, "-S", str(probe_path), str(self.session_dir)],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        probe_path.unlink(missing_ok=True)
        if result.stdout.strip() == "reachable":
            problems.append("session directory allows privileged package import")

        return {"passed": not problems, "problems": problems}
