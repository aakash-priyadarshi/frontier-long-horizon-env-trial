from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from evaluation_service.app import create_app
from evaluation_service.orchestration import EvaluationOrchestrator
from evaluation_service.persistence import EvaluationStore, record_digest
from evaluation_service.runner import EpisodeRunner
from evaluation_service.schemas import EvaluationCreate, EvaluationLimits
from evaluation_service.settings import Settings, dashboard_origins
from model_runners.configuration import RuntimeProviderSettings
from model_runners.protocol import ModelMessage, ModelRequestConfig, ModelResponse, ModelTool, ModelToolCall
from model_runners.errors import ModelRunnerError
from model_runners.registry import ProviderRegistry


async def run_request(tmp_path: Path, model: str) -> dict:
    store = EvaluationStore(tmp_path / f"{model}.sqlite3")
    orchestrator = EvaluationOrchestrator(store)
    request = EvaluationCreate(provider="scripted", model=model)
    batch_id = orchestrator.create(request, start_background=False)
    await orchestrator.run_batch(batch_id)
    batch = store.get_batch(batch_id)
    assert batch is not None
    run = batch["runs"][0]
    store.close()
    return run


@pytest.mark.asyncio
async def test_scripted_valid_model_uses_real_verifier(tmp_path: Path) -> None:
    run = await run_request(tmp_path, "scripted-valid")
    assert run["authoritative_reward"] == 1.0
    assert run["authoritative_verdict"] == "pass"
    assert run["action_count"] == 20
    assert len(run["distinct_tools"]) == 12
    assert record_digest(run) == run["record_digest"]
    payload = json.dumps(run)
    assert "auth_tag" not in payload
    assert "H-" not in payload


@pytest.mark.asyncio
async def test_scripted_wrong_control_is_not_strict_success(tmp_path: Path) -> None:
    run = await run_request(tmp_path, "scripted-wrong-control")
    assert run["authoritative_reward"] == 0.85
    assert run["authoritative_verdict"] == "partial"
    assert "member_hidden_workloads_pass" in run["failed_predicates"]


class UnknownToolAdapter:
    provider = "test"
    async def complete(self, *, messages: list[ModelMessage], tools: list[ModelTool], config: ModelRequestConfig) -> ModelResponse:
        return ModelResponse(tool_calls=(ModelToolCall("x", "shell.exec", {"command": "whoami"}),))


class SlowAdapter:
    provider = "test"
    async def complete(self, *, messages: list[ModelMessage], tools: list[ModelTool], config: ModelRequestConfig) -> ModelResponse:
        await asyncio.sleep(2)
        return ModelResponse()


class FlakyAdapter:
    provider = "test"
    def __init__(self) -> None:
        self.calls = 0
    async def complete(self, *, messages: list[ModelMessage], tools: list[ModelTool], config: ModelRequestConfig) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            raise ModelRunnerError("temporary", retryable=True)
        return ModelResponse(finish_reason="stop")


class UsageAdapter:
    provider = "test"
    async def complete(self, *, messages: list[ModelMessage], tools: list[ModelTool], config: ModelRequestConfig) -> ModelResponse:
        return ModelResponse(input_tokens=10, output_tokens=2, finish_reason="stop")


class SequenceAdapter:
    provider = "test"
    def __init__(self, calls: list[tuple[str, dict]]) -> None:
        self.calls = calls
    async def complete(self, *, messages: list[ModelMessage], tools: list[ModelTool], config: ModelRequestConfig) -> ModelResponse:
        if not self.calls:
            return ModelResponse(finish_reason="stop")
        name, arguments = self.calls.pop(0)
        return ModelResponse(tool_calls=(ModelToolCall(f"call-{len(messages)}", name, arguments),))


class InfiniteStatusAdapter:
    provider = "test"
    async def complete(self, *, messages: list[ModelMessage], tools: list[ModelTool], config: ModelRequestConfig) -> ModelResponse:
        return ModelResponse(tool_calls=(ModelToolCall(f"call-{len(messages)}", "release.status", {}),))


async def direct_episode(tmp_path: Path, adapter: object, *, limits: EvaluationLimits | None = None, cancelled: asyncio.Event | None = None, provider: str = "scripted", model: str = "scripted-valid") -> dict:
    events: list[tuple[str, dict]] = []
    async def emit(name: str, data: dict) -> None:
        events.append((name, data))
    request = EvaluationCreate(provider=provider, model=model, limits=limits or EvaluationLimits())
    runner = EpisodeRunner(
        adapter=adapter, request=request, seed=0, attempt=1,
        environment_commit="a" * 40, application_commit="b" * 40,
        cancelled=cancelled or asyncio.Event(), emit=emit,
    )
    outcome = await runner.run()
    return {"status": outcome.status, **outcome.payload, "events": events}


class CapturingConfigAdapter:
    provider = "ollama"

    def __init__(self) -> None:
        self.configs: list[ModelRequestConfig] = []

    async def complete(self, *, messages: list[ModelMessage], tools: list[ModelTool], config: ModelRequestConfig) -> ModelResponse:
        self.configs.append(config)
        return ModelResponse(finish_reason="stop")


class CapabilityFollowingAdapter:
    provider = "test"

    def __init__(self) -> None:
        self.calls = 0
        self.received_handle: str | None = None

    async def complete(self, *, messages: list[ModelMessage], tools: list[ModelTool], config: ModelRequestConfig) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(tool_calls=(ModelToolCall("logs", "telemetry.logs", {"alias": "Q-41"}),))
        if self.calls == 2:
            tool_result = json.loads(messages[-1].content)
            self.received_handle = tool_result["result"]["handle"]
            return ModelResponse(tool_calls=(ModelToolCall("trace", "telemetry.trace", {"handle": self.received_handle}),))
        return ModelResponse(finish_reason="stop")


@pytest.mark.asyncio
async def test_ollama_episodes_do_not_silently_disable_thinking(tmp_path: Path) -> None:
    adapter = CapturingConfigAdapter()
    outcome = await direct_episode(tmp_path, adapter, provider="ollama", model="qwen3:8b")
    assert outcome["status"] == "completed"
    assert adapter.configs
    assert adapter.configs[0].reasoning_effort is None
    assert outcome["model_turn_debug"][0]["tool_call_count"] == 0
    assert outcome["tool_use_debug"]["primary_cause"]["code"] == "no_tool_calls"


@pytest.mark.asyncio
async def test_ephemeral_trace_handle_reaches_model_but_not_public_record(tmp_path: Path) -> None:
    adapter = CapabilityFollowingAdapter()
    outcome = await direct_episode(tmp_path, adapter)
    assert adapter.received_handle
    assert outcome["status"] == "completed"
    assert outcome["action_count"] == 2
    assert all(entry["success"] for entry in outcome["authenticated_timeline"])
    assert "handle" not in outcome["authenticated_timeline"][0]["result_summary"]
    assert "handle" not in outcome["authenticated_timeline"][1]["arguments"]


@pytest.mark.asyncio
async def test_repeated_successful_read_loop_gets_one_warning_then_terminates(tmp_path: Path) -> None:
    outcome = await direct_episode(
        tmp_path,
        SequenceAdapter([
            ("workspace.read", {"path": "service/contract.md"}),
            ("workspace.read", {"path": "service/contract.md"}),
            ("workspace.read", {"path": "service/contract.md"}),
            ("workspace.edit", {"path": "service/settings.toml", "content": "unused"}),
        ]),
    )
    assert outcome["status"] == "completed"
    assert outcome["termination_reason"] == "model_repetitive_tool_loop"
    assert outcome["action_count"] == 3
    assert [item["code"] for item in outcome["runner_guidance"]] == [
        "repeated_read_only_cycle_warning",
        "repeated_read_only_cycle_terminated",
    ]
    assert outcome["tool_use_debug"]["primary_cause"]["code"] == "model_repetitive_tool_loop"


@pytest.mark.asyncio
async def test_unknown_tool_is_rejected_without_execution(tmp_path: Path) -> None:
    outcome = await direct_episode(tmp_path, UnknownToolAdapter())
    assert outcome["status"] == "failed"
    assert outcome["error_category"] == "unknown_tool"
    assert outcome["action_count"] == 0
    assert outcome["authoritative_reward"] == 0.0


@pytest.mark.asyncio
async def test_invalid_tool_arguments_return_to_model_without_crashing_episode(tmp_path: Path) -> None:
    outcome = await direct_episode(
        tmp_path,
        SequenceAdapter([
            ("recovery.pause", {}),
            ("recovery.restore", {"snapshot": "S0"}),
        ]),
    )
    assert outcome["status"] == "completed"
    assert outcome["error_category"] is None
    assert outcome["termination_reason"] == "model_stopped"
    assert outcome["action_count"] == 2
    invalid = outcome["authenticated_timeline"][1]
    assert invalid["tool"] == "recovery.restore"
    assert invalid["success"] is False
    assert invalid["error_code"] == "invalid_arguments"


@pytest.mark.asyncio
async def test_prose_only_model_stop_is_distinct_from_a_completed_tool_sequence(tmp_path: Path) -> None:
    outcome = await direct_episode(tmp_path, UsageAdapter())
    assert outcome["status"] == "completed"
    assert outcome["termination_reason"] == "model_stopped_without_tool_call"
    assert outcome["action_count"] == 0


@pytest.mark.asyncio
async def test_provider_timeout_is_terminal(tmp_path: Path) -> None:
    request_limits = EvaluationLimits(wall_clock_seconds=5)
    events: list = []
    async def emit(name: str, data: dict) -> None: events.append((name, data))
    request = EvaluationCreate(
        provider="scripted", model="scripted-valid", limits=request_limits,
        model_configuration={"timeout_seconds": 1, "max_retries": 0},
    )
    runner = EpisodeRunner(adapter=SlowAdapter(), request=request, seed=0, attempt=1, environment_commit="a"*40, application_commit="b"*40, cancelled=asyncio.Event(), emit=emit)
    outcome = await runner.run()
    assert outcome.status == "failed"
    assert outcome.payload["error_category"] == "provider_timeout"


@pytest.mark.asyncio
async def test_precancelled_episode_never_calls_model(tmp_path: Path) -> None:
    cancelled = asyncio.Event(); cancelled.set()
    outcome = await direct_episode(tmp_path, UnknownToolAdapter(), cancelled=cancelled)
    assert outcome["status"] == "cancelled"
    assert outcome["action_count"] == 0
    assert outcome["authoritative_reward"] == 0.0


@pytest.mark.asyncio
async def test_cancellation_interrupts_inflight_provider_wait(tmp_path: Path) -> None:
    cancelled = asyncio.Event()
    task = asyncio.create_task(direct_episode(tmp_path, SlowAdapter(), cancelled=cancelled))
    await asyncio.sleep(0.05)
    cancelled.set()
    outcome = await asyncio.wait_for(task, timeout=1)
    assert outcome["status"] == "cancelled"


@pytest.mark.asyncio
async def test_wall_clock_budget_bounds_provider_wait(tmp_path: Path) -> None:
    outcome = await direct_episode(
        tmp_path,
        SlowAdapter(),
        limits=EvaluationLimits(wall_clock_seconds=1),
    )
    assert outcome["status"] == "completed"
    assert outcome["termination_reason"] == "wall_clock_budget"
    assert outcome["authoritative_reward"] == 0.0


@pytest.mark.asyncio
async def test_retryable_provider_error_retries_once(tmp_path: Path) -> None:
    adapter = FlakyAdapter()
    events: list[tuple[str, dict]] = []
    async def emit(name: str, data: dict) -> None: events.append((name, data))
    request = EvaluationCreate(provider="scripted", model="scripted-valid")
    runner = EpisodeRunner(adapter=adapter, request=request, seed=0, attempt=1, environment_commit="a"*40, application_commit="b"*40, cancelled=asyncio.Event(), emit=emit)
    response = await runner._complete_with_retry([], ModelRequestConfig(model="test", max_retries=1))
    assert response.finish_reason == "stop"
    assert adapter.calls == 2
    assert events[0][0] == "provider_retry"


@pytest.mark.asyncio
async def test_token_budget_stops_before_tool_execution(tmp_path: Path) -> None:
    outcome = await direct_episode(
        tmp_path,
        UsageAdapter(),
        limits=EvaluationLimits(input_token_budget=1),
    )
    assert outcome["status"] == "completed"
    assert outcome["termination_reason"] == "input_token_budget"
    assert outcome["action_count"] == 0


@pytest.mark.asyncio
async def test_arbitrary_file_request_is_rejected_by_real_tool_boundary(tmp_path: Path) -> None:
    outcome = await direct_episode(
        tmp_path,
        SequenceAdapter([("workspace.read", {"path": "../../outside.txt"})]),
    )
    entry = outcome["authenticated_timeline"][0]
    assert entry["success"] is False
    assert "outside workspace" in json.dumps(entry["result_summary"])
    assert outcome["authoritative_reward"] == 0.0


@pytest.mark.asyncio
async def test_direct_hidden_workload_request_reaches_unknown_workload_rejection(tmp_path: Path) -> None:
    outcome = await direct_episode(
        tmp_path,
        SequenceAdapter([
            ("recovery.pause", {}),
            ("runtime.run", {"workload_id": "H-forbidden"}),
        ]),
    )
    entry = outcome["authenticated_timeline"][1]
    assert entry["success"] is False
    assert entry["error_code"] == "unknown_workload"
    assert "H-forbidden" not in json.dumps(outcome)


@pytest.mark.asyncio
async def test_model_call_budget_is_enforced(tmp_path: Path) -> None:
    outcome = await direct_episode(
        tmp_path,
        InfiniteStatusAdapter(),
        limits=EvaluationLimits(max_model_calls=1),
    )
    assert outcome["termination_reason"] == "model_call_budget"
    assert outcome["model_call_count"] == 1
    assert outcome["action_count"] == 1


@pytest.mark.asyncio
async def test_environment_step_budget_is_enforced(tmp_path: Path) -> None:
    outcome = await direct_episode(
        tmp_path,
        InfiniteStatusAdapter(),
        limits=EvaluationLimits(max_steps=1),
    )
    assert outcome["termination_reason"] == "environment_truncated"
    assert outcome["action_count"] == 1
    assert outcome["authenticated_timeline"][0]["truncated"] is True


def app_settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, database_path=tmp_path / "api.sqlite3")


def test_orchestrator_rejects_model_with_failed_tool_compatibility(tmp_path: Path) -> None:
    registry = ProviderRegistry(RuntimeProviderSettings({}))
    registry._discovered_models["ollama"] = [{
        "id": "incompatible-local-model",
        "display_name": "incompatible-local-model",
        "digest": "digest-one",
    }]
    registry._tool_probes[("ollama", "incompatible-local-model")] = {
        "state": "failed",
        "tested_at": "2026-07-14T00:00:00Z",
        "model": "incompatible-local-model",
        "model_digest": "digest-one",
        "error_code": "invalid_tool_call",
    }
    store = EvaluationStore(tmp_path / "failed-tool.sqlite3")
    orchestrator = EvaluationOrchestrator(store, registry)
    with pytest.raises(ValueError, match="failed the required tool compatibility"):
        orchestrator.create(EvaluationCreate(provider="ollama", model="incompatible-local-model"))
    store.close()


def test_orchestrator_requires_current_passing_ollama_tool_test(tmp_path: Path) -> None:
    registry = ProviderRegistry(RuntimeProviderSettings({}))
    registry._discovered_models["ollama"] = [{
        "id": "untested-local-model",
        "display_name": "untested-local-model",
        "digest": "digest-one",
    }]
    store = EvaluationStore(tmp_path / "untested-tool.sqlite3")
    orchestrator = EvaluationOrchestrator(store, registry)
    with pytest.raises(ValueError, match="must pass the current tool compatibility"):
        orchestrator.create(EvaluationCreate(provider="ollama", model="untested-local-model"))
    store.close()


def test_api_health_provider_status_and_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "api-secret-must-never-return"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    app = create_app(app_settings(tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        providers = client.get("/api/providers").json()
        assert secret not in json.dumps(providers)
        bad = client.post("/api/evaluations", json={"provider": "scripted", "model": "not-valid"})
        assert bad.status_code == 422
        assert bad.json()["error"]["code"] == "validation_error"
        overwrite = client.post(
            "/api/evaluations",
            json={"provider": "scripted", "model": "scripted-valid", "authoritative_reward": 1},
        )
        assert overwrite.status_code == 422

        support = client.get("/api/providers/ollama/tool-support")
        assert support.status_code == 200
        assert support.headers["cache-control"] == "no-store"
        assert any(item["id"] == "qwen3" for item in support.json()["items"])
        assert support.json()["custom_probe"]["executes_tool"] is False

        invalid_probe = client.post(
            "/api/providers/ollama/tool-probe",
            headers={"Origin": "http://localhost:3000"},
            json={"model": "local-model", "options": {"context_window": 2_048}},
        )
        assert invalid_probe.status_code == 422
        assert invalid_probe.json()["error"]["code"] == "validation_error"


def test_session_credential_api_never_returns_or_persists_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "session-secret-never-persist"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = create_app(app_settings(tmp_path))
    headers = {"Origin": "http://localhost:3000"}
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        saved = client.post(
            "/api/providers/anthropic/credentials",
            json={"credential": secret},
            headers=headers,
        )
        assert saved.status_code == 200
        assert saved.headers["cache-control"] == "no-store"
        assert saved.json()["provider"]["credential"]["source"] == "session"
        assert secret not in saved.text
        providers = client.get("/api/providers")
        assert secret not in providers.text
        assert next(item for item in providers.json()["items"] if item["provider"] == "anthropic")["configured"] is True

        evaluation = client.post("/api/evaluations", json={"provider": "scripted", "model": "scripted-valid"})
        batch_id = evaluation.json()["batch_id"]
        deadline = time.monotonic() + 20
        batch = {}
        while time.monotonic() < deadline:
            batch = client.get(f"/api/evaluations/{batch_id}").json()
            if batch.get("status") == "completed":
                break
            time.sleep(0.05)
        assert batch["status"] == "completed"
        events = client.get(f"/api/evaluations/{batch_id}/events")
        exported = client.get(f"/api/exports/{batch_id}.json")
        assert secret not in events.text
        assert secret not in exported.text
        assert secret not in caplog.text

        cleared = client.delete("/api/providers/anthropic/credentials", headers=headers)
        assert cleared.status_code == 200
        assert cleared.json()["provider"]["credential"]["source"] == "missing"
        unavailable = client.post("/api/evaluations", json={"provider": "anthropic", "model": "test-model"})
        assert unavailable.status_code == 409
    assert secret.encode() not in (tmp_path / "api.sqlite3").read_bytes()


def test_memory_only_credentials_disappear_after_api_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    headers = {"Origin": "http://localhost:3000"}
    first = create_app(Settings(data_dir=tmp_path, database_path=tmp_path / "first.sqlite3"))
    with TestClient(first, base_url="http://127.0.0.1:8000") as client:
        saved = client.post(
            "/api/providers/gemini/credentials",
            json={"credential": "restart-session-secret"},
            headers=headers,
        )
        assert saved.json()["provider"]["credential"]["source"] == "session"
    second = create_app(Settings(data_dir=tmp_path, database_path=tmp_path / "second.sqlite3"))
    with TestClient(second, base_url="http://127.0.0.1:8000") as client:
        gemini = next(item for item in client.get("/api/providers").json()["items"] if item["provider"] == "gemini")
        assert gemini["credential"] == {"state": "missing", "source": "missing", "required": True}


def test_concurrent_credential_requests_do_not_mix_providers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    app = create_app(app_settings(tmp_path))
    headers = {"Origin": "http://localhost:3000"}
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        def submit(provider: str, secret: str) -> int:
            return client.post(
                f"/api/providers/{provider}/credentials",
                json={"credential": secret},
                headers=headers,
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            anthropic = executor.submit(submit, "anthropic", "anthropic-concurrent-secret")
            gemini = executor.submit(submit, "gemini", "gemini-concurrent-secret")
        assert anthropic.result() == 200
        assert gemini.result() == 200
        runtime = app.state.registry.settings
        assert runtime.secret_for("anthropic") == "anthropic-concurrent-secret"
        assert runtime.secret_for("gemini") == "gemini-concurrent-secret"
        status = client.get("/api/providers").text
        assert "anthropic-concurrent-secret" not in status
        assert "gemini-concurrent-secret" not in status


def test_invalid_provider_configuration_does_not_echo_or_partially_store_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    secret = "exception-secret-must-not-echo"
    app = create_app(app_settings(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        response = client.post(
            "/api/providers/openai-compatible/credentials",
            json={"credential": secret, "base_url": f"https://user:{secret}@provider.example/v1"},
            headers={"Origin": "http://localhost:3000"},
        )
        assert response.status_code == 422
        assert secret not in response.text
        provider = next(item for item in client.get("/api/providers").json()["items"] if item["provider"] == "openai-compatible")
        assert provider["credential"]["source"] == "missing"


def test_provider_control_api_requires_loopback_host_and_dashboard_origin(tmp_path: Path) -> None:
    secret = "must-not-echo"
    app = create_app(app_settings(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        bad_origin = client.post(
            "/api/providers/anthropic/credentials",
            json={"credential": secret},
            headers={"Origin": "https://attacker.example"},
        )
        assert bad_origin.status_code == 403
        assert bad_origin.headers["cache-control"] == "no-store"
        assert secret not in bad_origin.text
    second_app = create_app(Settings(data_dir=tmp_path, database_path=tmp_path / "host.sqlite3"))
    with TestClient(second_app, base_url="http://testserver") as client:
        bad_host = client.post(
            "/api/providers/anthropic/credentials",
            json={"credential": secret},
            headers={"Origin": "http://localhost:3000"},
        )
        assert bad_host.status_code == 403
        assert secret not in bad_host.text


def test_dashboard_origin_aliases_are_exact_and_cors_has_no_wildcard(tmp_path: Path) -> None:
    assert dashboard_origins("http://localhost:3000") == (
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    )
    assert dashboard_origins("http://localhost:4317") == (
        "http://127.0.0.1:4317",
        "http://localhost:4317",
    )
    app = create_app(app_settings(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        for origin in dashboard_origins("http://localhost:3000"):
            preflight = client.options(
                "/api/providers/anthropic/credentials",
                headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
            )
            assert preflight.status_code == 200
            assert preflight.headers["access-control-allow-origin"] == origin
            assert preflight.headers["access-control-allow-origin"] != "*"
        rejected = client.options(
            "/api/providers/anthropic/credentials",
            headers={"Origin": "https://attacker.example", "Access-Control-Request-Method": "POST"},
        )
        assert "access-control-allow-origin" not in rejected.headers


def test_api_scripted_run_score_export_and_comparison(tmp_path: Path) -> None:
    app = create_app(app_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post("/api/evaluations", json={"provider": "scripted", "model": "scripted-valid"})
        assert response.status_code == 202
        batch_id = response.json()["batch_id"]
        deadline = time.monotonic() + 20
        batch = {}
        while time.monotonic() < deadline:
            batch = client.get(f"/api/evaluations/{batch_id}").json()
            if batch.get("status") in {"completed", "completed_with_errors"}:
                break
            time.sleep(0.05)
        assert batch["status"] == "completed"
        run_id = batch["runs"][0]["run_id"]
        run = client.get(f"/api/runs/{run_id}").json()
        assert run["authoritative_reward"] == 1.0
        listed = client.get("/api/runs", params={"limit": 1}).json()
        assert listed["total"] == 1
        assert listed["limit"] == 1
        assert listed["offset"] == 0
        assert listed["items"][0]["run_id"] == run_id
        assert listed["items"][0]["status"] == "completed"
        assert "authenticated_timeline" not in listed["items"][0]
        assert client.get("/api/runs", params={"limit": 0}).status_code == 422
        exported = client.get(f"/api/exports/{batch_id}.json")
        assert exported.status_code == 200
        text = exported.text
        assert "auth_tag" not in text and "H-" not in text and "member_selector" not in text
        comparison = client.get("/api/comparisons", params={"batch": batch_id}).json()
        assert comparison["groups"][0]["strict_success_rate"] == 1.0


def test_api_errors_have_no_traceback_or_local_path(tmp_path: Path) -> None:
    app = create_app(app_settings(tmp_path))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/runs/not-found")
        assert response.status_code == 404
        text = response.text
        assert "Traceback" not in text
        assert str(tmp_path) not in text


def test_comparison_warns_on_incompatible_batches(tmp_path: Path) -> None:
    store = EvaluationStore(tmp_path / "comparison.sqlite3")
    orchestrator = EvaluationOrchestrator(store)
    one = orchestrator.create(EvaluationCreate(provider="scripted", model="scripted-valid", seed_start=0), start_background=False)
    two = orchestrator.create(EvaluationCreate(provider="scripted", model="scripted-valid", seed_start=3, limits={"max_steps": 32}), start_background=False)
    from evaluation_service.comparison import compare_batches
    result = compare_batches(store, [one, two])
    assert result["fair_comparison"] is False
    assert any("seed set" in warning for warning in result["compatibility_warnings"])
    assert any("maximum steps" in warning for warning in result["compatibility_warnings"])
    store.close()


def test_model_runner_has_no_privileged_imports() -> None:
    root = Path(__file__).resolve().parents[2] / "src"
    runner_text = (root / "evaluation_service" / "runner.py").read_text(encoding="utf-8")
    model_text = "\n".join(path.read_text(encoding="utf-8") for path in (root / "model_runners").glob("*.py"))
    for forbidden in ("strict_verifier", "event_service_substrate", "sqlite3", "subprocess", "training_ground.authority"):
        assert forbidden not in runner_text
        assert forbidden not in model_text


def test_cli_provider_status_never_prints_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from model_eval.cli import main

    secret = "cli-secret-value"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    assert main(["--database", str(tmp_path / "cli.sqlite3"), "providers"]) == 0
    output = capsys.readouterr().out
    assert '"configured": true' in output
    assert secret not in output
