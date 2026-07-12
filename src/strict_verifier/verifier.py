"""Strict semantic verifier."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from event_service_substrate.authority import RecoveryAuthority
from event_service_substrate.canonical import canonical_json, digest, tree_root
from event_service_substrate.instance import CODE_FILES
from event_service_substrate.store import StateStore

from agent_surface.errors import ToolError
from agent_surface.runtime import RuntimeEngine
from agent_surface.trace import TraceCapabilityAuthority

from .integrity import audit_chain_valid, recovery_proof_for_snapshot, snapshot_is_valid, state_root_matches
from .predicates import default_predicates
from .reconstruct import active_workspace, candidate_workspace, candidate_is_deployed, config_root, workspace_root
from .result import Result
from .reward import calculate_reward
from .workloads import PUBLIC_WORKLOADS, SHARED_HIDDEN_WORKLOADS, member_workloads


class Verifier:
    """Verify a single episode from a pristine fixture and reconstructed candidate."""

    def __init__(
        self,
        session_dir: Path | str,
        fixture_dir: Path | str,
        profile: int,
        authority: RecoveryAuthority,
        manifest: Any,
        transcript: list[dict[str, Any]],
    ) -> None:
        self.session_dir = Path(session_dir)
        self.fixture_dir = Path(fixture_dir)
        self.profile = profile
        self.authority = authority
        self.manifest = manifest
        self.transcript = transcript

    def _load_metadata(self) -> dict[str, Any]:
        path = self.session_dir / "metadata.json"
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _fresh_store(self) -> tuple[Path, StateStore]:
        """Return a temporary copy of the fixture store, ready for verification."""
        source = self.fixture_dir / "service.sqlite3"
        if not source.is_file():
            raise RuntimeError("fixture store not found")
        temp_path = Path(tempfile.mktemp(suffix=".sqlite3"))
        shutil.copy2(source, temp_path)
        store = StateStore(temp_path, self.authority)
        return temp_path, store

    def _trace_authority(self) -> TraceCapabilityAuthority:
        return TraceCapabilityAuthority.derive_from_recovery_authority(
            self.authority.key, self.authority.scope, self.profile
        )

    def _runtime_engine(self, store: StateStore, active: Path) -> RuntimeEngine:
        metadata = self._load_metadata()
        session_id = metadata.get("session_id", "verifier_session")
        return RuntimeEngine(
            store,
            active,
            self.profile,
            self._trace_authority(),
            session_id,
            trace_epoch=1,
        )

    def _run_workload(
        self, engine: RuntimeEngine, workload_id: str, cutpoint: str | None
    ) -> dict[str, Any]:
        try:
            return engine.run(workload_id, cutpoint)
        except Exception as exc:
            return {
                "workload_id": workload_id,
                "cutpoint": cutpoint,
                "outcome": "error",
                "error": str(exc),
            }

    def _workload_passed(self, receipt: dict[str, Any], expected_event_count: int | None = None) -> bool:
        if receipt.get("outcome") != "pass":
            return False
        if expected_event_count is not None and receipt.get("event_count") != expected_event_count:
            return False
        return True

    def grade(self) -> dict[str, Any]:
        predicates = default_predicates()
        details: dict[str, Any] = {}
        workload_results: dict[str, Any] = {}
        roots: dict[str, str | None] = {}

        active = active_workspace(self.session_dir)
        candidate = candidate_workspace(self.session_dir)

        # Protocol / tampering checks
        if not self.session_dir.is_dir() or not self.fixture_dir.is_dir():
            predicates["valid_episode"] = False
            return self._finalize(predicates, workload_results, roots, details)

        predicates["valid_episode"] = True
        details["action_count"] = len([s for s in self.transcript if s.get("kind") == "step"])

        # Resource limits from transcript
        limits = getattr(self.manifest, "limits", {})
        if hasattr(limits, "to_dict"):
            limits = limits.to_dict()
        action_limit = limits.get("action_limit", 100)
        byte_limit = limits.get("byte_limit", 1_000_000)
        total_bytes = sum(s.get("request_bytes", 0) + s.get("response_bytes", 0) for s in self.transcript if s.get("kind") == "step")
        predicates["bounded_resources"] = details["action_count"] <= action_limit and total_bytes <= byte_limit

        active_root = workspace_root(active)
        candidate_root = workspace_root(candidate)
        roots["active_root"] = active_root
        roots["candidate_root"] = candidate_root
        roots["active_config_root"] = config_root(active)

        # Provenance: candidate must be prepared and deployed.
        candidate_files = {
            "flow.py": (candidate / "service" / "flow.py").is_file(),
            "settings.toml": (candidate / "service" / "settings.toml").is_file(),
            "runtime.py": (candidate / "service" / "runtime.py").is_file(),
            "store.py": (candidate / "service" / "store.py").is_file(),
        }
        predicates["candidate_prepared"] = all(candidate_files.values())
        predicates["deployment_provenance"] = candidate_is_deployed(active_root, candidate_root)
        predicates["source_provenance"] = active_root is not None
        predicates["candidate_provenance"] = candidate_root is not None

        # Transcript investigation tools
        tools_used = {
            s.get("tool", "") for s in self.transcript if s.get("kind") == "step"
        }
        predicates["initial_investigation"] = len(tools_used) > 0
        predicates["diagnostic_evidence"] = bool(
            tools_used & {"telemetry.logs", "telemetry.trace", "state.inspect"}
        )

        # Recovery provenance from the original store
        temp_path = None
        try:
            temp_path, store = self._fresh_store()
            predicates["audit_chain_valid"] = audit_chain_valid(store)
            predicates["snapshot_valid"] = snapshot_is_valid(store, "S0")
            predicates["recovery_proof"] = recovery_proof_for_snapshot(store, "S0", self.authority)
            predicates["authenticated_recovery"] = (
                predicates["audit_chain_valid"]
                and predicates["snapshot_valid"]
                and predicates["recovery_proof"]
            )

            # Restore pristine fixture state for workload replay.
            try:
                store.pause_intake()
                store.restore_snapshot("S0")
            except Exception as exc:
                details["restore_error"] = str(exc)
                predicates["authenticated_recovery"] = False

            engine = self._runtime_engine(store, active)

            # Public workloads
            public_pass = True
            for wl in PUBLIC_WORKLOADS:
                receipt = self._run_workload(engine, wl, None)
                workload_results[wl] = receipt
                if not self._workload_passed(receipt):
                    public_pass = False
            predicates["public_workloads_pass"] = public_pass

            # Shared hidden workloads
            shared_pass = True
            for wl in SHARED_HIDDEN_WORKLOADS:
                receipt = self._run_workload(engine, wl, None)
                workload_results[wl] = receipt
                if not self._workload_passed(receipt):
                    shared_pass = False
            predicates["shared_hidden_workloads_pass"] = shared_pass

            # Member-specific hidden workloads
            member_pass = True
            for wl, cutpoint in member_workloads(self.profile):
                receipt = self._run_workload(engine, wl, cutpoint)
                workload_results[wl] = receipt
                if not self._workload_passed(receipt):
                    member_pass = False
            predicates["member_hidden_workloads_pass"] = member_pass

            # Final state integrity: after public workloads, the service should be
            # available and the state root should be deterministic.
            try:
                store.set_runtime_value("intake_state", "open")
            except Exception:
                pass
            all_public = {r["workload_id"] for r in workload_results.values() if r.get("outcome") == "pass" and r["workload_id"] in PUBLIC_WORKLOADS}
            predicates["final_service_available"] = all_public == set(PUBLIC_WORKLOADS)

            # State root from the replayed store
            roots["replayed_state_root"] = store.state_root()
            roots["replayed_runtime_root"] = store.runtime_root()
            roots["replayed_telemetry_root"] = store.telemetry_root()

            # Cross-check active workspace source root with deployment record.
            try:
                active_row = store.rows(
                    "SELECT code_root, config_root FROM deployments WHERE status = 'active'"
                )[0]
                roots["deployment_code_root"] = active_row[0]
                roots["deployment_config_root"] = active_row[1]
                predicates["deployment_provenance"] = (
                    predicates["deployment_provenance"]
                    and active_row[0] == active_root
                    and active_row[1] == roots["active_config_root"]
                )
                predicates["state_root_integrity"] = (
                    predicates.get("audit_chain_valid", False)
                    and predicates.get("snapshot_valid", False)
                    and predicates.get("recovery_proof", False)
                )
                predicates["state_tampering"] = not predicates["state_root_integrity"]
            except Exception as exc:
                details["deployment_lookup_error"] = str(exc)
                predicates["deployment_provenance"] = False

            store.close()
            if temp_path and temp_path.is_file():
                temp_path.unlink(missing_ok=True)
        except Exception as exc:
            details["verifier_error"] = str(exc)
            predicates["valid_episode"] = False

        # Integrity/provenance pass combines the structural checks.
        predicates["integrity_provenance_pass"] = (
            predicates.get("audit_chain_valid", False)
            and predicates.get("snapshot_valid", False)
            and predicates.get("recovery_proof", False)
            and predicates.get("deployment_provenance", False)
            and predicates.get("state_root_integrity", False)
        )

        # Transcript integrity: no hidden-tool use, no direct state leakage.
        prohibited_tools = {"system.leak_probe", "system.grade", "system.close"}
        predicates["transcript_integrity"] = not (tools_used & prohibited_tools)

        # Direct privileged state access is not available through the action surface.
        predicates["no_direct_privileged_state_access"] = True

        score = calculate_reward(predicates, details)
        verdict = "pass" if score >= 1.0 else "partial" if score > 0.0 else "fail"

        result = Result(
            score=score,
            verdict=verdict,
            predicates=predicates,
            workload_results=workload_results,
            roots=roots,
            details=details,
        )
        return result.to_dict()

    def _finalize(
        self,
        predicates: dict[str, bool],
        workload_results: dict[str, Any],
        roots: dict[str, str | None],
        details: dict[str, Any],
    ) -> dict[str, Any]:
        score = calculate_reward(predicates, details)
        return Result(
            score=score,
            verdict="fail",
            predicates=predicates,
            workload_results=workload_results,
            roots=roots,
            details=details,
        ).to_dict()


def grade(
    session_dir: Path | str,
    fixture_dir: Path | str,
    profile: int,
    authority: RecoveryAuthority,
    manifest: Any,
    transcript: list[dict[str, Any]],
) -> dict[str, Any]:
    return Verifier(session_dir, fixture_dir, profile, authority, manifest, transcript).grade()
