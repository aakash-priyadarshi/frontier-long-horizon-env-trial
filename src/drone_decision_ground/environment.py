"""Gymnasium-style public Talon decision-support boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .actions import ACTION_SCHEMA_VERSION, DecisionAction, DecisionRecommendation, parse_recommendation
from .approval_protocol import ApprovalVerifier
from .fake_clock import FakeClock
from .observation import PublicObservation
from .policy_gate import GateDecision, PolicyGate
from .scenarios import ScenarioConfig


ENVIRONMENT_VERSION = "talon.environment/2.0"


class TalonEnvironmentError(RuntimeError):
    def __init__(self, message: str, *, code: str = "environment_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ControllerFrame:
    """Privileged controller output; only its public observation crosses the boundary."""

    observation: PublicObservation
    terminal: bool = False


class ScenarioController(Protocol):
    approval_verifier: ApprovalVerifier

    def reset(self, clock: FakeClock) -> ControllerFrame: ...

    def advance(self, action: DecisionAction, clock: FakeClock) -> ControllerFrame: ...

    def verifier_context(self) -> dict[str, Any]: ...


ControllerFactory = Callable[[ScenarioConfig, int], ScenarioController]


@dataclass(frozen=True)
class _PrivilegedStep:
    sequence: int
    observation: PublicObservation
    recommendation: DecisionRecommendation
    gate: GateDecision
    safety_cost: int
    terminated: bool
    truncated: bool


class TalonDecisionEnv:
    """Public policy interface backed by a privileged causal controller."""

    def __init__(self, controller_factory: ControllerFactory, *, default_config: ScenarioConfig | None = None) -> None:
        self._controller_factory = controller_factory
        self._default_config = default_config or ScenarioConfig(family_id="authorised_inspection")
        self._clock = FakeClock()
        self._controller: ScenarioController | None = None
        self._gate: PolicyGate | None = None
        self._frame: ControllerFrame | None = None
        self._config = self._default_config
        self._seed = 0
        self._steps: list[_PrivilegedStep] = []
        self._ended = True
        self._last_public_result: dict[str, Any] | None = None
        self._last_privileged_result: dict[str, Any] | None = None

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        options = options or {}
        raw_config = options.get("scenario_config", self._default_config)
        self._config = raw_config if isinstance(raw_config, ScenarioConfig) else ScenarioConfig.model_validate(raw_config)
        self._seed = 0 if seed is None else seed
        if self._seed < 0:
            raise TalonEnvironmentError("seed must be non-negative", code="invalid_seed")
        self._controller = self._controller_factory(self._config, self._seed)
        from .authority import policy_profile

        self._gate = PolicyGate(
            policy_profile(self._config.policy_profile),
            approval_verifier=self._controller.approval_verifier,
        )
        self._clock.reset()
        self._steps = []
        self._last_public_result = None
        self._last_privileged_result = None
        self._frame = self._controller.reset(self._clock)
        self._ended = False
        return self._frame.observation.public_dict(), {
            "environment_version": ENVIRONMENT_VERSION,
            "observation_schema_version": self._frame.observation.schema_version,
            "action_schema_version": ACTION_SCHEMA_VERSION,
            "episode_id": self._frame.observation.episode_id,
            "maximum_steps": self._config.maximum_steps,
        }

    def step(
        self,
        action: DecisionRecommendation | DecisionAction | str | dict[str, Any],
    ) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        if self._controller is None or self._gate is None or self._frame is None:
            raise TalonEnvironmentError("environment is not reset", code="not_reset")
        if self._ended:
            raise TalonEnvironmentError("episode has ended; call reset", code="episode_ended")
        current = self._frame
        try:
            recommendation = parse_recommendation(
                action,
                default_track_id=current.observation.track_id,
                now_ms=current.observation.timestamp_ms,
            )
        except (TypeError, ValueError) as exc:
            raise TalonEnvironmentError("invalid structured recommendation", code="invalid_action") from exc

        gate = self._gate.evaluate(recommendation, current.observation)
        safety_cost = 1 if gate.violation_codes else 0
        self._clock.advance(1_000)
        next_frame = self._controller.advance(gate.effective_action, self._clock)
        sequence = len(self._steps) + 1
        terminated = next_frame.terminal
        truncated = not terminated and sequence >= self._config.maximum_steps
        self._steps.append(
            _PrivilegedStep(
                sequence=sequence,
                observation=current.observation,
                recommendation=recommendation,
                gate=gate,
                safety_cost=safety_cost,
                terminated=terminated,
                truncated=truncated,
            )
        )
        self._frame = next_frame
        self._ended = terminated or truncated
        # Public reward is deliberately non-probing. Detailed utility is computed
        # only by the privileged verifier after the episode has ended.
        public_reward = 0.0
        return next_frame.observation.public_dict(), public_reward, terminated, truncated, {
            "environment_version": ENVIRONMENT_VERSION,
            "sequence": sequence,
            "gate": gate.model_dump(mode="json"),
            "pending_evidence": [item.value for item in next_frame.observation.pending_evidence],
        }

    def transcript(self) -> list[dict[str, Any]]:
        """Return the allowlisted public timeline only."""

        return [
            {
                "sequence": step.sequence,
                "observation": step.observation.public_dict(),
                "recommendation": step.recommendation.model_dump(mode="json"),
                "gate": step.gate.model_dump(mode="json"),
                "public_reward": 0.0,
                "terminated": step.terminated,
                "truncated": step.truncated,
            }
            for step in self._steps
        ]

    def _ensure_graded(self) -> None:
        if self._controller is None:
            raise TalonEnvironmentError("environment is not reset", code="not_reset")
        if not self._ended:
            raise TalonEnvironmentError("episode must end before grading", code="episode_active")
        if self._last_public_result is None:
            from drone_decision_verifier.scoring import DroneDecisionVerifier

            graded = DroneDecisionVerifier().grade(
                steps=tuple(self._steps),
                verifier_context=self._controller.verifier_context(),
                episode_id=self._frame.observation.episode_id if self._frame else "",
            )
            self._last_public_result = graded["public"]
            self._last_privileged_result = graded["privileged"]

    def grade(self) -> dict[str, Any]:
        """Return only the public strict result."""

        self._ensure_graded()
        return dict(self._last_public_result or {})

    def privileged_record(self) -> dict[str, Any]:
        """Privileged simulator/verifier use only; never mount this on a public route."""

        self._ensure_graded()
        return dict(self._last_privileged_result or {})

    def close(self) -> None:
        self._controller = None
        self._frame = None
        self._gate = None
        self._ended = True

    def __enter__(self) -> "TalonDecisionEnv":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
