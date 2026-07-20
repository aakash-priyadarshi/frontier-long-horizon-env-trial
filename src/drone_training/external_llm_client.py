"""Fail-closed external / scripted TALON policy clients."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from drone_decision_ground.actions import DecisionAction, DecisionRecommendation
from drone_decision_ground.observation import PublicObservation

from .external_llm_parser import ExternalLLMParseError, parse_external_llm_response
from .external_llm_prompt import (
    allowed_evidence_refs,
    build_public_prompt_bundle,
    render_prompt_text,
)
from .external_llm_schemas import (
    PROMPT_VERSION,
    PROVIDER_ADAPTER_VERSION,
    ExternalLLMEvaluationCreate,
)
from .manifests import content_digest
from .offline_rl import public_action_mask


FailureCategory = Literal[
    "timeout",
    "authentication_error",
    "rate_limited",
    "provider_unavailable",
    "invalid_json",
    "schema_invalid",
    "unknown_action",
    "action_not_publicly_allowed",
    "invalid_evidence_reference",
    "oversized_response",
    "tool_call_rejected",
    "cancelled",
    "adapter_error",
]

_ERROR_CODE_MAP: dict[str, FailureCategory] = {
    "provider_timeout": "timeout",
    "provider_authentication_failed": "authentication_error",
    "provider_rate_limited": "rate_limited",
    "provider_quota_exceeded": "rate_limited",
    "provider_not_configured": "provider_unavailable",
    "provider_unavailable": "provider_unavailable",
    "provider_http_error": "provider_unavailable",
    "provider_model_not_found": "provider_unavailable",
    "provider_request_rejected": "adapter_error",
    "provider_request_incompatible": "adapter_error",
    "provider_out_of_memory": "provider_unavailable",
    "provider_context_limit": "adapter_error",
    "malformed_model_response": "invalid_json",
    "provider_error": "adapter_error",
}


@dataclass
class ExternalPolicyStepTrace:
    """Sanitised per-step provenance retained for replay (never secrets or raw CoT)."""

    prompt_input_digest: str
    raw_response_digest: str | None
    parsed_response_digest: str | None
    provider_latency_ms: float | None
    schema_validation_ok: bool
    failure_category: FailureCategory | None
    selected_action: str
    confidence: float
    evidence_refs: tuple[str, ...]
    decision_summary: str
    provider_outcome: str


@dataclass
class ExternalPolicyClient:
    """Production external-policy client. Failures become gated abstentions."""

    policy_kind: Literal["external_llm", "scripted_external_baseline"]
    provider: Literal["openai_compatible", "scripted_external"]
    model: str
    prompt_version: str = PROMPT_VERSION
    temperature: float = 0.0
    timeout_seconds: float = 30.0
    max_output_tokens: int = 300
    profile_id: str = "uk_monitor_and_escalate"
    history_bound: int = 4
    _history: list[PublicObservation] = field(default_factory=list, init=False, repr=False)
    last_trace: ExternalPolicyStepTrace | None = field(default=None, init=False, repr=False)
    _cancelled: bool = field(default=False, init=False, repr=False)
    _adapter: Any = field(default=None, init=False, repr=False)

    def reset(self) -> None:
        self._history = []
        self.last_trace = None
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def close(self) -> None:
        self._adapter = None

    @classmethod
    def from_config(cls, config: ExternalLLMEvaluationCreate, *, profile_id: str) -> ExternalPolicyClient:
        return cls(
            policy_kind=config.policy_kind,
            provider=config.provider,
            model=config.model,
            prompt_version=config.prompt_version,
            temperature=float(config.temperature),
            timeout_seconds=float(config.timeout_seconds),
            max_output_tokens=int(config.max_output_tokens),
            profile_id=profile_id,
        )

    def evaluation_config_digest(self, *, seed_start: int, seed_count: int, scenario_partition: str) -> str:
        return content_digest(
            {
                "policy_kind": self.policy_kind,
                "provider": self.provider,
                "model": self.model,
                "prompt_version": self.prompt_version,
                "provider_adapter_version": PROVIDER_ADAPTER_VERSION,
                "temperature": self.temperature,
                "timeout_seconds": self.timeout_seconds,
                "max_output_tokens": self.max_output_tokens,
                "attempts_per_scenario": 1,
                "scenario_partition": scenario_partition,
                "seed_start": seed_start,
                "seed_count": seed_count,
            }
        )

    def recommend(self, observation: PublicObservation) -> DecisionRecommendation:
        if self._cancelled:
            return self._abstain(observation, category="cancelled", latency_ms=None, raw=None, prompt_digest="sha256:" + "0" * 64)

        mask = public_action_mask(observation, profile_id=self.profile_id)
        from .features import ACTIONS

        allowed_actions = {action.value for action, enabled in zip(ACTIONS, mask) if enabled}
        evidence = set(allowed_evidence_refs(observation))
        history = tuple(self._history[-self.history_bound :])
        bundle = build_public_prompt_bundle(
            observation,
            history=history,
            profile_id=self.profile_id,
            prompt_version=self.prompt_version,
        )
        prompt_digest = str(bundle["prompt_input_digest"])
        prompt_text = render_prompt_text(bundle)

        started = time.monotonic()
        try:
            raw_text, latency_ms, tool_calls = self._invoke_provider(prompt_text)
        except _CancelledError:
            return self._abstain(observation, category="cancelled", latency_ms=None, raw=None, prompt_digest=prompt_digest)
        except Exception as exc:  # noqa: BLE001 - fail closed
            category = self._classify_exception(exc)
            return self._abstain(
                observation,
                category=category,
                latency_ms=round((time.monotonic() - started) * 1_000, 3),
                raw=None,
                prompt_digest=prompt_digest,
            )

        if tool_calls:
            return self._abstain(
                observation,
                category="tool_call_rejected",
                latency_ms=latency_ms,
                raw=raw_text,
                prompt_digest=prompt_digest,
            )

        try:
            contract = parse_external_llm_response(
                raw_text,
                allowed_actions=allowed_actions,
                allowed_evidence_refs=evidence,
            )
        except ExternalLLMParseError as exc:
            return self._abstain(
                observation,
                category=exc.category,  # type: ignore[arg-type]
                latency_ms=latency_ms,
                raw=raw_text,
                prompt_digest=prompt_digest,
            )

        parsed_digest = content_digest(contract.model_dump(mode="json"))
        raw_digest = _response_digest(raw_text)
        action = DecisionAction(contract.action)
        self.last_trace = ExternalPolicyStepTrace(
            prompt_input_digest=prompt_digest,
            raw_response_digest=raw_digest,
            parsed_response_digest=parsed_digest,
            provider_latency_ms=latency_ms,
            schema_validation_ok=True,
            failure_category=None,
            selected_action=action.value,
            confidence=float(contract.confidence),
            evidence_refs=tuple(contract.evidence_refs),
            decision_summary=contract.decision_summary,
            provider_outcome="ok",
        )
        self._history.append(observation)
        return DecisionRecommendation(
            recommended_action=action,
            target_track_id=observation.track_id,
            valid_until_ms=observation.timestamp_ms + 1_000,
            action_confidence=float(contract.confidence),
            threat_probability=0.0,
            uncertainty=max(0.0, 1.0 - float(contract.confidence)),
            missing_evidence=(),
            reason_codes=("external_llm_policy",) if self.policy_kind == "external_llm" else ("scripted_external_baseline",),
        )

    def _invoke_provider(self, prompt_text: str) -> tuple[str, float, tuple[Any, ...]]:
        if self.provider == "scripted_external":
            return self._scripted_response(prompt_text)
        return self._openai_compatible_response(prompt_text)

    def _scripted_response(self, prompt_text: str) -> tuple[str, float, tuple[Any, ...]]:
        started = time.monotonic()
        if self._cancelled:
            raise _CancelledError()
        mode = self.model.strip().lower()
        # Deterministic valid JSON: prefer CONTINUE_OBSERVATION when allowed, else abstain.
        if mode in {"scripted-valid", "valid", "scripted_valid"}:
            allowed = _allowed_actions_from_prompt(prompt_text)
            action = "CONTINUE_OBSERVATION" if "CONTINUE_OBSERVATION" in allowed else "ABSTAIN_INSUFFICIENT_EVIDENCE"
            refs = _allowed_refs_from_prompt(prompt_text)[:2]
            payload = {
                "action": action,
                "confidence": 0.55,
                "evidence_refs": refs,
                "decision_summary": "Scripted external baseline selected a publicly allowed action.",
            }
            return json.dumps(payload, separators=(",", ":")), round((time.monotonic() - started) * 1_000, 3), ()
        if mode in {"scripted-malformed", "malformed", "scripted_malformed"}:
            return (
                '```json\n{"action":"CONTINUE_OBSERVATION","confidence":0.5,"evidence_refs":[],"decision_summary":"bad"}\n```',
                round((time.monotonic() - started) * 1_000, 3),
                (),
            )
        raise RuntimeError(f"unknown scripted external model id: {self.model}")

    def _openai_compatible_response(self, prompt_text: str) -> tuple[str, float, tuple[Any, ...]]:
        from model_runners.errors import ModelRunnerError, ProviderTimeout
        from model_runners.protocol import ModelMessage, ModelRequestConfig
        from model_runners.registry import ProviderRegistry

        if self._adapter is None:
            self._adapter = ProviderRegistry().create("openai-compatible")

        async def _run() -> Any:
            return await self._adapter.complete(
                messages=[
                    ModelMessage(
                        role="system",
                        content=(
                            "You are a simulation-only TALON decision-support policy. "
                            "Return exactly one plain JSON object. No markdown. No tool calls."
                        ),
                    ),
                    ModelMessage(role="user", content=prompt_text),
                ],
                tools=[],
                config=ModelRequestConfig(
                    model=self.model,
                    temperature=self.temperature,
                    max_output_tokens=self.max_output_tokens,
                    timeout_seconds=self.timeout_seconds,
                    max_retries=0,
                    deterministic=True,
                ),
            )

        started = time.monotonic()
        try:
            response = asyncio.run(_run())
        except ProviderTimeout as exc:
            raise exc
        except ModelRunnerError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("adapter_error") from exc
        latency = round((time.monotonic() - started) * 1_000, 3)
        if getattr(response, "latency_ms", None):
            latency = float(response.latency_ms)
        tool_calls = tuple(getattr(response, "tool_calls", ()) or ())
        return str(response.text or ""), latency, tool_calls

    def _abstain(
        self,
        observation: PublicObservation,
        *,
        category: FailureCategory,
        latency_ms: float | None,
        raw: str | None,
        prompt_digest: str,
    ) -> DecisionRecommendation:
        self.last_trace = ExternalPolicyStepTrace(
            prompt_input_digest=prompt_digest,
            raw_response_digest=_response_digest(raw) if raw is not None else None,
            parsed_response_digest=None,
            provider_latency_ms=latency_ms,
            schema_validation_ok=False,
            failure_category=category,
            selected_action=DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE.value,
            confidence=0.0,
            evidence_refs=(),
            decision_summary="",
            provider_outcome=category,
        )
        self._history.append(observation)
        return DecisionRecommendation(
            recommended_action=DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE,
            target_track_id=observation.track_id,
            valid_until_ms=observation.timestamp_ms + 1_000,
            action_confidence=0.0,
            threat_probability=0.0,
            uncertainty=1.0,
            missing_evidence=(),
            reason_codes=("external_policy_fail_closed", category),
        )

    @staticmethod
    def _classify_exception(exc: Exception) -> FailureCategory:
        from model_runners.errors import ModelRunnerError, ProviderTimeout

        if isinstance(exc, ProviderTimeout):
            return "timeout"
        if isinstance(exc, ModelRunnerError):
            return _ERROR_CODE_MAP.get(exc.code, "adapter_error")
        message = str(exc).lower()
        if "adapter_error" in message:
            return "adapter_error"
        return "adapter_error"


class _CancelledError(RuntimeError):
    pass


def _response_digest(raw: str | None) -> str | None:
    if raw is None:
        return None
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _allowed_actions_from_prompt(prompt_text: str) -> set[str]:
    actions: set[str] = set()
    capture = False
    for line in prompt_text.splitlines():
        if line.startswith("Allowed actions now:"):
            capture = True
            continue
        if capture:
            if line.startswith("Allowed public"):
                break
            if line.startswith("- "):
                name = line[2:].split(":", 1)[0].strip()
                if name:
                    actions.add(name)
    return actions


def _allowed_refs_from_prompt(prompt_text: str) -> list[str]:
    refs: list[str] = []
    capture = False
    for line in prompt_text.splitlines():
        if line.startswith("Allowed public evidence references:"):
            capture = True
            continue
        if capture:
            if line.startswith("Bounded public") or line.startswith("Current public"):
                break
            if line.startswith("- ") and line.strip() != "- (none)":
                refs.append(line[2:].strip())
    return refs


def openai_compatible_readiness() -> dict[str, Any]:
    """Public readiness without revealing secrets or endpoint query strings."""

    from model_runners.configuration import RuntimeProviderSettings, secret_for

    settings = RuntimeProviderSettings()
    configured = secret_for("openai-compatible", settings) is not None
    try:
        base = settings.public_base_url("openai-compatible")
        endpoint_ok = bool(base)
    except Exception:  # noqa: BLE001
        endpoint_ok = False
        base = None
    return {
        "provider": "openai_compatible",
        "configured": configured,
        "endpoint_configured": endpoint_ok,
        "secret_present": configured,
        "ready": configured and endpoint_ok,
        "simulation_only": True,
        "unsupported_providers": ["anthropic", "gemini", "ollama"],
    }
