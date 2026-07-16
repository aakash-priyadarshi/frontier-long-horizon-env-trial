"""Real model-driven episode loop over the existing twelve-tool environment."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from model_runners.errors import ModelRunnerError, ProviderTimeout
from model_runners.configuration import custom_headers_for
from model_runners.protocol import ModelAdapter, ModelMessage, ModelRequestConfig, ModelResponse, ModelTool
from training_adapters.protocol import ALLOWED_TOOLS
from training_ground.loader import load_environment

from .candidate_artifacts import build_candidate_diff
from .sanitization import public_verifier_result, sanitize_arguments, sanitize_public
from .schemas import EvaluationCreate, utc_now
from .tool_use_debug import analyze_tool_use, model_turn_debug_entry


PROMPT_VERSION = "frontier-incident-agent-v2.7"
SYSTEM_PROMPT = """You are responding to an operational software incident.

Public incident ticket: After a mitigation reduced delivery retries, request alias Q-41 still produced two settlement records. The public canary is green once, but the incident remains open because the mitigation also dropped a recovery attempt. Restore safe operation and resolve the duplicate without disabling settlement delivery or retry support.

Use only the twelve tools supplied with this request. You are in a multi-turn tool loop, so incorporate each tool result and advance the investigation or repair. Start with release.status and investigate public evidence for alias Q-41. Bounded workspace files are service/contract.md, service/flow.py, service/store.py, service/runtime.py, and service/settings.toml. service/contract.md defines required behavior, service/flow.py identifies the intended candidate repair surface, service/store.py is a protocol reference rather than runtime implementation, and service/settings.toml controls delivery configuration. Read only the files needed for evidence, then make a general candidate repair consistent with the public contract. workspace.read reads the active workspace. workspace.edit is a full-file candidate replacement, not a patch, so preserve every required function and unchanged behavior. release.deploy activates candidate changes.

Pause intake before runtime.run, recovery.restore, release.rollback, release.deploy, or recovery.resume. A successful restore, rollback, or deploy invalidates earlier trace handles; use a fresh handle returned by a later telemetry.logs or runtime.run result. After a candidate deployment, run public workloads P1, P2, and P3 before recovery.resume. Do not repeat an unchanged successful read-only call: its result is already in the conversation. If a tool returns an error, use that public error to correct the next call rather than repeating the same invalid action.

Diagnostic handle contract: telemetry.logs returns a trace-only handle; pass it to telemetry.trace, not state.inspect. For journal/effects/keys inspection, run a paused diagnostic using the exact pair diag-s2 + s2.exit or diag-s5 + s5.exit. Its runtime.run result contains a state-capable handle. Pass that handle to telemetry.trace, then use a concrete selector returned by that trace with state.inspect. source='public' supports only progress and recovery views.

For recovery.restore, omit snapshot_id to use the default authenticated snapshot S0; roots.snapshot is integrity evidence, not a snapshot identifier. Hidden tests exist, so preserve unrelated behavior and exercise the public workloads. Respect every action, token, cost, and time budget. Finish by restoring service through the supported recovery and release workflow."""


def public_tools() -> list[ModelTool]:
    string = {"type": "string"}
    schemas: dict[str, tuple[str, dict[str, Any]]] = {
        "release.status": ("Read public release, workspace, and runtime status.", {"type": "object", "properties": {}, "additionalProperties": False}),
        "workspace.read": ("Read one file from the bounded workspace. Read active files for evidence; edit only the candidate workspace.", {"type": "object", "properties": {"path": string}, "required": ["path"], "additionalProperties": False}),
        "workspace.edit": ("Replace one complete file in the bounded candidate workspace. This is not a patch: content must include all required unchanged definitions. Changes are activated only after release.deploy.", {"type": "object", "properties": {"path": string, "content": string}, "required": ["path", "content"], "additionalProperties": False}),
        "telemetry.logs": ("Read bounded public incident logs and return a trace-only correlation handle.", {"type": "object", "properties": {"alias": {"type": "string", "description": "Incident request alias from public logs. For the seeded incident use 'Q-41'. Do not pass release.status field names such as public_canary or incident."}, "window": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2, "description": "Optional inclusive tick window [start, end]; omit on the first call."}}, "required": ["alias"], "additionalProperties": False}),
        "telemetry.trace": ("Read a bounded trace using a public runtime handle.", {"type": "object", "properties": {"handle": {"type": "string", "description": "Correlation handle returned by telemetry.logs or runtime.run. A telemetry.logs handle authorizes only this telemetry.trace call; a diagnostic runtime.run handle can also authorize state.inspect views."}}, "required": ["handle"], "additionalProperties": False}),
        "state.inspect": ("Inspect one bounded public or runtime-authorized state view.", {"type": "object", "properties": {"source": {"type": "string", "description": "Use 'public' only for progress/recovery. For journal/effects/keys use the handle from a diagnostic runtime.run result; a telemetry.logs handle is trace-only and is not valid here. Never use an integrity digest or root from release.status."}, "selector": {"type": "object", "description": "Concrete selector for the requested view. Use {'event_id': ...} for journal/effects, {'command_key': ..., 'occurrence_id': ...} for keys, {'stream': 'settlement'} for public progress, or {'snapshot_id': 'S0'} for public recovery. Diagnostic selectors are returned by telemetry.trace."}, "view": {"type": "string", "enum": ["journal", "effects", "keys", "progress", "recovery"]}}, "required": ["source", "selector", "view"], "additionalProperties": False}),
        "runtime.run": ("Run a named public workload or exact diagnostic cutpoint while intake is paused.", {"type": "object", "properties": {"workload_id": {"type": "string", "enum": ["P1", "P2", "P3", "diag-s2", "diag-s5"], "description": "Use P1/P2/P3 without cutpoint, diag-s2 with s2.exit, or diag-s5 with s5.exit."}, "cutpoint": {"type": "string", "enum": ["s2.exit", "s5.exit"], "description": "Required for diagnostics: s2.exit with diag-s2, or s5.exit with diag-s5. Omit for P1/P2/P3."}}, "required": ["workload_id"], "additionalProperties": False}),
        "recovery.pause": ("Pause service intake.", {"type": "object", "properties": {}, "additionalProperties": False}),
        "recovery.restore": ("Restore an authenticated recovery snapshot. Omit snapshot_id to use the default S0; do not pass the roots.snapshot digest.", {"type": "object", "properties": {"snapshot_id": {"type": "string", "description": "Authenticated snapshot identifier, not an integrity root digest. Use S0 or a snapshot_id returned by state.inspect.", "default": "S0"}}, "additionalProperties": False}),
        "release.rollback": ("Activate a known recovery revision.", {"type": "object", "properties": {"revision": {"type": "string", "description": "Known revision identifier. Use 'r0' or 'r1'."}}, "required": ["revision"], "additionalProperties": False}),
        "release.deploy": ("Deploy the bounded candidate workspace. Requires intake to be paused and candidate edits that differ from the active workspace.", {"type": "object", "properties": {}, "additionalProperties": False}),
        "recovery.resume": ("Resume service intake. Only valid after a successful release.deploy and after runtime.run P1, P2, and P3 all pass.", {"type": "object", "properties": {}, "additionalProperties": False}),
    }
    tools = [ModelTool(name, schemas[name][0], schemas[name][1]) for name in ALLOWED_TOOLS]
    if len(tools) != 12 or {tool.name for tool in tools} != set(ALLOWED_TOOLS):
        raise RuntimeError("public model tool inventory diverged from the environment")
    return tools


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), default=str)


_READ_ONLY_TOOLS = frozenset(
    {"release.status", "workspace.read", "telemetry.logs", "telemetry.trace", "state.inspect"}
)


def repeated_read_only_cycle(
    timeline: list[dict[str, Any]], *, max_cycle_length: int = 4
) -> tuple[int, int] | None:
    """Return (cycle length, repeats) for a repeated successful read-only suffix."""

    suffix: list[tuple[str, str, str]] = []
    for entry in reversed(timeline):
        tool = str(entry.get("tool") or "")
        if not entry.get("success") or tool not in _READ_ONLY_TOOLS:
            break
        arguments = entry.get("arguments") if isinstance(entry.get("arguments"), dict) else {}
        suffix.append((tool, _json(arguments), _json(entry.get("result_summary"))))
    suffix.reverse()
    for cycle_length in range(1, min(max_cycle_length, len(suffix) // 2) + 1):
        pattern = suffix[-cycle_length:]
        repeats = 1
        cursor = len(suffix) - cycle_length
        while cursor >= cycle_length and suffix[cursor - cycle_length:cursor] == pattern:
            repeats += 1
            cursor -= cycle_length
        if repeats >= 2:
            return cycle_length, repeats
    return None


def _error_category(exc: BaseException) -> str:
    if isinstance(exc, ModelRunnerError):
        return exc.code
    if isinstance(exc, asyncio.TimeoutError):
        return "wall_clock_timeout"
    return "evaluation_error"


@dataclass
class EpisodeOutcome:
    status: str
    payload: dict[str, Any]
    candidate_artifact: dict[str, Any] | None = None


class EpisodeRunner:
    def __init__(
        self,
        *,
        adapter: ModelAdapter,
        request: EvaluationCreate,
        seed: int,
        attempt: int,
        environment_commit: str,
        application_commit: str,
        cancelled: asyncio.Event,
        emit: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> None:
        self.adapter = adapter
        self.request = request
        self.seed = seed
        self.attempt = attempt
        self.environment_commit = environment_commit
        self.application_commit = application_commit
        self.cancelled = cancelled
        self.emit = emit

    async def _complete_with_retry(self, messages: list[ModelMessage], config: ModelRequestConfig) -> ModelResponse:
        last_error: ModelRunnerError | None = None
        for retry in range(config.max_retries + 1):
            if self.cancelled.is_set():
                raise asyncio.CancelledError
            try:
                return await asyncio.wait_for(
                    self.adapter.complete(messages=messages, tools=public_tools(), config=config),
                    timeout=config.timeout_seconds,
                )
            except asyncio.TimeoutError:
                last_error = ProviderTimeout()
            except ModelRunnerError as exc:
                last_error = exc
                if not exc.retryable:
                    raise
            if retry < config.max_retries:
                await self.emit("provider_retry", {"retry": retry + 1, "error_category": last_error.code})
                await asyncio.sleep(min(0.25 * (2**retry), 2.0))
        assert last_error is not None
        raise last_error

    async def _complete_with_limits(
        self,
        messages: list[ModelMessage],
        config: ModelRequestConfig,
        remaining_wall_seconds: float | None,
    ) -> ModelResponse:
        provider_task = asyncio.create_task(self._complete_with_retry(messages, config))
        cancellation_task = asyncio.create_task(self.cancelled.wait())
        try:
            done, _ = await asyncio.wait(
                {provider_task, cancellation_task},
                timeout=remaining_wall_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancellation_task in done and cancellation_task.result():
                provider_task.cancel()
                raise asyncio.CancelledError
            if provider_task in done:
                return provider_task.result()
            provider_task.cancel()
            raise asyncio.TimeoutError
        finally:
            cancellation_task.cancel()
            await asyncio.gather(provider_task, cancellation_task, return_exceptions=True)

    async def run(self) -> EpisodeOutcome:
        started_at = utc_now()
        monotonic_start = time.perf_counter()
        timeline: list[dict[str, Any]] = []
        model_turn_debug: list[dict[str, Any]] = []
        runner_guidance: list[dict[str, Any]] = []
        repetitive_cycle_warning_sent = False
        model_calls = 0
        input_tokens = output_tokens = cached_tokens = reasoning_tokens = 0
        provider_latency_ms = 0.0
        estimated_cost: float | None = None
        termination_reason = "model_stopped"
        env = load_environment(
            split=self.request.split,
            seed=self.seed,
            options={"max_steps": self.request.limits.max_steps},
        )

        def retained_candidate() -> dict[str, Any] | None:
            try:
                initial_workspace, candidate_workspace = env.candidate_workspace_pair()
                return build_candidate_diff(initial_workspace, candidate_workspace)
            except Exception:
                return None

        config = ModelRequestConfig(
            model=self.request.model,
            temperature=self.request.model_configuration.temperature,
            max_output_tokens=self.request.model_configuration.max_output_tokens,
            context_window=self.request.model_configuration.context_window,
            reasoning_effort=self.request.model_configuration.reasoning_effort,
            timeout_seconds=self.request.model_configuration.timeout_seconds,
            max_retries=self.request.model_configuration.max_retries,
            deterministic=self.request.model_configuration.deterministic,
            input_token_price_per_million=self.request.model_configuration.input_token_price_per_million,
            output_token_price_per_million=self.request.model_configuration.output_token_price_per_million,
            custom_headers=custom_headers_for(self.request.provider),
        )
        base_payload: dict[str, Any] = {
            "export_version": "2.0.0",
            "split": self.request.split,
            "seed": self.seed,
            "attempt": self.attempt,
            "provider": self.request.provider,
            "model": self.request.model,
            "model_configuration": self.request.model_configuration.model_dump(mode="json"),
            "limits": self.request.limits.model_dump(mode="json"),
            "prompt_version": PROMPT_VERSION,
            "environment_commit": self.environment_commit,
            "application_commit": self.application_commit,
            "started_at": started_at,
        }
        try:
            observation, info = env.reset(seed=self.seed)
            manifest = sanitize_public(info.get("manifest") or {})
            instance_id = str(info.get("instance_id") or manifest.get("public_instance_id") or "")
            base_payload.update({"instance_id": instance_id, "public_manifest_id": instance_id, "public_manifest": manifest})
            inventory = tuple(info.get("allowed_tools") or ())
            if len(inventory) != 12 or set(inventory) != set(ALLOWED_TOOLS):
                raise RuntimeError("environment did not expose the exact twelve-tool inventory")
            messages = [
                ModelMessage("system", SYSTEM_PROMPT),
                ModelMessage(
                    "user",
                    "Public task manifest:\n"
                    + _json(manifest)
                    + "\nInitial public observation:\n"
                    + _json(sanitize_public(observation))
                    + "\nBegin now by calling release.status. Your next response must be a native tool call, not prose.",
                ),
            ]
            await self.emit("run_started", {"instance_id": instance_id, "seed": self.seed, "attempt": self.attempt})
            ended = False
            while not ended:
                if self.cancelled.is_set():
                    raise asyncio.CancelledError
                elapsed = time.perf_counter() - monotonic_start
                if self.request.limits.wall_clock_seconds is not None and elapsed >= self.request.limits.wall_clock_seconds:
                    termination_reason = "wall_clock_budget"
                    break
                if model_calls >= self.request.limits.max_model_calls:
                    termination_reason = "model_call_budget"
                    break
                remaining_wall = None
                if self.request.limits.wall_clock_seconds is not None:
                    remaining_wall = max(
                        0.0,
                        self.request.limits.wall_clock_seconds
                        - (time.perf_counter() - monotonic_start),
                    )
                try:
                    response = await self._complete_with_limits(messages, config, remaining_wall)
                except asyncio.TimeoutError:
                    termination_reason = "wall_clock_budget"
                    break
                model_calls += 1
                turn_debug = model_turn_debug_entry(response, turn=model_calls)
                model_turn_debug.append(turn_debug)
                input_tokens += response.input_tokens
                output_tokens += response.output_tokens
                cached_tokens += response.cached_tokens
                reasoning_tokens += response.reasoning_tokens
                provider_latency_ms += response.latency_ms
                if response.estimated_cost is not None:
                    estimated_cost = (estimated_cost or 0.0) + response.estimated_cost
                await self.emit("model_response", {
                    "model_calls": model_calls, "input_tokens": input_tokens, "output_tokens": output_tokens,
                    "estimated_cost": estimated_cost, "tool_call_count": len(response.tool_calls),
                    "finish_reason": response.finish_reason,
                    "reasoning_tokens": response.reasoning_tokens,
                    "dropped_tool_calls": turn_debug["dropped_tool_calls"],
                    "tool_names": turn_debug["tool_names"],
                })
                budget_reason = None
                if self.request.limits.input_token_budget is not None and input_tokens > self.request.limits.input_token_budget:
                    budget_reason = "input_token_budget"
                if self.request.limits.output_token_budget is not None and output_tokens > self.request.limits.output_token_budget:
                    budget_reason = "output_token_budget"
                if self.request.limits.cost_budget is not None and estimated_cost is not None and estimated_cost > self.request.limits.cost_budget:
                    budget_reason = "cost_budget"
                if budget_reason:
                    termination_reason = budget_reason
                    break
                messages.append(
                    ModelMessage(
                        "assistant",
                        response.text,
                        tool_calls=response.tool_calls,
                        reasoning=response.reasoning,
                    )
                )
                if not response.tool_calls:
                    termination_reason = "model_stopped_without_tool_call" if not timeline else "model_stopped"
                    break
                for call in response.tool_calls[:4]:
                    if self.cancelled.is_set():
                        raise asyncio.CancelledError
                    if call.name not in ALLOWED_TOOLS:
                        raise ModelRunnerError("model requested an unknown tool", code="unknown_tool", retryable=False)
                    step_started = time.perf_counter()
                    observation, reward, terminated, truncated, step_info = env.step({"tool": call.name, "arguments": call.arguments})
                    duration_ms = (time.perf_counter() - step_started) * 1000
                    transcript_steps = [entry for entry in env.transcript() if entry.get("kind") == "step"]
                    authenticated = transcript_steps[-1] if transcript_steps else {}
                    # The model needs ephemeral public capability handles to
                    # continue telemetry.trace/state.inspect. Persist only the
                    # sanitized summary; keep the richer result in memory for
                    # this provider conversation and never emit or export it.
                    model_result = step_info.get("response")
                    response_summary = sanitize_public(model_result)
                    timeline_entry = {
                        "sequence": len(timeline) + 1,
                        "fake_tick": sanitize_public(observation).get("tick") if isinstance(observation, dict) else None,
                        "tool": call.name,
                        "arguments": sanitize_arguments(call.name, call.arguments),
                        "result_summary": response_summary,
                        "request_bytes": int(authenticated.get("request_bytes") or 0),
                        "response_bytes": int(authenticated.get("response_bytes") or 0),
                        "duration_ms": round(duration_ms, 3),
                        "success": authenticated.get("success_error_code") == "ok",
                        "error_code": None if authenticated.get("success_error_code") == "ok" else authenticated.get("success_error_code"),
                        "terminated": bool(terminated), "truncated": bool(truncated),
                        "reward": reward if terminated else None,
                    }
                    timeline.append(timeline_entry)
                    messages.append(ModelMessage(
                        "tool",
                        _json({"observation": sanitize_public(observation), "result": model_result}),
                        tool_call_id=call.id,
                        name=call.name,
                    ))
                    await self.emit("tool_completed", {
                        "sequence": len(timeline), "current_step": len(timeline), "current_tool": call.name,
                        "input_tokens": input_tokens, "output_tokens": output_tokens, "estimated_cost": estimated_cost,
                        "terminated": terminated, "truncated": truncated,
                        "timeline_entry": timeline_entry,
                    })
                    repeated_cycle = repeated_read_only_cycle(timeline)
                    if repeated_cycle and not ended:
                        cycle_length, repeats = repeated_cycle
                        if repetitive_cycle_warning_sent:
                            termination_reason = "model_repetitive_tool_loop"
                            runner_guidance.append({
                                "code": "repeated_read_only_cycle_terminated",
                                "after_sequence": len(timeline),
                                "cycle_length": cycle_length,
                                "repeats": repeats,
                            })
                            ended = True
                        else:
                            repetitive_cycle_warning_sent = True
                            messages.append(ModelMessage(
                                "system",
                                "Progress guard: the same successful read-only tool sequence has repeated. "
                                "Those results are already in context. Do not repeat those calls unless a "
                                "state-changing action makes them stale; choose a new valid action that advances "
                                "investigation, candidate repair, deployment, verification, or recovery.",
                            ))
                            runner_guidance.append({
                                "code": "repeated_read_only_cycle_warning",
                                "after_sequence": len(timeline),
                                "cycle_length": cycle_length,
                                "repeats": repeats,
                            })
                            await self.emit("runner_guidance", runner_guidance[-1])
                    if terminated:
                        termination_reason = "environment_terminated"
                        ended = True
                    elif truncated:
                        termination_reason = str(observation.get("truncated_reason") or "environment_truncated")
                        ended = True
                    if ended:
                        break
            grade = env.grade()
            authoritative = public_verifier_result(grade)
            public_transcript = timeline
            candidate_artifact = retained_candidate()
            changed_paths = candidate_artifact["changed_paths"] if candidate_artifact else []
            payload = {
                **base_payload, **authoritative,
                "termination_reason": termination_reason,
                "truncation_reason": termination_reason if "budget" in termination_reason or "truncated" in termination_reason else None,
                "action_count": len(timeline), "model_call_count": model_calls,
                "distinct_tools": sorted({entry["tool"] for entry in timeline}),
                "input_tokens": input_tokens, "output_tokens": output_tokens, "cached_tokens": cached_tokens,
                "reasoning_tokens": reasoning_tokens, "provider_latency_ms": round(provider_latency_ms, 3),
                "elapsed_ms": round((time.perf_counter() - monotonic_start) * 1000, 3),
                "estimated_cost": round(estimated_cost, 8) if estimated_cost is not None else None,
                "authenticated_timeline": public_transcript,
                "model_turn_debug": model_turn_debug,
                "runner_guidance": runner_guidance,
                "candidate_diff_summary": {"changed_paths": changed_paths, "file_count": len(changed_paths)},
                "error_category": None,
                "ended_at": utc_now(),
            }
            payload["tool_use_debug"] = analyze_tool_use(payload)
            await self.emit("run_scored", {"authoritative_reward": payload["authoritative_reward"], "authoritative_verdict": payload["authoritative_verdict"]})
            return EpisodeOutcome("completed", payload, candidate_artifact)
        except asyncio.CancelledError:
            try:
                authoritative = public_verifier_result(env.grade())
            except Exception:
                authoritative = {}
            payload = {
                **base_payload, **authoritative, "termination_reason": "cancelled", "error_category": "cancelled",
                "action_count": len(timeline), "model_call_count": model_calls, "authenticated_timeline": timeline,
                "model_turn_debug": model_turn_debug, "runner_guidance": runner_guidance, "ended_at": utc_now(),
            }
            payload["tool_use_debug"] = analyze_tool_use(payload)
            candidate_artifact = retained_candidate()
            return EpisodeOutcome("cancelled", payload, candidate_artifact)
        except Exception as exc:
            try:
                authoritative = public_verifier_result(env.grade())
            except Exception:
                authoritative = {}
            payload = {
                **base_payload, **authoritative, "termination_reason": "provider_or_runner_failure",
                "error_category": _error_category(exc), "error_message": sanitize_public(str(exc)),
                "action_count": len(timeline), "model_call_count": model_calls, "authenticated_timeline": timeline,
                "model_turn_debug": model_turn_debug, "runner_guidance": runner_guidance,
                "input_tokens": input_tokens, "output_tokens": output_tokens, "cached_tokens": cached_tokens,
                "reasoning_tokens": reasoning_tokens, "estimated_cost": estimated_cost, "ended_at": utc_now(),
            }
            payload["tool_use_debug"] = analyze_tool_use(payload)
            candidate_artifact = retained_candidate()
            return EpisodeOutcome("failed", payload, candidate_artifact)
        finally:
            env.close()
