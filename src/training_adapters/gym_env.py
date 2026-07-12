"""Gymnasium-compatible environment over the twelve-tool gateway protocol."""

from __future__ import annotations

from typing import Any, SupportsFloat

from .protocol import ALLOWED_TOOLS
from .session import ProtocolGateway, ProtocolSession

try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError:  # pragma: no cover - optional dependency
    gym = None  # type: ignore[assignment]
    spaces = None  # type: ignore[assignment]


def _require_gym() -> None:
    if gym is None:
        raise ImportError(
            "gymnasium is required for IncidentGymEnv; install with "
            "pip install 'event-service-substrate[adapters]'"
        )


class IncidentGymEnv(gym.Env if gym is not None else object):  # type: ignore[misc]
    """Single-agent Gymnasium env with Dict actions ``{tool, arguments}``."""

    metadata = {"render_modes": []}

    def __init__(self, profile: int = 0, *, max_steps: int = 64) -> None:
        _require_gym()
        assert spaces is not None
        self.profile = profile
        self.max_steps = max_steps
        self._gateway: ProtocolGateway | None = None
        self._session: ProtocolSession | None = None
        self._steps = 0
        self._closed = True
        # Text spaces keep the action contract explicit without enumerating args.
        self.action_space = spaces.Dict(
            {
                "tool": spaces.Text(min_length=1, max_length=64),
                "arguments_json": spaces.Text(min_length=2, max_length=8_000),
            }
        )
        self.observation_space = spaces.Dict(
            {
                "status_json": spaces.Text(min_length=2, max_length=50_000),
                "last_ok": spaces.Discrete(2),
            }
        )

    def _encode_obs(self, status: dict[str, Any], last_ok: bool) -> dict[str, Any]:
        import json

        return {
            "status_json": json.dumps(status, sort_keys=True, ensure_ascii=True),
            "last_ok": 1 if last_ok else 0,
        }

    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        _require_gym()
        super().reset(seed=seed)
        self.close()
        self._gateway = ProtocolGateway(self.profile)
        self._session = self._gateway.__enter__()
        self._steps = 0
        self._closed = False
        obs = self._session.observation()
        return self._encode_obs(obs, True), {"allowed_tools": list(ALLOWED_TOOLS)}

    def step(
        self, action: dict[str, Any]
    ) -> tuple[dict[str, Any], SupportsFloat, bool, bool, dict[str, Any]]:
        import json

        if self._session is None or self._closed:
            raise RuntimeError("environment is not reset")
        tool = str(action.get("tool", ""))
        raw_args = action.get("arguments_json", "{}")
        try:
            arguments = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except json.JSONDecodeError:
            arguments = {}
            response_ok = False
            info = {"error": {"code": "invalid_arguments", "message": "arguments_json must be JSON object"}}
            obs = self._session.observation()
            self._steps += 1
            terminated = False
            truncated = self._steps >= self.max_steps
            return self._encode_obs(obs, False), -0.05, terminated, truncated, info

        response = self._session.call(tool, arguments if isinstance(arguments, dict) else {})
        self._steps += 1
        obs = self._session.observation()
        reward = 0.01 if response.ok else -0.05
        status = obs.get("status") if obs.get("ok") else {}
        terminated = bool(
            isinstance(status, dict)
            and status.get("incident") == "closed"
            and status.get("public_canary") == "pass"
        )
        if terminated:
            reward = 1.0
        truncated = (not terminated) and self._steps >= self.max_steps
        info = {"response": response.to_dict(), "steps": self._steps}
        return self._encode_obs(obs, response.ok), reward, terminated, truncated, info

    def close(self) -> None:
        if self._gateway is not None and not self._closed:
            self._gateway.__exit__(None, None, None)
        self._gateway = None
        self._session = None
        self._closed = True
