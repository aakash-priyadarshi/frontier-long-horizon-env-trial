"""Gymnasium-compatible environment wrapper over the training_ground core."""

from __future__ import annotations

import json
from typing import Any, SupportsFloat

from training_ground.loader import load_environment

try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError:  # pragma: no cover
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
        # Use Sequence spaces that accept arbitrary UTF-8 JSON strings.
        # Text spaces in some Gymnasium versions reject long/unicode content.
        self.action_space = spaces.Dict(
            {
                "tool": spaces.Text(min_length=1, max_length=64),
                "arguments_json": spaces.Sequence(spaces.Discrete(256)),
            }
        )
        self.observation_space = spaces.Dict(
            {
                "status_json": spaces.Sequence(spaces.Discrete(256)),
                "last_ok": spaces.Discrete(2),
            }
        )

    @staticmethod
    def _encode_text(value: str) -> tuple[int, ...]:
        # Gymnasium Sequence.contains requires a tuple of ints, not a list.
        return tuple(value.encode("utf-8"))

    @staticmethod
    def _decode_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, (bytes, bytearray)):
            return bytes(value).decode("utf-8")
        return bytes(int(x) for x in value).decode("utf-8")

    def _encode_obs(self, status: dict[str, Any]) -> dict[str, Any]:
        last_ok = 0 if "error" in status else 1
        payload = json.dumps(status, sort_keys=True, ensure_ascii=True)
        return {
            "status_json": self._encode_text(payload),
            "last_ok": last_ok,
        }

    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        _require_gym()
        super().reset(seed=seed)
        self.close()
        options = dict(options or {})
        options.setdefault("profile", self.profile)
        options.setdefault("max_steps", self.max_steps)
        seed = seed if seed is not None else self.seed
        # Rebuild core when seed changes so reset(seed=) reshuffles the episode.
        if seed != self._core.manifest.seed or options.get("profile") != self._core.manifest.profile:
            self._core = load_environment(
                split=self.split,
                seed=seed,
                options=options,
                work_dir=self.work_dir,
            )
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
        raw_args = action.get("arguments_json", self._encode_text("{}"))
        try:
            args_text = self._decode_text(raw_args)
            arguments = json.loads(args_text)
            if not isinstance(arguments, dict):
                raise ValueError("arguments_json must be a JSON object")
            core_action = {"tool": tool, "arguments": arguments}
            obs, reward, terminated, truncated, info = self._core.step(core_action)
            return self._encode_obs(obs), float(reward), terminated, truncated, info
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
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
