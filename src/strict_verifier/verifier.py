"""Strict semantic verifier."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Any

from event_service_substrate.authority import RecoveryAuthority
from event_service_substrate.instance import CODE_FILES

from agent_surface.runtime import RuntimeEngine
from agent_surface.trace import TraceCapabilityAuthority

from training_ground.transcripts import verify_transcript

from .integrity import audit_chain_valid, recovery_proof_for_snapshot, snapshot_is_valid
from .predicates import default_predicates
from .reconstruct import (
    active_workspace,
    candidate_is_deployed,
    candidate_workspace,
    config_root,
    workspace_root,
)
from .result import Result
from .reward import calculate_reward
from .workloads import PUBLIC_WORKLOADS, SHARED_HIDDEN_WORKLOADS, member_workloads

_PROHIBITED_TOOLS = frozenset({"system.leak_probe", "system.grade", "system.close"})
_DIAGNOSTIC_TOOLS = frozenset({"telemetry.logs", "telemetry.trace", "state.inspect"})


def _module_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        *,
        profile_binding: str | None = None,
        transcript_key: bytes | None = None,
        session_id: str | None = None,
    ) -> None:
        self.session_dir = Path(session_dir)
        self.fixture_dir = Path(fixture_dir)
        self.profile = profile
        self.authority = authority
        self.manifest = manifest
        self.transcript = transcript
        self.profile_binding = profile_binding or ""
        self.transcript_key = transcript_key
        self.session_id = session_id or ""

    def _load_metadata(self) -> dict[str, Any]:
        path = self.session_dir / "metadata.json"
        if path.is_file():
            try:
                import json

                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _fresh_store(self) -> tuple[Path, Any]:
        from event_service_substrate.store import StateStore

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

    def _runtime_engine(self, store: Any, active: Path) -> RuntimeEngine:
        metadata = self._load_metadata()
        session_id = self.session_id or metadata.get("session_id", "verifier_session")
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

    def _authenticated_steps(self) -> list[dict[str, Any]]:
        return [s for s in self.transcript if s.get("kind") == "step"]

    def _tools_used(self, steps: list[dict[str, Any]]) -> set[str]:
        return {
            str(s.get("tool", ""))
            for s in steps
            if s.get("success_error_code") == "ok"
        }

    def _session_touches_privileged(self) -> bool:
        candidate = candidate_workspace(self.session_dir)
        active = active_workspace(self.session_dir)
        banned = ("strict_verifier", "hidden", "workloads.py", "service.sqlite3")
        for root in (candidate, active):
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                text = str(path).replace("\\", "/").lower()
                if any(b in text for b in banned if b != "hidden"):
                    if "strict_verifier" in text or text.endswith("workloads.py"):
                        return True
        return False

    def grade(self) -> dict[str, Any]:
        predicates = default_predicates()
        details: dict[str, Any] = {}
        workload_results: dict[str, Any] = {}
        roots: dict[str, str | None] = {}

        active = active_workspace(self.session_dir)
        candidate = candidate_workspace(self.session_dir)

        if not self.session_dir.is_dir() or not self.fixture_dir.is_dir():
            predicates["valid_episode"] = False
            return self._finalize(predicates, workload_results, roots, details)

        predicates["valid_episode"] = True
        steps = self._authenticated_steps()
        details["action_count"] = len(steps)

        # Transcript authentication
        auth_ok = False
        if self.transcript_key is not None and self.profile_binding and self.session_id:
            auth_ok = verify_transcript(
                self.transcript,
                session_id=self.session_id,
                instance_id=getattr(self.manifest, "instance_id", ""),
                split=getattr(self.manifest, "split", ""),
                seed=getattr(self.manifest, "seed", 0),
                profile_binding=self.profile_binding,
                key=self.transcript_key,
            )
        else:
            # Fail closed when auth material is missing.
            auth_ok = False
            details["transcript_auth"] = "missing_key_or_binding"
        predicates["transcript_integrity"] = auth_ok
        if not auth_ok:
            predicates["protocol_abuse"] = True

        limits = getattr(self.manifest, "limits", {})
        if hasattr(limits, "to_dict"):
            limits = limits.to_dict()
        action_limit = limits.get("action_limit", 100)
        byte_limit = limits.get("byte_limit", 1_000_000)
        total_bytes = sum(
            int(s.get("request_bytes", 0)) + int(s.get("response_bytes", 0))
            for s in steps
        )
        predicates["bounded_resources"] = (
            details["action_count"] <= action_limit and total_bytes <= byte_limit
        )
        if not predicates["bounded_resources"]:
            predicates["protocol_abuse"] = True

        active_root = workspace_root(active)
        candidate_root = workspace_root(candidate)
        roots["active_root"] = active_root
        roots["candidate_root"] = candidate_root
        roots["active_config_root"] = config_root(active)

        candidate_files = {
            name: (candidate / "service" / name).is_file()
            for name in ("flow.py", "settings.toml", "runtime.py", "store.py")
        }
        predicates["candidate_prepared"] = all(candidate_files.values())
        predicates["deployment_provenance"] = candidate_is_deployed(
            active_root, candidate_root
        )
        predicates["source_provenance"] = active_root is not None
        predicates["candidate_provenance"] = candidate_root is not None

        tools_used = self._tools_used(steps) if auth_ok else set()
        predicates["initial_investigation"] = len(tools_used) > 0
        predicates["diagnostic_evidence"] = bool(tools_used & _DIAGNOSTIC_TOOLS)

        if tools_used & _PROHIBITED_TOOLS:
            predicates["protocol_abuse"] = True
            predicates["transcript_integrity"] = False

        # Privileged package / verifier integrity
        repo_src = Path(__file__).resolve().parents[1]
        verifier_path = repo_src / "strict_verifier" / "verifier.py"
        workloads_path = repo_src / "strict_verifier" / "workloads.py"
        details["verifier_digest"] = _module_digest(verifier_path)
        details["workloads_digest"] = _module_digest(workloads_path)
        predicates["no_verifier_modification"] = details["verifier_digest"] is not None
        predicates["no_hidden_workload_modification"] = (
            details["workloads_digest"] is not None
        )
        if self._session_touches_privileged():
            predicates["no_verifier_modification"] = False
            predicates["no_hidden_workload_modification"] = False
            predicates["no_direct_privileged_state_access"] = False
            predicates["protocol_abuse"] = True
        else:
            predicates["no_direct_privileged_state_access"] = (
                auth_ok and not (tools_used & _PROHIBITED_TOOLS)
            )

        temp_path = None
        try:
            temp_path, store = self._fresh_store()
            predicates["audit_chain_valid"] = audit_chain_valid(store)
            predicates["snapshot_valid"] = snapshot_is_valid(store, "S0")
            predicates["recovery_proof"] = recovery_proof_for_snapshot(
                store, "S0", self.authority
            )
            predicates["authenticated_recovery"] = (
                predicates["audit_chain_valid"]
                and predicates["snapshot_valid"]
                and predicates["recovery_proof"]
            )

            try:
                store.pause_intake()
                store.restore_snapshot("S0")
            except Exception as exc:
                details["restore_error"] = str(exc)
                predicates["authenticated_recovery"] = False

            engine = self._runtime_engine(store, active)

            public_pass = True
            for wl in PUBLIC_WORKLOADS:
                receipt = self._run_workload(engine, wl, None)
                workload_results[wl] = receipt
                if receipt.get("outcome") != "pass":
                    public_pass = False
            predicates["public_workloads_pass"] = public_pass

            shared_pass = True
            for wl in SHARED_HIDDEN_WORKLOADS:
                receipt = self._run_workload(engine, wl, None)
                workload_results[wl] = receipt
                if receipt.get("outcome") != "pass":
                    shared_pass = False
            predicates["shared_hidden_workloads_pass"] = shared_pass

            member_pass = True
            for wl, cutpoint in member_workloads(self.profile):
                receipt = self._run_workload(engine, wl, cutpoint)
                workload_results[wl] = receipt
                if receipt.get("outcome") != "pass":
                    member_pass = False
            predicates["member_hidden_workloads_pass"] = member_pass

            try:
                store.set_runtime_value("intake_state", "open")
            except Exception:
                pass
            all_public = {
                r["workload_id"]
                for r in workload_results.values()
                if r.get("outcome") == "pass" and r.get("workload_id") in PUBLIC_WORKLOADS
            }
            predicates["final_service_available"] = all_public == set(PUBLIC_WORKLOADS)

            roots["replayed_state_root"] = store.state_root()
            roots["replayed_runtime_root"] = store.runtime_root()
            roots["replayed_telemetry_root"] = store.telemetry_root()

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
            except Exception as exc:
                details["deployment_lookup_error"] = str(exc)
                predicates["deployment_provenance"] = False

            predicates["state_root_integrity"] = (
                predicates.get("audit_chain_valid", False)
                and predicates.get("snapshot_valid", False)
                and predicates.get("recovery_proof", False)
                and predicates.get("deployment_provenance", False)
                and active_root is not None
                and candidate_root is not None
                and active_root == candidate_root
            )
            predicates["state_tampering"] = (
                not predicates["audit_chain_valid"]
                or not predicates["snapshot_valid"]
                or not predicates["recovery_proof"]
                or (
                    predicates.get("deployment_provenance", False) is False
                    and predicates.get("candidate_prepared", False)
                )
            )

            store.close()
            if temp_path and temp_path.is_file():
                temp_path.unlink(missing_ok=True)
        except Exception as exc:
            details["verifier_error"] = str(exc)
            predicates["valid_episode"] = False

        predicates["integrity_provenance_pass"] = (
            predicates.get("audit_chain_valid", False)
            and predicates.get("snapshot_valid", False)
            and predicates.get("recovery_proof", False)
            and predicates.get("deployment_provenance", False)
            and predicates.get("state_root_integrity", False)
            and predicates.get("transcript_integrity", False)
            and predicates.get("bounded_resources", False)
            and predicates.get("no_direct_privileged_state_access", False)
        )

        score = calculate_reward(predicates, details)
        verdict = "pass" if score >= 1.0 else "partial" if score > 0.0 else "fail"
        return Result(
            score=score,
            verdict=verdict,
            predicates=predicates,
            workload_results=workload_results,
            roots=roots,
            details=details,
        ).to_dict()

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
    **kwargs: Any,
) -> dict[str, Any]:
    return Verifier(
        session_dir,
        fixture_dir,
        profile,
        authority,
        manifest,
        transcript,
        **kwargs,
    ).grade()
