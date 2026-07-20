"""External LLM / scripted-external TALON evaluation lane tests (offline only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from drone_decision_ground.actions import DecisionAction, DecisionRecommendation
from drone_decision_ground.authority import policy_profile
from drone_decision_ground.observation import PublicObservation
from drone_decision_ground.policy_gate import PolicyGate
from drone_decision_ground.scenarios import ScenarioConfig
from drone_decision_verifier.hidden_scenarios import build_environment
from drone_decision_verifier.leak_detection import find_public_leaks
from drone_training.external_llm_client import ExternalPolicyClient
from drone_training.external_llm_evaluation import evaluate_external_from_request
from drone_training.external_llm_parser import ExternalLLMParseError, parse_external_llm_response
from drone_training.external_llm_prompt import (
    build_public_prompt_bundle,
    project_public_observation,
    render_prompt_text,
)
from drone_training.external_llm_schemas import ExternalLLMEvaluationCreate
from drone_training.features import ACTIONS
from drone_training.manifests import content_digest
from drone_training.offline_rl import public_action_mask
from drone_training.persistence import TalonStore
from drone_training.replay import public_replay_export, verify_public_replay
from model_runners.errors import ModelRunnerError, ProviderTimeout
from model_runners.protocol import ModelResponse


SENTINEL_FAMILY = "SENTINEL_HIDDEN_FAMILY_xyz"
SENTINEL_INTENT = "SENTINEL_TRUE_INTENT_abc"
SENTINEL_KEY = "sk-sentinel-secret-key-do-not-leak"


def _obs(seed: int = 0) -> PublicObservation:
    config = ScenarioConfig(family_id="authorised_inspection", partition="evaluation")
    env = build_environment(config)
    raw, _ = env.reset(seed=seed, options={"scenario_config": config})
    return PublicObservation.model_validate(raw)


def _allowed(observation: PublicObservation) -> tuple[set[str], set[str]]:
    mask = public_action_mask(observation, profile_id="uk_monitor_and_escalate")
    actions = {action.value for action, enabled in zip(ACTIONS, mask) if enabled}
    from drone_training.external_llm_prompt import allowed_evidence_refs

    return actions, set(allowed_evidence_refs(observation))


def _valid_json(action: str, refs: list[str] | None = None) -> str:
    return json.dumps(
        {
            "action": action,
            "confidence": 0.74,
            "evidence_refs": refs or [],
            "decision_summary": "Additional sensor agreement is required.",
        },
        separators=(",", ":"),
    )


# --- Parser -----------------------------------------------------------------


def test_parser_accepts_valid_response_and_all_actions() -> None:
    observation = _obs()
    allowed, evidence = _allowed(observation)
    for action in ACTIONS:
        if action.value not in allowed:
            # Temporarily widen allowlist for coverage of every action name.
            widened = set(allowed) | {action.value}
            contract = parse_external_llm_response(
                _valid_json(action.value),
                allowed_actions=widened,
                allowed_evidence_refs=evidence,
            )
            assert contract.action == action.value


@pytest.mark.parametrize(
    ("raw", "category"),
    [
        ("not json", "invalid_json"),
        ('```json\n{"action":"CONTINUE_OBSERVATION","confidence":0.5,"evidence_refs":[],"decision_summary":"x"}\n```', "invalid_json"),
        ('Here is JSON: {"action":"CONTINUE_OBSERVATION","confidence":0.5,"evidence_refs":[],"decision_summary":"x"}', "invalid_json"),
        (
            '{"action":"CONTINUE_OBSERVATION","confidence":0.5,"evidence_refs":[],"decision_summary":"x"}{"action":"STAND_DOWN","confidence":0.1,"evidence_refs":[],"decision_summary":"y"}',
            "invalid_json",
        ),
        (
            '{"action":"CONTINUE_OBSERVATION","confidence":0.5,"evidence_refs":[],"decision_summary":"x","extra":1}',
            "schema_invalid",
        ),
        ('{"confidence":0.5,"evidence_refs":[],"decision_summary":"x"}', "schema_invalid"),
        (
            '{"action":"FLY_AWAY","confidence":0.5,"evidence_refs":[],"decision_summary":"x"}',
            "unknown_action",
        ),
        (
            '{"action":"CONTINUE_OBSERVATION","confidence":-0.1,"evidence_refs":[],"decision_summary":"x"}',
            "schema_invalid",
        ),
        (
            '{"action":"CONTINUE_OBSERVATION","confidence":1.1,"evidence_refs":[],"decision_summary":"x"}',
            "schema_invalid",
        ),
        (
            '{"action":"CONTINUE_OBSERVATION","confidence":NaN,"evidence_refs":[],"decision_summary":"x"}',
            "schema_invalid",
        ),
        (
            '{"action":"CONTINUE_OBSERVATION","confidence":Infinity,"evidence_refs":[],"decision_summary":"x"}',
            "schema_invalid",
        ),
        (
            '{"action":"CONTINUE_OBSERVATION","confidence":0.5,"evidence_refs":[],"decision_summary":"' + ("x" * 300) + '"}',
            "schema_invalid",
        ),
        (
            '{"action":"CONTINUE_OBSERVATION","confidence":0.5,"evidence_refs":[],"decision_summary":"' + ("x" * 5000) + '"}',
            "oversized_response",
        ),
    ],
)
def test_parser_rejects_malformed_inputs(raw: str, category: str) -> None:
    observation = _obs()
    allowed, evidence = _allowed(observation)
    # Ensure CONTINUE is allowed for cases that mention it.
    allowed = set(allowed) | {"CONTINUE_OBSERVATION"}
    with pytest.raises(ExternalLLMParseError) as exc:
        parse_external_llm_response(raw, allowed_actions=allowed, allowed_evidence_refs=evidence)
    assert exc.value.category == category


def test_parser_rejects_masked_out_action_and_bad_evidence() -> None:
    observation = _obs()
    allowed, evidence = _allowed(observation)
    masked = next(action.value for action in ACTIONS if action.value not in allowed)
    with pytest.raises(ExternalLLMParseError) as exc:
        parse_external_llm_response(
            _valid_json(masked),
            allowed_actions=allowed,
            allowed_evidence_refs=evidence,
        )
    assert exc.value.category == "action_not_publicly_allowed"
    with pytest.raises(ExternalLLMParseError) as exc:
        parse_external_llm_response(
            _valid_json("ABSTAIN_INSUFFICIENT_EVIDENCE", ["not_a_public_ref"]),
            allowed_actions=allowed | {"ABSTAIN_INSUFFICIENT_EVIDENCE"},
            allowed_evidence_refs=evidence,
        )
    assert exc.value.category == "invalid_evidence_reference"


def test_parser_rejects_tool_call_shaped_payloads_as_schema_invalid() -> None:
    observation = _obs()
    allowed, evidence = _allowed(observation)
    with pytest.raises(ExternalLLMParseError) as exc:
        parse_external_llm_response(
            json.dumps(
                {
                    "action": "CONTINUE_OBSERVATION",
                    "confidence": 0.5,
                    "evidence_refs": [],
                    "decision_summary": "x",
                    "tool_calls": [{"name": "step"}],
                }
            ),
            allowed_actions=allowed | {"CONTINUE_OBSERVATION"},
            allowed_evidence_refs=evidence,
        )
    assert exc.value.category == "schema_invalid"


# --- Prompt isolation -------------------------------------------------------


def test_public_prompt_projection_excludes_hidden_sentinels() -> None:
    observation = _obs()
    # Attach sentinel attributes that must never be projected if present on wrappers.
    privileged = {
        "true_intent": SENTINEL_INTENT,
        "hidden_family": SENTINEL_FAMILY,
        "expert_label": "EXPERT",
        "api_key": SENTINEL_KEY,
    }
    projected = project_public_observation(observation)
    encoded = json.dumps(projected)
    for sentinel in (SENTINEL_INTENT, SENTINEL_FAMILY, SENTINEL_KEY, "true_intent", "hidden_family"):
        assert sentinel not in encoded
    for key in privileged:
        assert key not in projected
    bundle = build_public_prompt_bundle(observation, history=(), profile_id="uk_monitor_and_escalate")
    text = render_prompt_text(bundle)
    for sentinel in (SENTINEL_INTENT, SENTINEL_FAMILY, SENTINEL_KEY):
        assert sentinel not in text
    assert find_public_leaks(projected) == []
    assert find_public_leaks(bundle) == []


# --- Fail-closed client -----------------------------------------------------


def test_scripted_valid_and_malformed_baselines() -> None:
    observation = _obs()
    valid = ExternalPolicyClient(
        policy_kind="scripted_external_baseline",
        provider="scripted_external",
        model="scripted-valid",
        profile_id="uk_monitor_and_escalate",
    )
    rec = valid.recommend(observation)
    assert isinstance(rec, DecisionRecommendation)
    assert rec.recommended_action in DecisionAction
    assert valid.last_trace is not None
    assert valid.last_trace.schema_validation_ok is True

    bad = ExternalPolicyClient(
        policy_kind="scripted_external_baseline",
        provider="scripted_external",
        model="scripted-malformed",
        profile_id="uk_monitor_and_escalate",
    )
    abstain = bad.recommend(observation)
    assert abstain.recommended_action is DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE
    assert bad.last_trace is not None
    assert bad.last_trace.failure_category == "invalid_json"
    assert SENTINEL_KEY not in json.dumps(bad.last_trace.__dict__)


@pytest.mark.parametrize(
    ("exc", "category"),
    [
        (ProviderTimeout(), "timeout"),
        (ModelRunnerError("auth", code="provider_authentication_failed"), "authentication_error"),
        (ModelRunnerError("rate", code="provider_rate_limited"), "rate_limited"),
        (RuntimeError("adapter_error"), "adapter_error"),
    ],
)
def test_provider_failures_become_abstention(exc: Exception, category: str) -> None:
    observation = _obs()
    client = ExternalPolicyClient(
        policy_kind="external_llm",
        provider="openai_compatible",
        model="gpt-test",
        profile_id="uk_monitor_and_escalate",
    )

    async def _boom(**_kwargs: object) -> ModelResponse:
        raise exc

    adapter = MagicMock()
    adapter.complete = _boom
    client._adapter = adapter
    with patch("model_runners.registry.ProviderRegistry.create", return_value=adapter):
        recommendation = client.recommend(observation)
    assert recommendation.recommended_action is DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE
    assert client.last_trace is not None
    assert client.last_trace.failure_category == category
    assert SENTINEL_KEY not in str(client.last_trace)


def test_cancellation_remains_cancellation() -> None:
    observation = _obs()
    client = ExternalPolicyClient(
        policy_kind="scripted_external_baseline",
        provider="scripted_external",
        model="scripted-valid",
        profile_id="uk_monitor_and_escalate",
    )
    client.cancel()
    recommendation = client.recommend(observation)
    assert recommendation.recommended_action is DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE
    assert client.last_trace is not None
    assert client.last_trace.failure_category == "cancelled"


def test_tool_calls_are_rejected() -> None:
    observation = _obs()
    client = ExternalPolicyClient(
        policy_kind="external_llm",
        provider="openai_compatible",
        model="gpt-test",
        profile_id="uk_monitor_and_escalate",
    )

    async def _tools(**_kwargs: object) -> ModelResponse:
        return ModelResponse(
            text=_valid_json("CONTINUE_OBSERVATION"),
            tool_calls=(MagicMock(),),
            latency_ms=1.0,
        )

    adapter = MagicMock()
    adapter.complete = _tools
    client._adapter = adapter
    recommendation = client.recommend(observation)
    assert recommendation.recommended_action is DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE
    assert client.last_trace is not None
    assert client.last_trace.failure_category == "tool_call_rejected"


# --- Authority / gate -------------------------------------------------------


def test_external_recommendation_still_goes_through_real_gate() -> None:
    observation = _obs()
    client = ExternalPolicyClient(
        policy_kind="scripted_external_baseline",
        provider="scripted_external",
        model="scripted-valid",
        profile_id="uk_monitor_and_escalate",
    )
    recommendation = client.recommend(observation)
    gate = PolicyGate(policy_profile("uk_monitor_and_escalate"))
    decision = gate.evaluate(recommendation, observation)
    assert decision.external_effect is False
    # Confidence cannot invent physical authority.
    high = recommendation.model_copy(update={"action_confidence": 1.0})
    again = gate.evaluate(high, observation)
    assert again.external_effect is False


def test_episode_evaluation_uses_gate_and_verifier_and_replay() -> None:
    request = ExternalLLMEvaluationCreate(
        policy_kind="scripted_external_baseline",
        provider="scripted_external",
        model="scripted-valid",
        seed_count=1,
        timeout_seconds=30,
    )
    episode = evaluate_external_from_request(
        request,
        family="authorised_inspection",
        seed=0,
        evaluation_run_id="talon_eval_" + "a" * 32,
    )
    public = episode["public"]
    private = episode["private"]
    assert public["checkpoint_digest"] is None
    assert public["external_policy"]["policy_kind"] == "scripted_external_baseline"
    assert private["manifest"]["checkpoint_provenance"] is False
    assert "model_checkpoint_digest" not in private["manifest"]
    replay = verify_public_replay(
        __import__("drone_training.replay", fromlist=["PublicEpisodeReplay"]).PublicEpisodeReplay.model_validate(
            public["replay"]
        )
    )
    assert replay.checkpoint_digest is None
    assert replay.external_policy is not None
    exported = public_replay_export(replay)
    blob = json.dumps({"public": public, "export": exported, "private_keys": list(private.keys())})
    for sentinel in (SENTINEL_KEY, "Authorization", "OPENAI_API_KEY"):
        assert sentinel not in blob
    assert find_public_leaks(public) == []
    assert find_public_leaks(exported) == []


def test_malformed_scripted_episode_abstains_through_gate_and_verifier() -> None:
    request = ExternalLLMEvaluationCreate(
        policy_kind="scripted_external_baseline",
        provider="scripted_external",
        model="scripted-malformed",
        seed_count=1,
        timeout_seconds=30,
    )
    episode = evaluate_external_from_request(
        request,
        family="authorised_inspection",
        seed=0,
        evaluation_run_id="talon_eval_" + "b" * 32,
    )
    timeline = episode["public"]["timeline"]
    assert timeline
    assert all(
        step["recommendation"]["recommended_action"] == "ABSTAIN_INSUFFICIENT_EVIDENCE" for step in timeline
    )
    assert "result" in episode["public"]
    assert episode["public"]["result"]["result_digest"].startswith("sha256:")


# --- Persistence / digests --------------------------------------------------


def test_prompt_and_config_digests_are_stable_and_response_sensitive(tmp_path: Path) -> None:
    observation = _obs()
    client = ExternalPolicyClient(
        policy_kind="scripted_external_baseline",
        provider="scripted_external",
        model="scripted-valid",
        profile_id="uk_monitor_and_escalate",
    )
    d1 = client.evaluation_config_digest(seed_start=0, seed_count=1, scenario_partition="evaluation")
    d2 = client.evaluation_config_digest(seed_start=0, seed_count=1, scenario_partition="evaluation")
    assert d1 == d2
    bundle = build_public_prompt_bundle(observation, history=(), profile_id="uk_monitor_and_escalate")
    assert bundle["prompt_input_digest"] == build_public_prompt_bundle(
        observation, history=(), profile_id="uk_monitor_and_escalate"
    )["prompt_input_digest"]
    client.recommend(observation)
    first = client.last_trace
    assert first is not None and first.raw_response_digest
    # Mutate model to malformed → different response digest category.
    other = ExternalPolicyClient(
        policy_kind="scripted_external_baseline",
        provider="scripted_external",
        model="scripted-malformed",
        profile_id="uk_monitor_and_escalate",
    )
    other.recommend(observation)
    assert other.last_trace is not None
    assert other.last_trace.raw_response_digest != first.raw_response_digest

    store = TalonStore(tmp_path / "talon.sqlite3")
    try:
        record_id = "talon_eval_" + "c" * 32
        store.create_record(
            record_id,
            "evaluation",
            {
                "schema_version": "talon.public-evaluation-record/2.0",
                "configuration": {
                    "policy_kind": "scripted_external_baseline",
                    "provider": "scripted_external",
                    "model": "scripted-valid",
                },
                "application_commit": "test",
                "progress": {"phase": "queued"},
            },
        )
        from drone_training.exports import public_evaluation_export

        store.finalize(
            record_id,
            "completed",
            {
                "policy_kind": "scripted_external_baseline",
                "provider": "scripted_external",
                "model": "scripted-valid",
                "aggregate": {"episode_count": 0},
                "episodes": [],
                "evaluation_config_digest": d1,
            },
        )
        record = store.get(record_id)
        assert record is not None
        exported = public_evaluation_export(record)
        assert "configuration" not in exported
        assert SENTINEL_KEY not in json.dumps(exported)
        assert exported.get("checkpoint_digest") is None
        # Credentials must never be accepted into public completion payloads.
        from drone_decision_verifier.leak_detection import find_public_leaks

        assert find_public_leaks({"api_key": SENTINEL_KEY}) != []
    finally:
        store.close()


def test_product_api_rejects_policy_client_injection_field() -> None:
    # Schema forbids unknown fields; worker also rejects policy_client.
    with pytest.raises(Exception):
        ExternalLLMEvaluationCreate.model_validate(
            {
                "policy_kind": "scripted_external_baseline",
                "provider": "scripted_external",
                "model": "scripted-valid",
                "policy_client": {"inject": True},
            }
        )


def _drain_queue(queue: Any) -> list[dict[str, Any]]:
    """Drain an in-process worker queue without relying on empty() races."""

    from queue import Empty

    messages: list[dict[str, Any]] = []
    while True:
        try:
            messages.append(queue.get_nowait())
        except Empty:
            return messages


def test_worker_rejects_policy_client_and_checkpoint_binding(tmp_path: Path) -> None:
    from queue import Queue
    from threading import Event

    from drone_training.worker import run_job

    queue: Queue = Queue()
    cancelled = Event()
    run_job(
        "external_llm_evaluation",
        {
            "policy_kind": "scripted_external_baseline",
            "provider": "scripted_external",
            "model": "scripted-valid",
            "seed_start": 0,
            "seed_count": 1,
            "timeout_seconds": 20,
            "scenario_partition": "evaluation",
            "prompt_version": "talon-llm-policy/1.0",
            "temperature": 0.0,
            "max_output_tokens": 300,
            "attempts_per_scenario": 1,
            "run_id": "talon_eval_" + "d" * 32,
            "application_commit": "test",
            "policy_client": "forbidden",
        },
        {
            "data_root": str(tmp_path),
            "private_evaluation": str(tmp_path / "verification.json"),
        },
        queue,
        cancelled,
    )
    messages = _drain_queue(queue)
    assert any(item.get("type") == "failed" for item in messages)


def test_end_to_end_scripted_worker_completes(tmp_path: Path) -> None:
    from queue import Queue
    from threading import Event

    from drone_training.worker import run_job

    private_eval = tmp_path / "private" / "talon_eval_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    private_eval.mkdir(parents=True)
    queue: Queue = Queue()
    cancelled = Event()
    run_job(
        "external_llm_evaluation",
        {
            "policy_kind": "scripted_external_baseline",
            "provider": "scripted_external",
            "model": "scripted-valid",
            "seed_start": 0,
            "seed_count": 1,
            "timeout_seconds": 30,
            "scenario_partition": "evaluation",
            "prompt_version": "talon-llm-policy/1.0",
            "temperature": 0.0,
            "max_output_tokens": 300,
            "attempts_per_scenario": 1,
            "run_id": "talon_eval_" + "e" * 32,
            "application_commit": "test",
        },
        {
            "data_root": str(tmp_path),
            "private_evaluation": str(private_eval / "verification.json"),
        },
        queue,
        cancelled,
    )
    messages = _drain_queue(queue)
    completed = [item for item in messages if item.get("type") == "completed"]
    assert completed, messages
    payload = completed[0]["data"]
    assert payload["algorithm"] == "scripted_external_baseline"
    assert payload["checkpoint_digest"] is None
    assert payload["aggregate"]["episode_count"] == 15
    assert "provider_failure_rate" in payload["aggregate"]
    blob = json.dumps(payload)
    assert SENTINEL_KEY not in blob
    assert find_public_leaks(payload["episodes"]) == []


def test_product_api_creates_scripted_external_evaluation(tmp_path: Path) -> None:
    import time

    from evaluation_service.app import create_app
    from evaluation_service.settings import Settings
    from fastapi.testclient import TestClient

    settings = Settings(
        data_dir=tmp_path / "frontier",
        database_path=tmp_path / "frontier" / "evaluations.sqlite3",
        talon_data_dir=tmp_path / "talon",
        talon_database_path=tmp_path / "talon" / "talon.sqlite3",
    )
    app = create_app(settings)
    headers = {"Origin": "http://localhost:3000", "Idempotency-Key": "external-scripted-0001"}
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        readiness = client.get("/api/drone/external-llm/readiness")
        assert readiness.status_code == 200
        assert readiness.json()["simulation_only"] is True
        assert "anthropic" in readiness.json()["unsupported_providers"]
        created = client.post(
            "/api/drone/external-llm/evaluations",
            headers=headers,
            json={
                "policy_kind": "scripted_external_baseline",
                "provider": "scripted_external",
                "model": "scripted-valid",
                "prompt_version": "talon-llm-policy/1.0",
                "temperature": 0,
                "timeout_seconds": 30,
                "max_output_tokens": 300,
                "attempts_per_scenario": 1,
                "scenario_partition": "evaluation",
                "seed_count": 1,
            },
        )
        assert created.status_code == 202, created.text
        evaluation_id = created.json()["evaluation_id"]
        record: dict[str, object] | None = None
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            response = client.get(f"/api/drone/evaluations/{evaluation_id}")
            assert response.status_code == 200
            record = response.json()
            if record["status"] in {"completed", "failed", "cancelled", "timed_out"}:
                break
            time.sleep(0.1)
        assert record is not None
        assert record["status"] == "completed", record
        assert record["algorithm"] == "scripted_external_baseline"
        assert record.get("checkpoint_digest") is None
        # Public evaluation detail does not re-export the full create configuration,
        # but the numeric output budget must remain a safe public field name.
        assert find_public_leaks({"configuration": {"max_output_tokens": 300}}) == []
        assert find_public_leaks(record) == []
        episode_id = record["episodes"][0]["result"]["episode_id"]
        replay = client.get(f"/api/drone/episodes/{episode_id}/replay")
        assert replay.status_code == 200
        body = replay.json()
        assert body["checkpoint_digest"] is None
        assert body["external_policy"]["policy_kind"] == "scripted_external_baseline"
        assert find_public_leaks(body) == []
