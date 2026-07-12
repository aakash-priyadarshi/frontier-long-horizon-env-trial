"""Core Gymnasium-compatible training and evaluation environment."""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Any, Type

from agent_surface.gateway import ToolClient, ToolGateway
from agent_surface.errors import ToolError

from .actions import action_bytes, dispatch_action, result_bytes, validate_action
from .authority import authority_for_profile
from .limits import Limits
from .manifests import Manifest
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
        self._transcript = Transcript(
            version=ENVIRONMENT_VERSION,
            instance_id=manifest.instance_id,
            split=manifest.split,
            seed=manifest.seed,
        )
        self._action_count = 0
        self._total_bytes = 0
        self._sequence = 0
        self._last_status: dict[str, Any] | None = None
        self._closed = False
        self._graded = False
        self._grade_result: dict[str, Any] | None = None

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
        if self._work_dir is None:
            import tempfile

            self._work_dir = Path(tempfile.mkdtemp(prefix="training-ground-"))
        self._work_dir.mkdir(parents=True, exist_ok=True)
        authority = authority_for_profile(self.manifest.profile)
        session_dir = self._work_dir / "session"
        fixture_dir = self._work_dir / "fixture"
        self._gateway = ToolGateway(
            self.manifest.profile,
            session_dir,
            fixture_dir,
            authority,
        )
        self._client = self._gateway.__enter__()
        self._closed = False
        self._action_count = 0
        self._total_bytes = 0
        self._sequence = 0
        self._graded = False
        self._grade_result = None
        obs = self._status_observation()
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
        self._action_count += 1
        self._sequence += 1
        req_bytes = action_bytes(action)
        success_code = "ok"
        try:
            tool, arguments = validate_action(action)
            raw_result = dispatch_action(self._client, tool, arguments)
        except EnvironmentError as exc:
            raw_result = {"error": {"code": exc.code, "message": str(exc)}}
            success_code = exc.code
            tool = action.get("tool", "unknown") if isinstance(action, dict) else "unknown"
            arguments = action.get("arguments") if isinstance(action, dict) else {}
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
            "response": raw_result,
            "action_count": self._action_count,
            "total_bytes": self._total_bytes,
        }

        if terminated and not self._graded:
            self._grade_result = self.grade()
            self._graded = True
            reward = float(self._grade_result.get("score", 0.0))
            info["grade"] = self._grade_result

        self._transcript.add_step(
            sequence=self._sequence,
            tick=status.get("tick", 0),
            tool=tool,
            arguments_digest=canonical_arguments_digest(arguments),
            success_code=success_code,
            result_digest=bounded_result_digest(raw_result),
            reward_delta=reward,
            terminated=terminated,
            truncated=truncated,
            cumulative_action_count=self._action_count,
            request_bytes=req_bytes,
            response_bytes=resp_bytes,
        )

        return status, reward, terminated, truncated, info

    def grade(self) -> dict[str, Any]:
        if self._client is None or self._closed or self._client.session_dir is None:
            raise EnvironmentError("environment is not reset")
        if self._grade_result is not None:
            return self._grade_result
        from strict_verifier import Verifier

        authority = authority_for_profile(self.manifest.profile)
        verifier = Verifier(
            session_dir=self._client.session_dir,
            fixture_dir=self._client.fixture_dir,
            profile=self.manifest.profile,
            authority=authority,
            manifest=self.manifest,
            transcript=self._transcript.to_list(),
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
