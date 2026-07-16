"""Deterministic fake-clock runtime engine and service protocol implementation."""

from __future__ import annotations

import importlib
import sys
import tomllib
from pathlib import Path
from typing import Any, Final

from event_service_substrate.canonical import canonical_json, digest
from event_service_substrate.store import StateStore

from .errors import ToolError
from .trace import TraceCapabilityAuthority

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

VIEWS: Final[frozenset[str]] = frozenset({"journal", "effects", "keys", "trace"})


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
        transient: bool | None = None,
    ) -> None:
        self.store = store
        self.profile = profile
        self.cutpoint = cutpoint
        self.workload_id = workload_id
        self.alias = alias
        self.handle = handle
        self.start_tick = store.tick()
        self._attempts: dict[str, int] = {}
        self._cutpoint_triggered = False
        self._s2_cutpoint_pending = (cutpoint == "s2.exit") and (profile == 1)
        self._s5_cutpoint_pending = (cutpoint == "s5.exit") and (profile == 0)
        if transient is None:
            transient = workload_id in ("P1", "P2") and cutpoint is None
        self._transient_pending = transient and cutpoint is None
        self._selectors: list[dict[str, Any]] = []

    @property
    def trace_selectors(self) -> list[dict[str, Any]]:
        """Distinct selectors observed during this trace."""
        seen: set[tuple[str, str | None, str | None]] = set()
        distinct: list[dict[str, Any]] = []
        for sel in self._selectors:
            key = (sel.get("event_id"), sel.get("command_key"), sel.get("occurrence_id"))
            if key not in seen:
                seen.add(key)
                distinct.append(sel)
        return distinct

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
        if event_id is not None:
            self._selectors.append(
                {
                    "event_id": event_id,
                    "command_key": command_key,
                    "occurrence_id": occurrence_id,
                }
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

    def _new_effect_id(
        self, event_id: str, occurrence_id: str, logical_effect_key: str, tick: int
    ) -> str:
        return "efx_" + digest(
            "effect-v1",
            canonical_json(
                [event_id, occurrence_id, logical_effect_key, tick, self.workload_id]
            ),
        )[:32]

    def _payload_hash(self, command: dict[str, str]) -> str:
        return digest("payload-v1", canonical_json(command))

    def _existing_payload_hash(
        self, command_key: str, occurrence_id: str
    ) -> str | None:
        row = self.store.connection.execute(
            """
            SELECT payload_hash FROM journal
            WHERE command_key = ? AND occurrence_id = ?
            ORDER BY seq LIMIT 1
            """,
            (command_key, occurrence_id),
        ).fetchone()
        return str(row[0]) if row is not None else None

    def _reject_conflicting_payload(
        self, command_key: str, occurrence_id: str, payload_hash: str
    ) -> None:
        existing = self._existing_payload_hash(command_key, occurrence_id)
        if existing is not None and existing != payload_hash:
            raise ToolError("conflicting payload")

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
        payload_hash = self._payload_hash(command)
        self._reject_conflicting_payload(command_key, occurrence_id, payload_hash)
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
            self._cutpoint_triggered = True
            raise Cutpoint(event_id=event_id)
        return event_id

    def register(self, command: dict[str, str], event_id: str) -> None:
        """s3: register command-key/occurrence mapping."""
        tick = self._advance()
        command_key = command["command_key"]
        occurrence_id = command["occurrence_id"]
        self._reject_conflicting_payload(
            command_key, occurrence_id, self._payload_hash(command)
        )
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
        logical_effect_key = event.get("logical_effect_key", "settlement")
        attempt = self._attempts.get(event_id, 0) + 1
        self._attempts[event_id] = attempt
        tick = self._advance()
        if self._transient_pending and attempt == 1:
            self._transient_pending = False
            self._append_trace(STAGE_TRANSIENT, event_id, command_key, occurrence_id)
            self._control(f"transient failure before effect for {event_id}")
            raise TransientFailure()
        effect_id = self._new_effect_id(
            event_id, occurrence_id, logical_effect_key, tick
        )
        self.store.connection.execute(
            """
            INSERT INTO effects(
                effect_id, occurrence_id, amount, kind, logical_effect_key,
                source_event_id, committed_tick
            ) VALUES (?, ?, ?, 'settlement', ?, ?, ?)
            """,
            (
                effect_id,
                occurrence_id,
                EFFECT_AMOUNT,
                logical_effect_key,
                event_id,
                tick,
            ),
        )
        self._append_trace(STAGE_S5, event_id, command_key, occurrence_id)
        if self._s5_cutpoint_pending:
            self._s5_cutpoint_pending = False
            self._append_trace(STAGE_CUTPOINT, event_id, command_key, occurrence_id)
            self._control(f"s5.exit cutpoint for {event_id}")
            self._cutpoint_triggered = True
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

    def get_event_id(self, command_key: str, occurrence_id: str) -> str | None:
        """Return the event id for an already accepted command occurrence.

        This is an optional helper for idempotent intake repairs in
        ``service.flow.s2``.
        """
        row = self.store.connection.execute(
            "SELECT event_id FROM journal WHERE command_key = ? AND occurrence_id = ? ORDER BY seq LIMIT 1",
            (command_key, occurrence_id),
        ).fetchone()
        return str(row[0]) if row is not None else None

    def get_command_registration(
        self, command_key: str, occurrence_id: str
    ) -> dict[str, str] | None:
        """Return event and payload metadata for a registered command occurrence."""
        row = self.store.connection.execute(
            """
            SELECT event_id, payload_hash
            FROM journal
            WHERE command_key = ? AND occurrence_id = ?
            ORDER BY seq LIMIT 1
            """,
            (command_key, occurrence_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "event_id": str(row[0]),
            "payload_hash": str(row[1]),
        }

    def effect_exists(self, event_id: str) -> str | None:
        """Return an existing effect id for an event.

        This is an optional helper for idempotent settlement repairs in
        ``service.flow.s5``.
        """
        row = self.store.connection.execute(
            "SELECT effect_id FROM effects WHERE source_event_id = ? ORDER BY committed_tick LIMIT 1",
            (event_id,),
        ).fetchone()
        return str(row[0]) if row is not None else None

    def effect_by_key(self, event_id: str, logical_effect_key: str) -> str | None:
        """Return an effect id for the event and logical effect key."""
        row = self.store.connection.execute(
            """
            SELECT effect_id FROM effects
            WHERE source_event_id = ? AND logical_effect_key = ?
            ORDER BY committed_tick LIMIT 1
            """,
            (event_id, logical_effect_key),
        ).fetchone()
        return str(row[0]) if row is not None else None

    def intent_create(
        self,
        event_id: str,
        command_key: str,
        occurrence_id: str,
        logical_effect_key: str = "settlement",
    ) -> str:
        """Create an atomic effect-intent record for the event."""
        tick = self._advance()
        intent_id = "int_" + digest(
            "intent-v1",
            canonical_json(
                [
                    event_id,
                    command_key,
                    occurrence_id,
                    logical_effect_key,
                    tick,
                    self.workload_id,
                ]
            ),
        )[:32]
        self.store.connection.execute(
            """
            INSERT INTO intents(
                intent_id, source_event_id, command_key, occurrence_id,
                logical_effect_key, created_tick, state, effect_id
            ) VALUES (?, ?, ?, ?, ?, ?, 'created', NULL)
            """,
            (
                intent_id,
                event_id,
                command_key,
                occurrence_id,
                logical_effect_key,
                tick,
            ),
        )
        return intent_id

    def intent_complete(self, intent_id: str, effect_id: str) -> None:
        """Mark an intent as completed with an effect id."""
        self._advance()
        self.store.connection.execute(
            "UPDATE intents SET state = 'completed', effect_id = ? WHERE intent_id = ?",
            (effect_id, intent_id),
        )

    def mark_event(
        self, event_id: str, mark_key: str, mark_state: str = "marked"
    ) -> None:
        """Add a neutral event mark for debugging/audit purposes."""
        self._advance()
        self.store.connection.execute(
            """
            INSERT OR REPLACE INTO event_marks(event_id, mark_key, mark_state)
            VALUES (?, ?, ?)
            """,
            (event_id, mark_key, mark_state),
        )

    def get_intent(
        self, event_id: str, logical_effect_key: str = "settlement"
    ) -> dict[str, str] | None:
        """Return the latest intent for an event and logical effect key."""
        row = self.store.connection.execute(
            """
            SELECT intent_id, source_event_id, command_key, occurrence_id,
                   logical_effect_key, created_tick, state, effect_id
            FROM intents
            WHERE source_event_id = ? AND logical_effect_key = ?
            ORDER BY created_tick DESC LIMIT 1
            """,
            (event_id, logical_effect_key),
        ).fetchone()
        if row is None:
            return None
        return {
            "intent_id": row[0],
            "source_event_id": row[1],
            "command_key": row[2],
            "occurrence_id": row[3],
            "logical_effect_key": row[4],
            "created_tick": str(row[5]),
            "state": row[6],
            "effect_id": row[7] or "",
        }


class RuntimeEngine:
    """Deterministic fake-clock executor for public workloads and cutpoints."""

    def __init__(
        self,
        store: StateStore,
        active_workspace: Path,
        profile: int,
        trace_authority: TraceCapabilityAuthority,
        session_id: str,
        trace_epoch: int,
    ) -> None:
        self.store = store
        self.active_workspace = active_workspace
        self.profile = profile
        self._trace_authority = trace_authority
        self._session_id = session_id
        self._trace_epoch = trace_epoch
        self._active_config_root = self._config_root(self._active_settings_bytes())
        sys.dont_write_bytecode = True

    def _active_settings_bytes(self) -> bytes:
        return (self.active_workspace / "service" / "settings.toml").read_bytes()

    def _config_root(self, config_bytes: bytes) -> str:
        return digest("config-v1", config_bytes)

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
        return self._trace_authority.derive_placeholder(
            session_id=self._session_id,
            epoch=self._trace_epoch,
            run_id=run_id,
            workload_id=workload_id,
            alias=alias,
            tick=self.store.tick(),
        )

    def _load_service_runtime(self) -> Any:
        """Load the agent's public service runtime module from the active workspace."""
        active = str(self.active_workspace)
        if active not in sys.path:
            sys.path.insert(0, active)
        for name in list(sys.modules.keys()):
            if name == "service" or name.startswith("service."):
                del sys.modules[name]
        try:
            import service.runtime as runtime  # type: ignore[import]
            import service.flow as flow  # type: ignore[import]

            if not hasattr(runtime, "accept") or not hasattr(runtime, "deliver"):
                raise ToolError("active workspace service/runtime.py is missing accept/deliver")
            return runtime
        finally:
            try:
                sys.path.remove(active)
            except ValueError:
                pass

    def _accept_command(
        self,
        runtime: RuntimeStore,
        service_runtime: Any,
        command: dict[str, str],
        retry_after_s2_cutpoint: bool = True,
    ) -> str:
        try:
            return service_runtime.accept(command, runtime)
        except Cutpoint as cutpoint:
            event_id = cutpoint.event_id
            if not retry_after_s2_cutpoint or event_id is None:
                return event_id if event_id is not None else ""
            # retry: the flow's s2 must be idempotent or it will duplicate the event.
            service_runtime.accept(command, runtime)
            return event_id

    def _deliver_event(
        self,
        runtime: RuntimeStore,
        service_runtime: Any,
        event_id: str,
        sequence: int,
        attempt_budget: int,
        retry_on_transient: bool,
    ) -> str:
        attempts = 0
        while attempts < attempt_budget:
            attempts += 1
            try:
                return service_runtime.deliver(event_id, sequence, runtime)
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

    def _run_public_workload(self, runtime: RuntimeStore, service_runtime: Any, attempt_budget: int) -> dict[str, Any]:
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
            event_id = self._accept_command(runtime, service_runtime, command)
            event_ids.append(event_id)
            runtime._log(
                f"t={self.store.tick()} intake accepted alias={runtime.alias}"
            )

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
                runtime, service_runtime, event_id, sequence, attempt_budget, retry_on_transient=True
            )
            durable_count = self._effect_count_for_event_keys(
                [event_id], ["settlement"]
            )
            runtime._log(self._public_canary_line(runtime.alias, durable_count))

        validation = self._validate_durable_outcome(
            expected_event_count=len(commands),
            expected_effect_count=len(commands),
            event_ids_or_command_pairs=[
                (command["command_key"], command["occurrence_id"])
                for command in commands
            ],
        )
        return self._build_receipt(
            runtime,
            event_count=validation["event_count"],
            effect_count=validation["effect_count"],
            net_effect_count=validation["net_effect_count"],
            outcome=validation["outcome"],
        )

    def _run_cutpoint_diagnostic(
        self, runtime: RuntimeStore, service_runtime: Any, attempt_budget: int
    ) -> dict[str, Any]:
        # Consecutive s2/s5 diagnostics must not reuse one logical command. Their
        # workload aliases are part of the payload, so sharing an identity makes
        # the second diagnostic look like a conflicting replay before its cutpoint
        # can execute. Preserve the established s2 identity and isolate s5.
        identity = "diagnostic_s5" if runtime.cutpoint == "s5.exit" else "diagnostic"
        command = {
            "command_key": f"cmd_{identity}",
            "occurrence_id": f"occ_{identity}",
            "alias": runtime.alias,
            "amount": str(EFFECT_AMOUNT),
        }
        if runtime.cutpoint == "s5.exit":
            event_id = self._accept_command(runtime, service_runtime, command)
            seq = self.store.connection.execute(
                "SELECT seq FROM journal WHERE event_id = ?", (event_id,)
            ).fetchone()
            if seq is None:
                raise ToolError("event not in journal")
            runtime._log(
                f"t={self.store.tick()} delivery window opened alias={runtime.alias} attempt=1"
            )
            self._deliver_event(
                runtime, service_runtime, event_id, seq[0], attempt_budget, retry_on_transient=False
            )
            effects = self.store.connection.execute(
                "SELECT COUNT(*) FROM effects WHERE source_event_id = ?", (event_id,)
            ).fetchone()[0]
            return self._build_receipt(
                runtime,
                event_count=1,
                effect_count=effects,
                net_effect_count=effects * EFFECT_AMOUNT,
                outcome="cutpoint" if runtime._cutpoint_triggered else "diagnostic",
            )
        if runtime.cutpoint == "s2.exit":
            start_seq = self.store.connection.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM journal"
            ).fetchone()[0]
            self._accept_command(runtime, service_runtime, command, retry_after_s2_cutpoint=True)
            runtime._log(
                f"t={self.store.tick()} intake accepted alias={runtime.alias}"
            )
            # Deliver all journal events created in this run.
            rows = self.store.connection.execute(
                "SELECT event_id, seq FROM journal WHERE seq >= ? ORDER BY seq",
                (start_seq,),
            ).fetchall()
            for event_id, sequence in rows:
                runtime._log(
                    f"t={self.store.tick()} delivery window opened alias={runtime.alias} attempt=1"
                )
                self._deliver_event(
                    runtime, service_runtime, event_id, sequence, attempt_budget, retry_on_transient=False
                )
            effect_count = self._effect_count_for_rows(rows)
            return self._build_receipt(
                runtime,
                event_count=len(rows),
                effect_count=effect_count,
                net_effect_count=effect_count * EFFECT_AMOUNT,
                outcome="cutpoint" if runtime._cutpoint_triggered else "diagnostic",
            )
        raise ToolError(f"unsupported cutpoint {runtime.cutpoint}")

    def _run_hidden_workload(
        self, runtime: RuntimeStore, service_runtime: Any, attempt_budget: int
    ) -> dict[str, Any]:
        """Execute a hidden workload for the strict verifier.

        These workloads are not part of the agent-legal runtime tool surface.
        They are called directly by the verifier to exercise boundary cases.
        """
        if runtime.workload_id == "H-A1":
            # Member A: effect succeeds but worker acknowledgement/progress is lost.
            # The s5.exit cutpoint leaves a committed effect without returning the id.
            commands = [
                {
                    "command_key": "cmd_a_effect_ack",
                    "occurrence_id": "occ_a_effect_ack",
                    "alias": runtime.alias,
                    "amount": str(EFFECT_AMOUNT),
                }
            ]
            for command in commands:
                self._accept_command(runtime, service_runtime, command)
            rows = self.store.connection.execute(
                "SELECT event_id, seq FROM journal WHERE command_key = ? AND occurrence_id = ?",
                (commands[0]["command_key"], commands[0]["occurrence_id"]),
            ).fetchall()
            for event_id, sequence in rows:
                self._deliver_event(
                    runtime, service_runtime, event_id, sequence, attempt_budget, retry_on_transient=False
                )
                runtime._log(
                    f"t={self.store.tick()} hidden effect delivered {event_id}"
                )
            event_count = len(rows)
            effect_count = self._effect_count_for_rows(rows)
            return self._build_receipt(
                runtime,
                event_count=event_count,
                effect_count=effect_count,
                net_effect_count=effect_count * EFFECT_AMOUNT,
                outcome="pass" if event_count == 1 and effect_count == 1 else "fail",
            )

        if runtime.workload_id == "H-A2":
            # Member A: two legitimate occurrences sharing the same business key.
            # A coarse deduplication that suppresses by command_key alone would fail.
            commands = [
                {
                    "command_key": "cmd_a_shared_key",
                    "occurrence_id": "occ_a_first",
                    "alias": runtime.alias,
                    "amount": str(EFFECT_AMOUNT),
                },
                {
                    "command_key": "cmd_a_shared_key",
                    "occurrence_id": "occ_a_second",
                    "alias": runtime.alias,
                    "amount": str(EFFECT_AMOUNT),
                },
            ]
            for command in commands:
                self._accept_command(runtime, service_runtime, command)
            pairs = [(c["command_key"], c["occurrence_id"]) for c in commands]
            placeholders = ",".join("(?,?)" for _ in pairs)
            params = [p for pair in pairs for p in pair]
            rows = self.store.connection.execute(
                f"SELECT event_id, seq FROM journal WHERE (command_key, occurrence_id) IN ({placeholders})",
                params,
            ).fetchall()
            for event_id, sequence in rows:
                self._deliver_event(
                    runtime, service_runtime, event_id, sequence, attempt_budget, retry_on_transient=False
                )
            event_count = len(rows)
            effect_count = self._effect_count_for_rows(rows)
            return self._build_receipt(
                runtime,
                event_count=event_count,
                effect_count=effect_count,
                net_effect_count=effect_count * EFFECT_AMOUNT,
                outcome="pass" if event_count == 2 and effect_count == 2 else "fail",
            )

        if runtime.workload_id == "H-B1":
            # Member B: command registration succeeds but response is lost.
            # s2.exit cutpoint then client retry should return the same journal id.
            command = {
                "command_key": "cmd_b_idempotent_retry",
                "occurrence_id": "occ_b_retry",
                "alias": runtime.alias,
                "amount": str(EFFECT_AMOUNT),
            }
            self._accept_command(runtime, service_runtime, command, retry_after_s2_cutpoint=True)
            rows = self.store.connection.execute(
                "SELECT event_id, seq FROM journal WHERE command_key = ? AND occurrence_id = ? ORDER BY seq",
                (command["command_key"], command["occurrence_id"]),
            ).fetchall()
            for event_id, sequence in rows:
                self._deliver_event(
                    runtime, service_runtime, event_id, sequence, attempt_budget, retry_on_transient=False
                )
            effect_count = self._effect_count_for_rows(rows)
            return self._build_receipt(
                runtime,
                event_count=len(rows),
                effect_count=effect_count,
                net_effect_count=effect_count * EFFECT_AMOUNT,
                outcome="pass" if len(rows) == 1 and effect_count == 1 else "fail",
            )

        if runtime.workload_id == "H-B2":
            # Member B: same command shape and occurrence retried explicitly should
            # produce a single journal id and single effect.
            command = {
                "command_key": "cmd_b_same_occurrence",
                "occurrence_id": "occ_b_same",
                "alias": runtime.alias,
                "amount": str(EFFECT_AMOUNT),
            }
            for _ in range(2):
                self._accept_command(runtime, service_runtime, command)
            rows = self.store.connection.execute(
                "SELECT event_id, seq FROM journal WHERE command_key = ? AND occurrence_id = ? ORDER BY seq",
                (command["command_key"], command["occurrence_id"]),
            ).fetchall()
            for event_id, sequence in rows:
                self._deliver_event(
                    runtime, service_runtime, event_id, sequence, attempt_budget, retry_on_transient=False
                )
            effect_count = self._effect_count_for_rows(rows)
            return self._build_receipt(
                runtime,
                event_count=len(rows),
                effect_count=effect_count,
                net_effect_count=effect_count * EFFECT_AMOUNT,
                outcome="pass" if len(rows) == 1 and effect_count == 1 else "fail",
            )

        if runtime.workload_id == "H-A3":
            # Profile 0: one event legitimately emits two independent logical effects.
            command = {
                "command_key": "cmd_a_logical_multi",
                "occurrence_id": "occ_a_logical_multi",
                "alias": runtime.alias,
                "amount": str(EFFECT_AMOUNT),
            }
            event_id = self._accept_command(runtime, service_runtime, command)
            seq = self.store.connection.execute(
                "SELECT seq FROM journal WHERE event_id = ?", (event_id,)
            ).fetchone()
            if seq is None:
                raise ToolError("event not in journal")
            self._deliver_event(
                runtime, service_runtime, event_id, seq[0], attempt_budget, retry_on_transient=False
            )
            event = runtime.load(event_id)
            event["logical_effect_key"] = "notify"
            flow_module = sys.modules.get("service.flow")
            if flow_module is None or not hasattr(flow_module, "s5"):
                raise ToolError("active workspace service/flow.py is missing s5")
            flow_module.s5(event, runtime)
            rows = self.store.connection.execute(
                """
                SELECT logical_effect_key FROM effects
                WHERE source_event_id = ?
                ORDER BY logical_effect_key
                """,
                (event_id,),
            ).fetchall()
            keys = [row[0] for row in rows]
            effect_count = len(keys)
            return self._build_receipt(
                runtime,
                event_count=1,
                effect_count=effect_count,
                net_effect_count=effect_count * EFFECT_AMOUNT,
                outcome="pass" if keys == ["notify", "settlement"] else "fail",
            )

        if runtime.workload_id == "H-A4":
            # Profile 0: redeliver the same logical effect after a restart boundary.
            command = {
                "command_key": "cmd_a_restart_retry",
                "occurrence_id": "occ_a_restart_retry",
                "alias": runtime.alias,
                "amount": str(EFFECT_AMOUNT),
            }
            event_id = self._accept_command(runtime, service_runtime, command)
            seq = self.store.connection.execute(
                "SELECT seq FROM journal WHERE event_id = ?", (event_id,)
            ).fetchone()
            if seq is None:
                raise ToolError("event not in journal")
            self._deliver_event(
                runtime, service_runtime, event_id, seq[0], attempt_budget, retry_on_transient=False
            )
            effect_count = self._effect_count_for_event_keys([event_id], ["settlement"])
            return self._build_receipt(
                runtime,
                event_count=1,
                effect_count=effect_count,
                net_effect_count=effect_count * EFFECT_AMOUNT,
                outcome="pass" if effect_count == 1 else "fail",
            )

        if runtime.workload_id == "H-B3":
            # Profile 1: same command occurrence with a different payload must not merge.
            first = {
                "command_key": "cmd_b_conflict",
                "occurrence_id": "occ_b_conflict",
                "alias": runtime.alias,
                "amount": "100",
            }
            second = {
                "command_key": "cmd_b_conflict",
                "occurrence_id": "occ_b_conflict",
                "alias": runtime.alias,
                "amount": "101",
            }
            self._accept_command(runtime, service_runtime, first)
            rejected = False
            try:
                self._accept_command(runtime, service_runtime, second)
            except ToolError:
                rejected = True
            rows = self.store.connection.execute(
                """
                SELECT event_id, seq FROM journal
                WHERE command_key = ? AND occurrence_id = ?
                ORDER BY seq
                """,
                (first["command_key"], first["occurrence_id"]),
            ).fetchall()
            return self._build_receipt(
                runtime,
                event_count=len(rows),
                effect_count=0,
                net_effect_count=0,
                # Pass if the conflicting payload did not create a second journal row.
                # Explicit rejection is preferred but not required when idempotent s2
                # returns the prior event id without merging payloads.
                outcome="pass" if len(rows) == 1 else "fail",
            )

        if runtime.workload_id == "H-B4":
            # Profile 1: same command key with distinct occurrences is legitimate.
            commands = [
                {
                    "command_key": "cmd_b_legit_repeat",
                    "occurrence_id": "occ_b_legit_first",
                    "alias": runtime.alias,
                    "amount": str(EFFECT_AMOUNT),
                },
                {
                    "command_key": "cmd_b_legit_repeat",
                    "occurrence_id": "occ_b_legit_second",
                    "alias": runtime.alias,
                    "amount": str(EFFECT_AMOUNT),
                },
            ]
            event_ids = [self._accept_command(runtime, service_runtime, cmd) for cmd in commands]
            rows = self.store.connection.execute(
                """
                SELECT event_id, seq FROM journal
                WHERE command_key = ?
                ORDER BY seq
                """,
                (commands[0]["command_key"],),
            ).fetchall()
            for event_id, sequence in rows:
                self._deliver_event(
                    runtime, service_runtime, event_id, sequence, attempt_budget, retry_on_transient=False
                )
            effect_count = self._effect_count_for_rows(rows)
            return self._build_receipt(
                runtime,
                event_count=len(event_ids),
                effect_count=effect_count,
                net_effect_count=effect_count * EFFECT_AMOUNT,
                outcome="pass" if len(rows) == 2 and effect_count == 2 else "fail",
            )

        if runtime.workload_id == "H-S1":
            # Shared recovery regression: replay public-like redelivery and ensure
            # the restored state plus idempotent code yields no loss and no excess.
            commands = [
                {
                    "command_key": "cmd_s_recovery_first",
                    "occurrence_id": "occ_s_recovery_first",
                    "alias": runtime.alias,
                    "amount": str(EFFECT_AMOUNT),
                },
                {
                    "command_key": "cmd_s_recovery_second",
                    "occurrence_id": "occ_s_recovery_second",
                    "alias": runtime.alias,
                    "amount": str(EFFECT_AMOUNT),
                },
            ]
            event_ids = [self._accept_command(runtime, service_runtime, cmd) for cmd in commands]
            for event_id in event_ids:
                seq = self.store.connection.execute(
                    "SELECT seq FROM journal WHERE event_id = ?", (event_id,)
                ).fetchone()
                if seq is None:
                    raise ToolError("event not in journal")
                self._deliver_event(
                    runtime, service_runtime, event_id, seq[0], attempt_budget, retry_on_transient=False
                )
            validation = self._validate_durable_outcome(
                expected_event_count=len(commands),
                expected_effect_count=len(commands),
                event_ids_or_command_pairs=[
                    (command["command_key"], command["occurrence_id"])
                    for command in commands
                ],
            )
            return self._build_receipt(
                runtime,
                event_count=validation["event_count"],
                effect_count=validation["effect_count"],
                net_effect_count=validation["net_effect_count"],
                outcome=validation["outcome"],
            )

        if runtime.workload_id == "H-S2":
            # Shared compatibility: repeat the same occurrence several times and
            # check the contract of at most one durable effect per new accepted occurrence.
            command = {
                "command_key": "cmd_s_compat",
                "occurrence_id": "occ_s_compat",
                "alias": runtime.alias,
                "amount": str(EFFECT_AMOUNT),
            }
            for _ in range(3):
                self._accept_command(runtime, service_runtime, command)
            rows = self.store.connection.execute(
                "SELECT event_id, seq FROM journal WHERE command_key = ? AND occurrence_id = ? ORDER BY seq",
                (command["command_key"], command["occurrence_id"]),
            ).fetchall()
            for event_id, sequence in rows:
                self._deliver_event(
                    runtime, service_runtime, event_id, sequence, attempt_budget, retry_on_transient=False
                )
            validation = self._validate_durable_outcome(
                expected_event_count=1,
                expected_effect_count=1,
                event_ids_or_command_pairs=[
                    (command["command_key"], command["occurrence_id"])
                ],
            )
            return self._build_receipt(
                runtime,
                event_count=validation["event_count"],
                effect_count=validation["effect_count"],
                net_effect_count=validation["net_effect_count"],
                outcome=validation["outcome"],
            )

        if runtime.workload_id == "H-TRANS":
            # Shared pre-effect transient failure followed by retry.
            command = {
                "command_key": "cmd_s_transient",
                "occurrence_id": "occ_s_transient",
                "alias": runtime.alias,
                "amount": str(EFFECT_AMOUNT),
            }
            event_id = self._accept_command(runtime, service_runtime, command)
            seq = self.store.connection.execute(
                "SELECT seq FROM journal WHERE event_id = ?", (event_id,)
            ).fetchone()
            if seq is None:
                raise ToolError("event not in journal")
            self._deliver_event(
                runtime, service_runtime, event_id, seq[0], attempt_budget, retry_on_transient=True
            )
            validation = self._validate_durable_outcome(
                expected_event_count=1,
                expected_effect_count=1,
                event_ids_or_command_pairs=[
                    (command["command_key"], command["occurrence_id"])
                ],
            )
            return self._build_receipt(
                runtime,
                event_count=validation["event_count"],
                effect_count=validation["effect_count"],
                net_effect_count=validation["net_effect_count"],
                outcome=validation["outcome"],
            )

        if runtime.workload_id == "H-S3":
            # Shared: deterministic interleaved redelivery of the same occurrence.
            command = {
                "command_key": "cmd_s_interleaved",
                "occurrence_id": "occ_s_interleaved",
                "alias": runtime.alias,
                "amount": str(EFFECT_AMOUNT),
            }
            first_event_id = self._accept_command(runtime, service_runtime, command)
            runtime.restart()
            self._accept_command(runtime, service_runtime, command)
            rows = self.store.connection.execute(
                """
                SELECT event_id, seq FROM journal
                WHERE command_key = ? AND occurrence_id = ?
                ORDER BY seq
                """,
                (command["command_key"], command["occurrence_id"]),
            ).fetchall()
            if rows:
                self._deliver_event(
                    runtime,
                    service_runtime,
                    first_event_id,
                    rows[0][1],
                    attempt_budget,
                    retry_on_transient=False,
                )
                runtime.restart()
                self._deliver_event(
                    runtime,
                    service_runtime,
                    first_event_id,
                    rows[0][1],
                    attempt_budget,
                    retry_on_transient=False,
                )
            effect_count = self._effect_count_for_rows(rows)
            return self._build_receipt(
                runtime,
                event_count=len(rows),
                effect_count=effect_count,
                net_effect_count=effect_count * EFFECT_AMOUNT,
                outcome="pass" if len(rows) == 1 and effect_count == 1 else "fail",
            )

        raise ToolError(f"unsupported hidden workload {runtime.workload_id}")

    def _effect_count_for_rows(self, rows: list[tuple[str, int]]) -> int:
        if not rows:
            return 0
        event_ids = [event_id for event_id, _ in rows]
        return self._effect_count_for_event_keys(event_ids, None)

    def _journal_rows_for_scope(
        self, event_ids_or_command_pairs: list[str | tuple[str, str]]
    ) -> list[tuple[str, int]]:
        if not event_ids_or_command_pairs:
            return []
        first = event_ids_or_command_pairs[0]
        if isinstance(first, tuple):
            clauses = []
            params: list[Any] = []
            for command_key, occurrence_id in event_ids_or_command_pairs:
                clauses.append("(command_key = ? AND occurrence_id = ?)")
                params.extend([command_key, occurrence_id])
            return [
                (str(event_id), int(seq))
                for event_id, seq in self.store.connection.execute(
                    f"""
                    SELECT event_id, seq FROM journal
                    WHERE {' OR '.join(clauses)}
                    ORDER BY seq
                    """,
                    params,
                ).fetchall()
            ]
        event_ids = [str(event_id) for event_id in event_ids_or_command_pairs]
        placeholders = ",".join("?" for _ in event_ids)
        return [
            (str(event_id), int(seq))
            for event_id, seq in self.store.connection.execute(
                f"""
                SELECT event_id, seq FROM journal
                WHERE event_id IN ({placeholders})
                ORDER BY seq
                """,
                event_ids,
            ).fetchall()
        ]

    def _effect_rows_for_events(
        self, event_ids: list[str]
    ) -> list[tuple[str, int]]:
        if not event_ids:
            return []
        placeholders = ",".join("?" for _ in event_ids)
        return [
            (str(effect_id), int(amount))
            for effect_id, amount in self.store.connection.execute(
                f"""
                SELECT effect_id, amount FROM effects
                WHERE source_event_id IN ({placeholders})
                ORDER BY committed_tick, effect_id
                """,
                event_ids,
            ).fetchall()
        ]

    def _validate_durable_outcome(
        self,
        expected_event_count: int,
        expected_effect_count: int,
        event_ids_or_command_pairs: list[str | tuple[str, str]],
    ) -> dict[str, Any]:
        rows = self._journal_rows_for_scope(event_ids_or_command_pairs)
        event_ids = [event_id for event_id, _ in rows]
        effects = self._effect_rows_for_events(event_ids)
        effect_count = len(effects)
        net_effect_count = sum(amount for _, amount in effects)
        cursor = int(
            self.store.connection.execute(
                "SELECT committed_seq FROM cursor WHERE stream = 'settlement'"
            ).fetchone()[0]
        )
        max_delivered_seq = max((seq for _, seq in rows), default=0)
        amounts_ok = all(amount == EFFECT_AMOUNT for _, amount in effects)
        outcome = (
            "pass"
            if len(rows) == expected_event_count
            and effect_count == expected_effect_count
            and amounts_ok
            and net_effect_count == expected_effect_count * EFFECT_AMOUNT
            and cursor >= max_delivered_seq
            else "fail"
        )
        return {
            "event_count": len(rows),
            "effect_count": effect_count,
            "net_effect_count": net_effect_count,
            "outcome": outcome,
        }

    def _effect_count_for_event_keys(
        self, event_ids: list[str], logical_effect_keys: list[str] | None
    ) -> int:
        if not event_ids:
            return 0
        placeholders = ",".join("?" for _ in event_ids)
        params: list[Any] = list(event_ids)
        key_clause = ""
        if logical_effect_keys is not None:
            key_placeholders = ",".join("?" for _ in logical_effect_keys)
            key_clause = f" AND logical_effect_key IN ({key_placeholders})"
            params.extend(logical_effect_keys)
        return int(
            self.store.connection.execute(
                f"""
                SELECT COUNT(*) FROM effects
                WHERE source_event_id IN ({placeholders}){key_clause}
                """,
                params,
            ).fetchone()[0]
        )

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
            "active_config_root": self._active_config_root,
        }

    def _issue_capability(self, runtime: RuntimeStore, run_id: int) -> str:
        """Replace the runtime placeholder handle with an authenticated capability."""
        token = self._trace_authority.issue(
            session_id=self._session_id,
            epoch=self._trace_epoch,
            run_id=run_id,
            workload_id=runtime.workload_id,
            alias=runtime.alias,
            tick=runtime.start_tick,
            selectors=runtime.trace_selectors,
            views=sorted(VIEWS),
        )
        self.store.connection.execute(
            "UPDATE trace_spans SET correlation_handle = ? WHERE correlation_handle = ?",
            (token, runtime.handle),
        )
        self.store.connection.commit()
        return token

    def run(
        self, workload_id: str, cutpoint: str | None = None, run_id: int = 0
    ) -> dict[str, Any]:
        """Execute a public workload, diagnostic cutpoint, or hidden workload run."""
        try:
            config = self._read_config()
            attempt_budget = self._attempt_budget(config)
        except (ValueError, TypeError, KeyError) as exc:
            raise ToolError("active workspace configuration invalid") from exc
        service_runtime = self._load_service_runtime()
        is_hidden = workload_id.startswith("H-")
        if workload_id in ("P1", "P2", "P3"):
            if cutpoint is not None:
                raise ToolError("public workloads do not accept cutpoints")
            alias = workload_id
            handle = self._new_handle(workload_id, cutpoint, alias, run_id)
        elif is_hidden:
            alias = workload_id
            handle = self._new_handle(workload_id, cutpoint, alias, run_id)
        elif cutpoint in ("s5.exit", "s2.exit"):
            alias = workload_id
            handle = self._new_handle(workload_id, cutpoint, alias, run_id)
        else:
            raise ToolError(f"unknown workload or missing cutpoint: {workload_id}")
        transient = workload_id in ("P1", "P2", "H-TRANS")
        runtime = RuntimeStore(
            self.store, self.profile, cutpoint, workload_id, alias, handle, transient
        )
        runtime._control(
            f"workload {workload_id} cutpoint {cutpoint} handle {handle} alias {alias}"
        )
        if workload_id in ("P1", "P2", "P3"):
            receipt = self._run_public_workload(runtime, service_runtime, attempt_budget)
        elif is_hidden:
            receipt = self._run_hidden_workload(runtime, service_runtime, attempt_budget)
        else:
            receipt = self._run_cutpoint_diagnostic(runtime, service_runtime, attempt_budget)
        receipt["handle"] = self._issue_capability(runtime, run_id)
        return receipt
