"""Deterministic fake-clock runtime engine and service protocol implementation."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Final

from event_service_substrate.canonical import canonical_json, digest
from event_service_substrate.store import StateStore

from .errors import ToolError

STAGE_S1: Final[str] = "s1"
STAGE_S2: Final[str] = "s2"
STAGE_S3: Final[str] = "s3"
STAGE_S4: Final[str] = "s4"
STAGE_S5: Final[str] = "s5"
STAGE_S6: Final[str] = "s6"
STAGE_RESTART: Final[str] = "restart"
STAGE_CUTPOINT: Final[str] = "cutpoint"
STAGE_TRANSIENT: Final[str] = "transient"

EFFECT_AMOUNT: Final[int] = 100


class Cutpoint(Exception):
    """Raised when a neutral diagnostic cutpoint interrupts the flow."""

    def __init__(self, event_id: str | None = None, effect_id: str | None = None) -> None:
        self.event_id = event_id
        self.effect_id = effect_id
        super().__init__("cutpoint")


class TransientFailure(Exception):
    """Raised when a deterministic transient failure occurs before a commit."""


class RuntimeStore:
    """In-process protocol implementation backed by the canonical StateStore."""

    def __init__(
        self,
        store: StateStore,
        profile: int,
        cutpoint: str | None,
        workload_id: str,
        alias: str,
        handle: str,
    ) -> None:
        self.store = store
        self.profile = profile
        self.cutpoint = cutpoint
        self.workload_id = workload_id
        self.alias = alias
        self.handle = handle
        self.start_tick = store.tick()
        self._attempts: dict[str, int] = {}
        self._s2_cutpoint_pending = (cutpoint == "s2.exit") and (profile == 1)
        self._s5_cutpoint_pending = (cutpoint == "s5.exit") and (profile == 0)
        self._transient_pending = workload_id in ("P1", "P2") and cutpoint is None

    def _next_seq(self, table: str) -> int:
        row = self.store.connection.execute(
            f"SELECT COALESCE(MAX(seq), 0) + 1 FROM {table}"
        ).fetchone()
        return int(row[0])

    def _advance(self) -> int:
        return self.store.advance()

    def _append_trace(
        self,
        stage: str,
        event_id: str | None = None,
        command_key: str | None = None,
        occurrence_id: str | None = None,
    ) -> int:
        tick = self.store.tick()
        span_id = digest(
            "span-v1",
            canonical_json(
                [self.handle, stage, event_id, command_key, occurrence_id, tick]
            ),
        )
        return self.store.append_trace_span(
            correlation_handle=self.handle,
            span_id=span_id,
            parent_id=None,
            workload_id=self.workload_id,
            alias=self.alias,
            stage=stage,
            event_id=event_id,
            command_key=command_key,
            occurrence_id=occurrence_id,
            tick=tick,
        )

    def _log(self, message: str) -> int:
        return self.store.append_telemetry(self._advance(), "public", message)

    def _control(self, message: str) -> int:
        return self.store.append_telemetry(self.store.tick(), "control", message)

    def _new_event_id(self, command_key: str, occurrence_id: str, tick: int) -> str:
        return "evt_" + digest(
            "event-v1",
            canonical_json(
                [command_key, occurrence_id, tick, self.workload_id]
            ),
        )[:32]

    def _new_effect_id(self, event_id: str, occurrence_id: str, tick: int) -> str:
        return "efx_" + digest(
            "effect-v1",
            canonical_json([event_id, occurrence_id, tick, self.workload_id]),
        )[:32]

    def prepare(self, command: dict[str, str]) -> dict[str, str]:
        """s1: prepare the command."""
        self._advance()
        self._append_trace(STAGE_S1, command_key=command.get("command_key"))
        return dict(command)

    def append(self, command: dict[str, str]) -> str:
        """s2: append a journal event."""
        tick = self._advance()
        command_key = command["command_key"]
        occurrence_id = command["occurrence_id"]
        payload = canonical_json(command)
        payload_hash = digest("payload-v1", payload)
        event_id = self._new_event_id(command_key, occurrence_id, tick)
        self.store.connection.execute(
            """
            INSERT INTO journal(
                seq, event_id, command_key, occurrence_id, payload_hash, accepted_tick
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                self._next_seq("journal"),
                event_id,
                command_key,
                occurrence_id,
                payload_hash,
                tick,
            ),
        )
        self._append_trace(STAGE_S2, event_id, command_key, occurrence_id)
        if self._s2_cutpoint_pending:
            self._s2_cutpoint_pending = False
            self._append_trace(STAGE_CUTPOINT, event_id, command_key, occurrence_id)
            self._control(f"s2.exit cutpoint for {command_key}")
            raise Cutpoint(event_id=event_id)
        return event_id

    def register(self, command: dict[str, str], event_id: str) -> None:
        """s3: register command-key/occurrence mapping."""
        tick = self._advance()
        command_key = command["command_key"]
        occurrence_id = command["occurrence_id"]
        self.store.connection.execute(
            """
            INSERT OR REPLACE INTO command_keys(command_key, occurrence_id, event_id, state)
            VALUES (?, ?, ?, 'registered')
            """,
            (command_key, occurrence_id, event_id),
        )
        self._append_trace(STAGE_S3, event_id, command_key, occurrence_id)

    def load(self, event_id: str) -> dict[str, str]:
        """s4: load a journal event."""
        tick = self._advance()
        row = self.store.connection.execute(
            """
            SELECT seq, event_id, command_key, occurrence_id, payload_hash, accepted_tick
            FROM journal WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()
        if row is None:
            raise ToolError("event not found")
        _, event_id, command_key, occurrence_id, payload_hash, accepted_tick = row
        self._append_trace(STAGE_S4, event_id, command_key, occurrence_id)
        return {
            "event_id": event_id,
            "command_key": command_key,
            "occurrence_id": occurrence_id,
            "payload_hash": payload_hash,
            "accepted_tick": str(accepted_tick),
            "amount": str(EFFECT_AMOUNT),
        }

    def settle(self, event: dict[str, str]) -> str:
        """s5: request a settlement effect."""
        event_id = event["event_id"]
        occurrence_id = event["occurrence_id"]
        command_key = event["command_key"]
        attempt = self._attempts.get(event_id, 0) + 1
        self._attempts[event_id] = attempt
        tick = self._advance()
        if self._transient_pending and attempt == 1:
            self._transient_pending = False
            self._append_trace(STAGE_TRANSIENT, event_id, command_key, occurrence_id)
            self._control(f"transient failure before effect for {event_id}")
            raise TransientFailure()
        effect_id = self._new_effect_id(event_id, occurrence_id, tick)
        self.store.connection.execute(
            """
            INSERT INTO effects(
                effect_id, occurrence_id, amount, kind, source_event_id, committed_tick
            ) VALUES (?, ?, ?, 'settlement', ?, ?)
            """,
            (effect_id, occurrence_id, EFFECT_AMOUNT, event_id, tick),
        )
        self._append_trace(STAGE_S5, event_id, command_key, occurrence_id)
        if self._s5_cutpoint_pending:
            self._s5_cutpoint_pending = False
            self._append_trace(STAGE_CUTPOINT, event_id, command_key, occurrence_id)
            self._control(f"s5.exit cutpoint for {event_id}")
            raise Cutpoint(event_id=event_id, effect_id=effect_id)
        return effect_id

    def advance(self, sequence: int) -> None:
        """s6: advance cursor."""
        tick = self._advance()
        self.store.connection.execute(
            "UPDATE cursor SET committed_seq = ? WHERE stream = 'settlement'",
            (sequence,),
        )
        event_id = None
        command_key = None
        occurrence_id = None
        row = self.store.connection.execute(
            "SELECT event_id, command_key, occurrence_id FROM journal WHERE seq = ?",
            (sequence,),
        ).fetchone()
        if row is not None:
            event_id, command_key, occurrence_id = row
        self._append_trace(STAGE_S6, event_id, command_key, occurrence_id)

    def restart(self) -> None:
        """Reset in-memory attempt counters after a restart."""
        self._attempts.clear()
        tick = self._advance()
        self._append_trace(STAGE_RESTART, None, None, None)
        self._control("restart")


class RuntimeEngine:
    """Deterministic fake-clock executor for public workloads and cutpoints."""

    def __init__(self, store: StateStore, active_workspace: Path, profile: int) -> None:
        self.store = store
        self.active_workspace = active_workspace
        self.profile = profile

    def _read_config(self) -> dict[str, Any]:
        settings_path = self.active_workspace / "service" / "settings.toml"
        if not settings_path.exists():
            raise ToolError("active workspace settings.toml missing")
        return tomllib.loads(settings_path.read_text(encoding="utf-8"))

    def _attempt_budget(self, config: dict[str, Any]) -> int:
        return int(config["service"]["attempt_budget"])

    def _transient_behavior(self, config: dict[str, Any]) -> str:
        return str(config["service"].get("transient_behavior", "retry"))

    def _new_handle(
        self, workload_id: str, cutpoint: str | None, alias: str, run_id: int
    ) -> str:
        return "h_" + digest(
            "handle-v1",
            canonical_json(
                {
                    "workload_id": workload_id,
                    "cutpoint": cutpoint,
                    "alias": alias,
                    "tick": self.store.tick(),
                    "run_id": run_id,
                }
            ),
        )[:32]

    def _accept_command(
        self,
        runtime: RuntimeStore,
        command: dict[str, str],
        retry_after_s2_cutpoint: bool = True,
    ) -> str:
        prepared = runtime.prepare(command)
        try:
            event_id = runtime.append(prepared)
        except Cutpoint as cutpoint:
            event_id = cutpoint.event_id
            if not retry_after_s2_cutpoint:
                return event_id
            prepared = runtime.prepare(command)
            event_id = runtime.append(prepared)
        runtime.register(prepared, event_id)
        return event_id

    def _deliver_event(
        self,
        runtime: RuntimeStore,
        event_id: str,
        sequence: int,
        attempt_budget: int,
        retry_on_transient: bool,
    ) -> str:
        attempts = 0
        while attempts < attempt_budget:
            attempts += 1
            try:
                event = runtime.load(event_id)
                effect_id = runtime.settle(event)
                runtime.advance(sequence)
                return effect_id
            except TransientFailure:
                runtime._log(
                    f"t={self.store.tick()} delivery boundary interrupted alias={runtime.alias}"
                )
                if not retry_on_transient or attempts >= attempt_budget:
                    raise ToolError(
                        f"transient effect exceeded attempt budget {attempt_budget}"
                    )
            except Cutpoint:
                # s5.exit: restart and redeliver the same event.
                runtime.restart()
                attempts = 0
        raise ToolError("delivery exceeded attempt budget")

    def _public_canary_line(self, alias: str, effect_count: int) -> str:
        return f"t={self.store.tick()} settlement observed alias={alias} count={effect_count}"

    def _run_public_workload(self, runtime: RuntimeStore, attempt_budget: int) -> dict[str, Any]:
        if runtime.workload_id == "P1":
            commands = [
                {
                    "command_key": "cmd_routine_redelivery",
                    "occurrence_id": "occ_routine_redelivery",
                    "alias": runtime.alias,
                    "amount": str(EFFECT_AMOUNT),
                }
            ]
        elif runtime.workload_id == "P2":
            commands = [
                {
                    "command_key": "cmd_transient_effect",
                    "occurrence_id": "occ_transient_effect",
                    "alias": runtime.alias,
                    "amount": str(EFFECT_AMOUNT),
                }
            ]
        elif runtime.workload_id == "P3":
            commands = [
                {
                    "command_key": f"cmd_unique_{i}",
                    "occurrence_id": f"occ_unique_{i}",
                    "alias": runtime.alias,
                    "amount": str(EFFECT_AMOUNT),
                }
                for i in range(1, 4)
            ]
        else:
            raise ToolError(f"unknown public workload {runtime.workload_id}")

        event_ids: list[str] = []
        for command in commands:
            event_id = self._accept_command(runtime, command)
            event_ids.append(event_id)
            runtime._log(
                f"t={self.store.tick()} intake accepted alias={runtime.alias}"
            )

        effect_count = 0
        for event_id in event_ids:
            seq = self.store.connection.execute(
                "SELECT seq FROM journal WHERE event_id = ?", (event_id,)
            ).fetchone()
            if seq is None:
                raise ToolError("event not in journal")
            sequence = seq[0]
            runtime._log(
                f"t={self.store.tick()} delivery window opened alias={runtime.alias} attempt=1"
            )
            self._deliver_event(
                runtime, event_id, sequence, attempt_budget, retry_on_transient=True
            )
            effect_count += 1
            runtime._log(self._public_canary_line(runtime.alias, effect_count))

        return self._build_receipt(
            runtime,
            event_count=len(event_ids),
            effect_count=effect_count,
            net_effect_count=effect_count * EFFECT_AMOUNT,
            outcome="pass" if effect_count == len(event_ids) else "fail",
        )

    def _run_cutpoint_diagnostic(
        self, runtime: RuntimeStore, attempt_budget: int
    ) -> dict[str, Any]:
        command = {
            "command_key": "cmd_diagnostic",
            "occurrence_id": "occ_diagnostic",
            "alias": runtime.alias,
            "amount": str(EFFECT_AMOUNT),
        }
        if runtime.cutpoint == "s5.exit":
            event_id = self._accept_command(runtime, command)
            seq = self.store.connection.execute(
                "SELECT seq FROM journal WHERE event_id = ?", (event_id,)
            ).fetchone()
            if seq is None:
                raise ToolError("event not in journal")
            runtime._log(
                f"t={self.store.tick()} delivery window opened alias={runtime.alias} attempt=1"
            )
            self._deliver_event(
                runtime, event_id, seq[0], attempt_budget, retry_on_transient=False
            )
            effects = self.store.connection.execute(
                "SELECT COUNT(*) FROM effects WHERE source_event_id = ?", (event_id,)
            ).fetchone()[0]
            return self._build_receipt(
                runtime,
                event_count=1,
                effect_count=effects,
                net_effect_count=effects * EFFECT_AMOUNT,
                outcome="cutpoint",
            )
        if runtime.cutpoint == "s2.exit":
            start_seq = self.store.connection.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM journal"
            ).fetchone()[0]
            self._accept_command(runtime, command, retry_after_s2_cutpoint=True)
            runtime._log(
                f"t={self.store.tick()} intake accepted alias={runtime.alias}"
            )
            # Deliver all journal events created in this run.
            rows = self.store.connection.execute(
                "SELECT event_id, seq FROM journal WHERE seq >= ? ORDER BY seq",
                (start_seq,),
            ).fetchall()
            effect_count = 0
            for event_id, sequence in rows:
                runtime._log(
                    f"t={self.store.tick()} delivery window opened alias={runtime.alias} attempt=1"
                )
                self._deliver_event(
                    runtime, event_id, sequence, attempt_budget, retry_on_transient=False
                )
                effect_count += 1
            return self._build_receipt(
                runtime,
                event_count=len(rows),
                effect_count=effect_count,
                net_effect_count=effect_count * EFFECT_AMOUNT,
                outcome="cutpoint",
            )
        raise ToolError(f"unsupported cutpoint {runtime.cutpoint}")

    def _build_receipt(
        self,
        runtime: RuntimeStore,
        event_count: int,
        effect_count: int,
        net_effect_count: int,
        outcome: str,
    ) -> dict[str, Any]:
        cursor = self.store.connection.execute(
            "SELECT committed_seq FROM cursor WHERE stream = 'settlement'"
        ).fetchone()[0]
        return {
            "workload_id": runtime.workload_id,
            "cutpoint": runtime.cutpoint,
            "handle": runtime.handle,
            "alias": runtime.alias,
            "start_tick": runtime.start_tick,
            "end_tick": self.store.tick(),
            "event_count": event_count,
            "effect_count": effect_count,
            "net_effect_count": net_effect_count,
            "cursor_seq": cursor,
            "outcome": outcome,
        }

    def run(
        self, workload_id: str, cutpoint: str | None = None, run_id: int = 0
    ) -> dict[str, Any]:
        """Execute a public workload or diagnostic cutpoint run."""
        config = self._read_config()
        attempt_budget = self._attempt_budget(config)
        if workload_id in ("P1", "P2", "P3"):
            if cutpoint is not None:
                raise ToolError("public workloads do not accept cutpoints")
            alias = workload_id
            handle = self._new_handle(workload_id, cutpoint, alias, run_id)
        elif cutpoint in ("s5.exit", "s2.exit"):
            alias = workload_id
            handle = self._new_handle(workload_id, cutpoint, alias, run_id)
        else:
            raise ToolError(f"unknown workload or missing cutpoint: {workload_id}")
        runtime = RuntimeStore(
            self.store, self.profile, cutpoint, workload_id, alias, handle
        )
        runtime._control(
            f"workload {workload_id} cutpoint {cutpoint} handle {handle} alias {alias}"
        )
        if workload_id in ("P1", "P2", "P3"):
            return self._run_public_workload(runtime, attempt_budget)
        return self._run_cutpoint_diagnostic(runtime, attempt_budget)
