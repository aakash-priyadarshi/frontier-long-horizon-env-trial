"""Tests for post-hoc tool-use root-cause analysis."""

from __future__ import annotations

from evaluation_service.tool_use_debug import analyze_tool_use, model_turn_debug_entry
from model_runners.protocol import ModelResponse, ModelToolCall


def _entry(sequence: int, tool: str, *, success: bool, message: str | None = None, arguments: dict | None = None) -> dict:
    result = {"ok": True} if success else {"error": {"code": "tool_error", "message": message or "tool failed"}}
    return {
        "sequence": sequence,
        "tool": tool,
        "arguments": arguments or {},
        "result_summary": result,
        "success": success,
        "error_code": None if success else "tool_error",
        "request_bytes": 10,
        "response_bytes": 20,
        "duration_ms": 1,
        "terminated": False,
        "truncated": False,
    }


def test_qwen_style_precondition_cascade_is_workflow_misuse_not_protocol_failure():
    run = {
        "provider": "ollama",
        "model": "qwen3:8b",
        "termination_reason": "model_stopped",
        "model_call_count": 6,
        "reasoning_tokens": 0,
        "error_category": None,
        "authenticated_timeline": [
            _entry(1, "recovery.restore", success=False, message="recovery.restore: tool_error: intake must be paused"),
            _entry(2, "recovery.pause", success=True),
            _entry(3, "recovery.restore", success=True),
            _entry(4, "recovery.resume", success=False, message="recovery.resume: tool_error: resume requires a deployed candidate"),
            _entry(5, "release.deploy", success=False, message="release.deploy: tool_error: no candidate changes to deploy"),
        ],
    }
    report = analyze_tool_use(run)
    assert report["protocol_health"]["tool_calling_appears_functional"] is True
    assert report["primary_cause"]["code"] == "precondition_intake_not_paused"
    codes = {finding["code"] for finding in report["findings"]}
    assert "precondition_resume_without_deploy" in codes
    assert "precondition_deploy_without_edits" in codes
    assert "skipped_investigation" in codes
    assert "skipped_candidate_edits" in codes
    assert "incomplete_repair_sequence" in codes
    assert "workflow misuse" in report["summary"].lower() or "preconditions" in report["summary"].lower()
    phases = {phase["id"]: phase["status"] for phase in report["workflow_phases"]}
    assert phases["pause"] == "present"
    assert phases["recover"] == "present"
    assert phases["edit"] == "missing"
    assert phases["deploy"] == "attempted"
    assert phases["verify"] == "missing"


def test_diagnostic_alias_and_digest_confusion_plus_resume_loop():
    digest = "18cdc2bec20acd2e13af29111e23679ec53970cbd0c4c260a8a3a373e0f078df"
    run = {
        "provider": "ollama",
        "model": "qwen3:8b",
        "termination_reason": "model_stopped",
        "model_call_count": 8,
        "reasoning_tokens": 0,
        "error_category": None,
        "authenticated_timeline": [
            _entry(1, "recovery.pause", success=True),
            _entry(
                2,
                "telemetry.logs",
                success=False,
                message="telemetry.logs: tool_error: no valid trace handle for the requested alias and window",
                arguments={"alias": "public_canary", "window": [44, 45]},
            ),
            _entry(
                3,
                "state.inspect",
                success=False,
                message="state.inspect: invalid arguments",
                arguments={"source": digest, "view": "recovery"},
            ),
            _entry(
                4,
                "state.inspect",
                success=False,
                message="state.inspect: invalid_trace_capability: invalid trace capability",
                arguments={"selector": {}, "source": digest, "view": "recovery"},
            ),
            _entry(5, "recovery.resume", success=False, message="recovery.resume: tool_error: resume requires a deployed candidate"),
            _entry(6, "recovery.resume", success=False, message="recovery.resume: tool_error: resume requires a deployed candidate"),
            _entry(7, "recovery.resume", success=False, message="recovery.resume: tool_error: resume requires a deployed candidate"),
        ],
    }
    report = analyze_tool_use(run)
    codes = {finding["code"] for finding in report["findings"]}
    assert report["protocol_health"]["tool_calling_appears_functional"] is True
    assert report["primary_cause"]["code"] == "diagnostic_status_field_as_log_alias"
    assert "diagnostic_digest_as_trace_source" in codes
    assert "diagnostic_empty_or_missing_selector" in codes or "diagnostic_digest_as_trace_source" in codes
    assert "precondition_resume_without_deploy" in codes
    assert "repeated_identical_failure" in codes
    assert "investigation_attempted_but_failed" in codes
    assert "skipped_candidate_edits" in codes
    assert "guessing aliases" in report["summary"].lower() or "invalid public identifiers" in report["summary"].lower()
    assert report["coverage"]["diagnostics"] == 3
    assert report["coverage"]["workspace"] == 0


def test_malformed_protocol_failure_outranks_workflow_warnings():
    run = {
        "termination_reason": "provider_or_runner_failure",
        "error_category": "malformed_model_response",
        "error_message": "tool call is missing a function name",
        "model_call_count": 1,
        "reasoning_tokens": 1200,
        "authenticated_timeline": [],
    }
    report = analyze_tool_use(run)
    assert report["protocol_health"]["tool_calling_appears_functional"] is False
    assert report["primary_cause"]["code"] == "malformed_model_response"
    assert "protocol" in report["summary"].lower()


def test_model_stopped_without_tool_call_is_flagged():
    run = {
        "termination_reason": "model_stopped_without_tool_call",
        "model_call_count": 1,
        "reasoning_tokens": 4000,
        "authenticated_timeline": [],
        "model_turn_debug": [
            {
                "turn": 1,
                "finish_reason": "length",
                "tool_call_count": 0,
                "tool_names": [],
                "dropped_tool_calls": 0,
                "has_text": False,
                "text_chars": 0,
                "input_tokens": 100,
                "output_tokens": 4096,
                "reasoning_tokens": 4000,
                "latency_ms": 12,
            }
        ],
    }
    report = analyze_tool_use(run)
    assert report["primary_cause"]["code"] == "no_tool_calls"
    assert "thinking" in report["primary_cause"]["detail"].lower() or "reasoning" in report["primary_cause"]["detail"].lower()


def test_repeated_read_cycle_is_primary_and_phase_coverage_requires_actual_progress():
    reads = []
    paths = ["service/flow.py", "service/settings.toml", "service/contract.md"] * 3
    for sequence, path in enumerate(paths, start=1):
        reads.append(_entry(sequence, "workspace.read", success=True, arguments={"path": path}))
        reads[-1]["result_summary"] = f"content for {path}"
    run = {
        "termination_reason": "environment_truncated",
        "model_call_count": len(reads),
        "authenticated_timeline": reads,
    }
    report = analyze_tool_use(run)
    assert report["primary_cause"]["code"] == "model_repetitive_tool_loop"
    phases = {phase["id"]: phase["status"] for phase in report["workflow_phases"]}
    assert phases["edit"] == "attempted"
    assert phases["resume"] == "missing"
    assert "skipped_candidate_edits" in {finding["code"] for finding in report["findings"]}


def test_model_turn_debug_entry_is_compact_and_safe():
    response = ModelResponse(
        text="thinking out loud",
        reasoning="private chain state",
        tool_calls=(
            ModelToolCall(id="1", name="recovery.pause", arguments={}),
            ModelToolCall(id="2", name="recovery.restore", arguments={}),
            ModelToolCall(id="3", name="workspace.edit", arguments={"path": "a", "content": "x"}),
            ModelToolCall(id="4", name="release.deploy", arguments={}),
            ModelToolCall(id="5", name="runtime.run", arguments={"workload_id": "P1"}),
        ),
        finish_reason="tool_calls",
        input_tokens=10,
        output_tokens=20,
        reasoning_tokens=3,
        latency_ms=12.3456,
    )
    entry = model_turn_debug_entry(response, turn=2)
    assert entry == {
        "turn": 2,
        "finish_reason": "tool_calls",
        "tool_call_count": 5,
        "tool_names": ["recovery.pause", "recovery.restore", "workspace.edit", "release.deploy", "runtime.run"],
        "dropped_tool_calls": 1,
        "has_text": True,
        "text_chars": len("thinking out loud"),
        "has_reasoning": True,
        "reasoning_chars": len("private chain state"),
        "input_tokens": 10,
        "output_tokens": 20,
        "reasoning_tokens": 3,
        "latency_ms": 12.346,
    }
    # Never embed model prose content in the public record.
    assert "thinking out loud" not in str(entry)
    assert "private chain state" not in str(entry)
