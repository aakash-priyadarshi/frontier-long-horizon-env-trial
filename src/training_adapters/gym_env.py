"""Gymnasium-compatible environment wrapper over the training_ground core."""

from __future__ import annotations

import json
from typing import Any, SupportsFloat

from training_ground.loader import load_environment
from training_ground.protocol import EnvironmentError

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
    """Single-agent Gymnasium env with Dict actions ``{tool, arguments_json}``."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        profile: int = 0,
        *,
        split: str = "train",
        seed: int = 0,
        max_steps: int = 64,
        work_dir: str | None = None,
    ) -> None:
        _require_gym()
        assert spaces is not None
        self.profile = profile
        self.split = split
        self.seed = seed
        self.max_steps = max_steps
        self.work_dir = work_dir
        self._core = load_environment(
            split=split,
            seed=seed,
            options={"profile": profile, "max_steps": max_steps},
            work_dir=work_dir,
        )
        self._closed = True
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

    def _encode_obs(self, status: dict[str, Any]) -> dict[str, Any]:
        last_ok = 0 if "error" in status else 1
        return {
            "status_json": json.dumps(status, sort_keys=True, ensure_ascii=True),
            "last_ok": last_ok,
        }

    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        _require_gym()
        super().reset(seed=seed)
        self.close()
        seed = seed if seed is not None else self.seed
        obs, info = self._core.reset(seed=seed, options=options)
        self._closed = False
        info["allowed_tools"] = info.get("allowed_tools", [])
        return self._encode_obs(obs), info

    def step(
        self, action: dict[str, Any]
    ) -> tuple[dict[str, Any], SupportsFloat, bool, bool, dict[str, Any]]:
        if self._closed:
            raise RuntimeError("environment is not reset")
        tool = str(action.get("tool", ""))
        raw_args = action.get("arguments_json", "{}")
        try:
            arguments = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            if not isinstance(arguments, dict):
                raise ValueError("arguments_json must be a JSON object")
            core_action = {"tool": tool, "arguments": arguments}
            obs, reward, terminated, truncated, info = self._core.step(core_action)
            return self._encode_obs(obs), float(reward), terminated, truncated, info
        except (json.JSONDecodeError, ValueError) as exc:
            obs = self._core._last_status or {
                "error": str(exc),
                "incident": "open",
                "public_canary": "green_once",
            }
            return self._encode_obs(obs), 0.0, False, False, {"error": str(exc)}

    def close(self) -> None:
        if not self._closed:
            self._core.close()
        self._closed = True

    def __enter__(self) -> "IncidentGymEnv":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
