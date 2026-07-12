"""Core Gymnasium-compatible training and evaluation environment."""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path
from types import TracebackType
from typing import Any, Type

from agent_surface.errors import ToolError
from agent_surface.gateway import ToolClient, ToolGateway

from .actions import action_bytes, dispatch_action, result_bytes, validate_action
from .authority import (
    authority_for_profile,
    profile_binding,
    transcript_key_for_authority,
)
from .manifests import Manifest, build_manifest
from .observations import error_observation, is_terminated, sanitize_release_status
from .protocol import ENVIRONMENT_VERSION, EnvironmentError
from .transcripts import Transcript, bounded_result_digest, canonical_arguments_digest


class IncidentEnv:
    """Process-separated, pair-blind environment for incident repair."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        manifest: Manifest,
        *,
        work_dir: Path | str | None = None,
        max_steps: int | None = None,
    ) -> None:
        self.manifest = manifest
        self._work_dir = Path(work_dir) if work_dir is not None else None
        self._max_steps = max_steps
        self._gateway: ToolGateway | None = None
        self._client: ToolClient | None = None
        self._authority = authority_for_profile(manifest.profile)
        self._profile_binding = profile_binding(manifest.profile, self._authority)
        self._transcript = self._new_transcript(session_id="pending")
        self._action_count = 0
        self._total_bytes = 0
        self._sequence = 0
        self._last_status: dict[str, Any] | None = None
        self._closed = False
        self._ended = False
        self._graded = False
        self._grade_result: dict[str, Any] | None = None
        self._last_trace_handle: str | None = None

    def _new_transcript(self, session_id: str) -> Transcript:
        return Transcript(
            version=ENVIRONMENT_VERSION,
            instance_id=self.manifest.instance_id,
            split=self.manifest.split,
            seed=self.manifest.seed,
            session_id=session_id,
            profile_binding=self._profile_binding,
            hmac_key=transcript_key_for_authority(self._authority),
        )

    def _status_observation(self) -> dict[str, Any]:
        if self._client is None:
            raise EnvironmentError("environment is not reset")
        try:
            status = self._client.release_status()
        except ToolError as exc:
            return error_observation("release.status", f"{exc.code}: {exc}")
        self._last_status = status
        return sanitize_release_status(status)

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self.close()
        options = options or {}
        if seed is not None and seed != self.manifest.seed:
            self.manifest = build_manifest(self.manifest.split, seed)
        if options.get("profile") is not None:
            self.manifest = replace(self.manifest, profile=int(options["profile"]))
        self._authority = authority_for_profile(self.manifest.profile)
        self._profile_binding = profile_binding(self.manifest.profile, self._authority)

        if self._work_dir is None:
            import tempfile

            self._work_dir = Path(tempfile.mkdtemp(prefix="training-ground-"))
        self._work_dir.mkdir(parents=True, exist_ok=True)
        session_dir = self._work_dir / "session"
        fixture_dir = self._work_dir / "fixture"
        if session_dir.exists():
            shutil.rmtree(session_dir)
        if fixture_dir.exists():
            shutil.rmtree(fixture_dir)
        self._gateway = ToolGateway(
            self.manifest.profile,
            session_dir,
            fixture_dir,
            self._authority,
        )
        self._client = self._gateway.__enter__()
        self._closed = False
        self._ended = False
        self._action_count = 0
        self._total_bytes = 0
        self._sequence = 0
        self._graded = False
        self._grade_result = None
        obs = self._status_observation()
        session_id = str(obs.get("session_id") or "unknown-session")
        self._transcript = self._new_transcript(session_id=session_id)
        info = {
            "allowed_tools": list(self._client.tool_inventory()) if self._client else [],
            "manifest": self.manifest.public(),
            "instance_id": self.manifest.instance_id,
        }
        self._transcript.add_meta("manifest", self.manifest.public())
        return obs, info

    def step(
        self,
        action: dict[str, Any],
    ) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        if self._client is None or self._closed:
            raise EnvironmentError("environment is not reset")
        if self._ended:
            raise EnvironmentError(
                "episode has ended; call reset() before stepping",
                code="episode_ended",
            )
        self._action_count += 1
        self._sequence += 1
        req_bytes = action_bytes(action) if isinstance(action, dict) else 0
        success_code = "ok"
        try:
            tool, arguments = validate_action(action)
            if (
                tool == "telemetry.trace"
                and arguments.get("handle") == "__from_previous__"
            ):
                if not self._last_trace_handle:
                    raise EnvironmentError(
                        "no prior runtime handle available for telemetry.trace",
                        code="invalid_arguments",
                    )
                arguments = {**arguments, "handle": self._last_trace_handle}
            raw_result = dispatch_action(self._client, tool, arguments)
            if tool == "runtime.run" and isinstance(raw_result, dict):
                handle = raw_result.get("handle")
                if isinstance(handle, str) and handle:
                    self._last_trace_handle = handle
        except EnvironmentError as exc:
            raw_result = {"error": {"code": exc.code, "message": str(exc)}}
            success_code = exc.code
            tool = action.get("tool", "unknown") if isinstance(action, dict) else "unknown"
            arguments = action.get("arguments") if isinstance(action, dict) else {}
            if not isinstance(arguments, dict):
                arguments = {}
        resp_bytes = result_bytes(raw_result)
        self._total_bytes += req_bytes + resp_bytes

        status = self._status_observation()
        if isinstance(raw_result, dict) and "error" in raw_result:
            status["error"] = raw_result["error"]
            status["last_tool"] = tool
        terminated = is_terminated(status)
        truncated = False
        if not terminated:
            if self._max_steps is not None and self._action_count >= self._max_steps:
                truncated = True
            else:
                tick = status.get("tick", 0)
                truncated, reason = self.manifest.limits.check(
                    self._action_count, self._total_bytes, tick
                )
                if truncated:
                    status["truncated_reason"] = reason

        reward = 0.0
        info: dict[str, Any] = {
            "tool": tool,
            "response_digest": bounded_result_digest(raw_result),
            "action_count": self._action_count,
            "total_bytes": self._total_bytes,
        }

        self._transcript.add_step(
            sequence=self._sequence,
            tick=status.get("tick", 0),
            tool=tool,
            arguments_digest=canonical_arguments_digest(arguments),
            success_code=success_code,
            result_digest=bounded_result_digest(raw_result),
            reward_delta=0.0,
            terminated=terminated,
            truncated=truncated,
            cumulative_action_count=self._action_count,
            request_bytes=req_bytes,
            response_bytes=resp_bytes,
        )

        if terminated and not self._graded:
            self._grade_result = self.grade()
            self._graded = True
            reward = float(self._grade_result.get("score", 0.0))
            info["grade"] = self._grade_result

        if terminated or truncated:
            self._ended = True

        return status, reward, terminated, truncated, info

    def grade(self) -> dict[str, Any]:
        if self._client is None or self._closed or self._client.session_dir is None:
            raise EnvironmentError("environment is not reset")
        if self._grade_result is not None:
            return self._grade_result
        from strict_verifier import Verifier

        verifier = Verifier(
            session_dir=self._client.session_dir,
            fixture_dir=self._client.fixture_dir,
            profile=self.manifest.profile,
            authority=self._authority,
            manifest=self.manifest,
            transcript=self._transcript.to_list(),
            profile_binding=self._profile_binding,
            transcript_key=transcript_key_for_authority(self._authority),
            session_id=self._transcript.session_id,
        )
        self._grade_result = verifier.grade()
        return self._grade_result

    def transcript(self) -> list[dict[str, Any]]:
        return self._transcript.to_list()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._gateway is not None:
            try:
                self._gateway.__exit__(None, None, None)
            except Exception:
                pass
            self._gateway = None
        self._client = None

    def __enter__(self) -> "IncidentEnv":
        return self

    def __exit__(
        self,
        exc_type: Type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
