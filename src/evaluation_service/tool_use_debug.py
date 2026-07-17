"""Post-hoc tool-use root-cause analysis for episode inspection.

Derives structured findings from the authenticated timeline and run metadata.
Does not re-score the episode or invent rewards — it only explains why tool
calls failed or why the repair workflow stalled.
"""

from __future__ import annotations

from typing import Any


EXPECTED_PHASES = (
    {
        "id": "investigate",
        "title": "Investigate public evidence",
        "tools": ("release.status", "telemetry.logs", "telemetry.trace", "state.inspect", "runtime.run"),
        "detail": "Read status/logs/traces and optionally run diagnostic cutpoints before editing.",
    },
    {
        "id": "pause",
        "title": "Pause intake",
        "tools": ("recovery.pause",),
        "detail": "recovery.pause must succeed before restore, rollback, deploy, or resume.",
    },
    {
        "id": "recover",
        "title": "Authenticated recovery",
        "tools": ("recovery.restore", "release.rollback"),
        "detail": "Restore snapshot S0 (and optionally rollback to r0/r1) while intake is paused.",
    },
    {
        "id": "edit",
        "title": "Candidate repair",
        "tools": ("workspace.read", "workspace.edit"),
        "detail": "Read and edit candidate files so release.deploy has real changes.",
    },
    {
        "id": "deploy",
        "title": "Deploy candidate",
        "tools": ("release.deploy",),
        "detail": "Activate the edited candidate workspace.",
    },
    {
        "id": "verify",
        "title": "Public verification",
        "tools": ("runtime.run",),
        "detail": "Pass P1, P2, and P3 on the deployed candidate before resume.",
    },
    {
        "id": "resume",
        "title": "Resume service",
        "tools": ("recovery.resume",),
        "detail": "Resume intake only after deploy + public workloads pass.",
    },
)

# Error substring → structured classification. Order matters: first match wins.
_ERROR_PATTERNS: tuple[tuple[str, str, str, str], ...] = (
    (
        "intake must be paused",
        "precondition_intake_not_paused",
        "Called a gated recovery/release tool while intake was still open",
        "Call recovery.pause first, then retry restore/rollback/deploy/resume.",
    ),
    (
        "resume requires a deployed candidate",
        "precondition_resume_without_deploy",
        "recovery.resume ran before a successful release.deploy",
        "Edit the candidate, release.deploy it, pass P1/P2/P3, then resume.",
    ),
    (
        "no candidate changes to deploy",
        "precondition_deploy_without_edits",
        "release.deploy ran with no candidate file changes",
        "workspace.edit at least one candidate file before deploy.",
    ),
    (
        "transient effect exceeded attempt budget",
        "candidate_configuration_failure",
        "Active candidate delivery configuration could not recover the transient effect",
        "Read the public contract and service/settings.toml, correct the candidate configuration, redeploy, and rerun the workload.",
    ),
    (
        "public workloads not passed",
        "precondition_resume_without_public_pass",
        "recovery.resume ran before P1/P2/P3 all passed on the active config",
        "After deploy, runtime.run P1, P2, and P3 successfully, then resume.",
    ),
    (
        "recovery provenance missing",
        "precondition_resume_without_restore",
        "recovery.resume lacked authenticated recovery provenance",
        "Complete recovery.restore (default S0) while paused before resume.",
    ),
    (
        "intake is not open",
        "precondition_pause_when_already_paused",
        "recovery.pause ran while intake was already paused",
        "Skip pause if already paused; continue with restore/edit/deploy.",
    ),
    (
        "unknown revision",
        "invalid_rollback_revision",
        "release.rollback used an unknown revision",
        "Use revision r0 or r1 only.",
    ),
    (
        "no valid trace handle for the requested alias and window",
        "diagnostic_bad_log_alias_or_window",
        "telemetry.logs used an alias/window with no valid trace handle",
        "Use the incident request alias from public logs (typically Q-41). Do not pass status fields like public_canary as the alias. Prefer omitting window, or use a window that covers the alias ticks.",
    ),
    (
        "no public logs for alias",
        "diagnostic_unknown_log_alias",
        "telemetry.logs alias does not appear in public telemetry",
        "Use alias Q-41 from the incident narrative / public log lines, not release.status field names.",
    ),
    (
        "invalid_trace_capability",
        "diagnostic_invalid_trace_capability",
        "state.inspect/telemetry.trace used an invalid or empty capability/selector",
        "A telemetry.logs handle is trace-only. Use it with telemetry.trace. For state.inspect journal/effects/keys, use a diagnostic runtime.run handle and a selector returned by its trace; source='public' supports only progress/recovery.",
    ),
    (
        "invalid trace capability",
        "diagnostic_invalid_trace_capability",
        "state.inspect/telemetry.trace used an invalid or empty capability/selector",
        "A telemetry.logs handle is trace-only. Use it with telemetry.trace. For state.inspect journal/effects/keys, use a diagnostic runtime.run handle and a selector returned by its trace; source='public' supports only progress/recovery.",
    ),
    (
        "selector is empty",
        "diagnostic_empty_selector",
        "state.inspect was called with an empty selector",
        "Pass a concrete selector such as {\"stream\": \"settlement\"} for public recovery/progress views.",
    ),
    (
        "invalid_arguments",
        "invalid_tool_arguments",
        "Tool arguments did not match the public schema",
        "Fix argument names/types from the tool schema and retry.",
    ),
    (
        "invalid arguments",
        "invalid_tool_arguments",
        "Tool arguments did not match the public schema",
        "Fix argument names/types from the tool schema and retry.",
    ),
)


def _tool_error_message(entry: dict[str, Any]) -> str | None:
    if entry.get("success"):
        return None
    summary = entry.get("result_summary")
    if isinstance(summary, dict):
        error = summary.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message:
                return message
        message = summary.get("message")
        if isinstance(message, str) and message:
            return message
    code = entry.get("error_code")
    if isinstance(code, str) and code and code != "ok":
        return code
    return "tool failed"


def _looks_like_digest(value: object) -> bool:
    if not isinstance(value, str):
        return False
    compact = value.strip().lower()
    return len(compact) >= 40 and all(ch in "0123456789abcdef" for ch in compact)


def _classify_error(message: str, *, tool: str | None = None, arguments: dict[str, Any] | None = None) -> tuple[str, str, str]:
    args = arguments or {}
    tool_name = tool or ""

    if tool_name == "runtime.run" and "unknown workload or missing cutpoint" in message.lower():
        return (
            "diagnostic_invalid_workload_or_cutpoint",
            "runtime.run used an incomplete or mismatched diagnostic pair",
            "Use diag-s2 with s2.exit or diag-s5 with s5.exit. Use P1/P2/P3 without a cutpoint.",
        )

    if tool_name == "runtime.run" and (
        "active workspace configuration invalid" in message.lower()
        or "tool_execution_failed" in message.lower()
    ):
        return (
            "candidate_execution_failure",
            "Deployed candidate could not execute the public workload",
            "Review the full-file candidate edit, preserve the required public module interface, redeploy, and rerun the workload.",
        )

    if tool_name == "telemetry.logs":
        alias = args.get("alias")
        if isinstance(alias, str) and alias in {"public_canary", "green_once", "pass", "incident"}:
            return (
                "diagnostic_status_field_as_log_alias",
                "telemetry.logs confused a release.status field for a log alias",
                "public_canary/incident are status fields, not log aliases. Call telemetry.logs with alias Q-41 (omit window initially).",
            )

    if tool_name == "state.inspect":
        source = args.get("source")
        selector = args.get("selector")
        if "trace capability view not allowed" in message.lower():
            return (
                "diagnostic_handle_view_not_allowed",
                "state.inspect used a handle that does not authorize the requested view",
                "telemetry.logs handles authorize telemetry.trace only. Use a diagnostic runtime.run handle for journal/effects/keys, with a selector returned by telemetry.trace.",
            )
        if source == "public" and "public stream not supported for this view" in message.lower():
            return (
                "diagnostic_public_view_not_supported",
                "state.inspect requested a private state view from the public source",
                "source='public' supports only progress with stream=settlement or recovery with snapshot_id=S0. Use a diagnostic runtime.run handle for journal/effects/keys.",
            )
        if _looks_like_digest(source):
            return (
                "diagnostic_digest_as_trace_source",
                "state.inspect used an integrity digest as source",
                "source must be 'public' or a correlation handle from telemetry.logs/runtime.run — never a roots.*/digest hash.",
            )
        if selector == {} or selector is None:
            # Prefer this when the schema/capability failure is selector-related.
            if "invalid" in message.lower() or "selector" in message.lower() or "capability" in message.lower():
                return (
                    "diagnostic_empty_or_missing_selector",
                    "state.inspect missing a usable selector",
                    "Include required selector (for public views, e.g. {\"stream\": \"settlement\"}) and use source 'public' unless you hold a valid trace handle.",
                )

    lowered = message.lower()
    for needle, code, title, remediation in _ERROR_PATTERNS:
        if needle in lowered:
            return code, title, remediation
    if "tool_error" in lowered:
        return "tool_precondition_or_runtime", "Environment tool rejected the call", "Read the error message and satisfy the stated precondition."
    return "tool_failure_unclassified", "Tool call failed", "Inspect the sanitized result and correct the next attempt."


def _failure_signature(entry: dict[str, Any]) -> tuple[Any, ...]:
    message = _tool_error_message(entry) or ""
    args = entry.get("arguments") if isinstance(entry.get("arguments"), dict) else {}
    return (entry.get("tool"), entry.get("error_code"), message, tuple(sorted((k, repr(v)) for k, v in args.items())))


def _repeated_failure_findings(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect stuck loops where the model retries the same failing call unchanged."""
    streaks: list[dict[str, Any]] = []
    current_sig: tuple[Any, ...] | None = None
    start_seq: int | None = None
    count = 0
    tool = None
    message = None
    for entry in timeline:
        if entry.get("success"):
            if count >= 2 and current_sig is not None:
                streaks.append(
                    {
                        "tool": tool,
                        "count": count,
                        "start_sequence": start_seq,
                        "detail": message,
                    }
                )
            current_sig = None
            count = 0
            continue
        sig = _failure_signature(entry)
        if sig == current_sig:
            count += 1
        else:
            if count >= 2 and current_sig is not None:
                streaks.append(
                    {
                        "tool": tool,
                        "count": count,
                        "start_sequence": start_seq,
                        "detail": message,
                    }
                )
            current_sig = sig
            count = 1
            start_seq = entry.get("sequence")
            tool = entry.get("tool")
            message = _tool_error_message(entry)
    if count >= 2 and current_sig is not None:
        streaks.append(
            {
                "tool": tool,
                "count": count,
                "start_sequence": start_seq,
                "detail": message,
            }
        )
    findings: list[dict[str, Any]] = []
    for streak in streaks:
        findings.append(
            {
                "severity": "warning",
                "code": "repeated_identical_failure",
                "title": f"Retried {streak['tool']} {streak['count']} times without changing strategy",
                "detail": str(streak["detail"] or "identical failing call repeated"),
                "remediation": "After a tool_error, change arguments or switch to the next required workflow step instead of repeating the same call.",
                "sequence": streak["start_sequence"],
                "tool": streak["tool"],
            }
        )
    return findings


_READ_ONLY_TOOLS = frozenset(
    {"release.status", "workspace.read", "telemetry.logs", "telemetry.trace", "state.inspect"}
)


def _repeated_read_only_cycle_finding(timeline: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Detect a repeated successful read-only suffix, including multi-call cycles."""

    suffix: list[tuple[str, str, str, int | None]] = []
    for entry in reversed(timeline):
        tool = str(entry.get("tool") or "")
        if not entry.get("success") or tool not in _READ_ONLY_TOOLS:
            break
        args = entry.get("arguments") if isinstance(entry.get("arguments"), dict) else {}
        suffix.append((tool, repr(sorted(args.items())), repr(entry.get("result_summary")), entry.get("sequence")))
    suffix.reverse()
    for cycle_length in range(1, min(4, len(suffix) // 2) + 1):
        pattern = [(tool, args, result) for tool, args, result, _ in suffix[-cycle_length:]]
        repeats = 1
        cursor = len(suffix) - cycle_length
        while cursor >= cycle_length:
            prior = [(tool, args, result) for tool, args, result, _ in suffix[cursor - cycle_length:cursor]]
            if prior != pattern:
                break
            repeats += 1
            cursor -= cycle_length
        if repeats >= 2:
            return {
                "severity": "error",
                "code": "model_repetitive_tool_loop",
                "title": "Model repeated a successful read-only tool cycle without progress",
                "detail": f"A {cycle_length}-call read-only cycle repeated {repeats} times.",
                "remediation": "Do not retry unchanged successful reads; use the evidence already returned to choose a state-changing repair or the next workflow phase.",
                "sequence": suffix[cursor][3] if cursor < len(suffix) else None,
                "tool": None,
            }
    return None


def _category_counts(timeline: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"diagnostics": 0, "recovery": 0, "workspace": 0, "release": 0, "verification": 0}
    for entry in timeline:
        tool = str(entry.get("tool") or "")
        if tool.startswith("recovery."):
            counts["recovery"] += 1
        elif tool.startswith("workspace."):
            counts["workspace"] += 1
        elif tool.startswith("release."):
            counts["release"] += 1
        elif tool.startswith("runtime."):
            counts["verification"] += 1
        else:
            counts["diagnostics"] += 1
    return counts


def _phase_coverage(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tools_seen = {str(entry.get("tool") or "") for entry in timeline}
    successful = {str(entry.get("tool") or "") for entry in timeline if entry.get("success")}
    covered: list[dict[str, Any]] = []
    for phase in EXPECTED_PHASES:
        matched = [name for name in phase["tools"] if name in tools_seen]
        matched_ok = [name for name in phase["tools"] if name in successful]
        if phase["id"] == "recover":
            restored = "recovery.restore" in successful
            status = "present" if restored else ("attempted" if matched else "missing")
        elif phase["id"] == "edit":
            edited = "workspace.edit" in successful
            status = "present" if edited else ("attempted" if matched else "missing")
        elif phase["id"] == "verify":
            # Verification is complete only after all three public workloads pass.
            passed = set()
            for entry in timeline:
                if entry.get("tool") != "runtime.run" or not entry.get("success"):
                    continue
                args = entry.get("arguments") if isinstance(entry.get("arguments"), dict) else {}
                result = entry.get("result_summary") if isinstance(entry.get("result_summary"), dict) else {}
                workload_id = args.get("workload_id")
                if workload_id in {"P1", "P2", "P3"} and result.get("outcome") == "pass":
                    passed.add(workload_id)
            status = "present" if passed == {"P1", "P2", "P3"} else ("attempted" if matched else "missing")
        elif matched_ok:
            status = "present"
        elif matched:
            status = "attempted"
        else:
            status = "missing"
        covered.append(
            {
                "id": phase["id"],
                "title": phase["title"],
                "status": status,
                "detail": phase["detail"],
                "tools_seen": matched,
            }
        )
    return covered


def _protocol_health(run: dict[str, Any], timeline: list[dict[str, Any]]) -> dict[str, Any]:
    error_category = run.get("error_category")
    termination = run.get("termination_reason")
    protocol_issues: list[dict[str, str]] = []
    if error_category in {"malformed_model_response", "unknown_tool"}:
        protocol_issues.append(
            {
                "code": str(error_category),
                "title": "Provider/tool-call protocol failure",
                "detail": str(run.get("error_message") or error_category),
            }
        )
    if termination == "model_stopped_without_tool_call":
        protocol_issues.append(
            {
                "code": "no_tool_calls",
                "title": "Model stopped without emitting tool calls",
                "detail": "The adapter received an assistant turn with empty tool_calls. A syntax probe does not guarantee that a model will choose tools throughout a full multi-turn task; inspect the reasoning effort and output budget.",
            }
        )
    return {
        "tool_calls_executed": len(timeline),
        "tool_failures": sum(1 for entry in timeline if not entry.get("success")),
        "model_calls": int(run.get("model_call_count") or 0),
        "reasoning_tokens": int(run.get("reasoning_tokens") or 0),
        "protocol_issues": protocol_issues,
        "tool_calling_appears_functional": bool(timeline) and error_category not in {
            "malformed_model_response",
            "unknown_tool",
        },
    }


def analyze_tool_use(run: dict[str, Any]) -> dict[str, Any]:
    """Build a read-only debug report for episode inspection."""
    timeline = [
        entry for entry in (run.get("authenticated_timeline") or [])
        if isinstance(entry, dict)
    ]
    findings: list[dict[str, Any]] = []
    repetitive_cycle = _repeated_read_only_cycle_finding(timeline)
    if repetitive_cycle is not None:
        findings.append(repetitive_cycle)
    for entry in timeline:
        if entry.get("success"):
            continue
        message = _tool_error_message(entry) or "tool failed"
        args = entry.get("arguments") if isinstance(entry.get("arguments"), dict) else {}
        code, title, remediation = _classify_error(
            message,
            tool=str(entry.get("tool") or "") or None,
            arguments=args,
        )
        findings.append(
            {
                "severity": "error",
                "code": code,
                "title": title,
                "detail": message,
                "remediation": remediation,
                "sequence": entry.get("sequence"),
                "tool": entry.get("tool"),
            }
        )
    findings.extend(_repeated_failure_findings(timeline))

    counts = _category_counts(timeline)
    phases = _phase_coverage(timeline)
    protocol = _protocol_health(run, timeline)

    diagnostic_failures = [
        finding for finding in findings
        if str(finding.get("code") or "").startswith("diagnostic_")
        or finding.get("tool") in {"telemetry.logs", "telemetry.trace", "state.inspect"}
    ]
    if counts["diagnostics"] == 0 and timeline:
        findings.append(
            {
                "severity": "warning",
                "code": "skipped_investigation",
                "title": "No diagnostic tools were used",
                "detail": "The episode never called release.status, telemetry.*, or state.inspect.",
                "remediation": "Investigate public evidence before pausing and editing.",
                "sequence": None,
                "tool": None,
            }
        )
    elif diagnostic_failures and not any(
        entry.get("tool") in {"telemetry.logs", "telemetry.trace", "state.inspect", "release.status"} and entry.get("success")
        for entry in timeline
    ):
        findings.append(
            {
                "severity": "warning",
                "code": "investigation_attempted_but_failed",
                "title": "Diagnostics were attempted but never succeeded",
                "detail": "The model called diagnostic tools with invalid aliases/sources/selectors and never obtained usable evidence.",
                "remediation": "telemetry.logs alias=Q-41 (no window), then state.inspect source='public' with a concrete selector; do not reuse digests or status field names.",
                "sequence": None,
                "tool": None,
            }
        )
    if timeline and not any(
        entry.get("tool") == "workspace.edit" and entry.get("success") for entry in timeline
    ):
        findings.append(
            {
                "severity": "warning",
                "code": "skipped_candidate_edits",
                "title": "No candidate workspace edits",
                "detail": "No successful workspace.edit ran, so deploy cannot activate a repair.",
                "remediation": "workspace.read the broken files, workspace.edit a general fix, then deploy.",
                "sequence": None,
                "tool": None,
            }
        )

    missing_phases = [phase["id"] for phase in phases if phase["status"] == "missing"]
    if (
        run.get("termination_reason") in {
            "model_stopped", "model_stopped_without_tool_call", "environment_truncated",
            "model_repetitive_tool_loop", "model_call_budget",
        }
        and missing_phases
        and timeline
    ):
        findings.append(
            {
                "severity": "warning",
                "code": "incomplete_repair_sequence",
                "title": "Model stopped before completing the recovery workflow",
                "detail": f"Missing phases: {', '.join(missing_phases)}.",
                "remediation": "Continue through pause → restore → edit → deploy → P1/P2/P3 → resume.",
                "sequence": None,
                "tool": None,
            }
        )

    for issue in protocol["protocol_issues"]:
        findings.insert(
            0,
            {
                "severity": "error",
                "code": issue["code"],
                "title": issue["title"],
                "detail": issue["detail"],
                "remediation": "Confirm the Settings tool probe still passes, inspect the selected reasoning effort, and review model_turn_debug finish_reason.",
                "sequence": None,
                "tool": None,
            },
        )

    primary = None
    for finding in findings:
        if finding["severity"] == "error":
            primary = finding
            break
    if primary is None and findings:
        primary = findings[0]

    diagnostic_primary = primary is not None and (
        str(primary.get("code") or "").startswith("diagnostic_")
        or primary.get("code") == "invalid_tool_arguments"
    )
    if primary is None:
        summary = "No tool failures detected in the authenticated timeline."
        if not timeline:
            summary = "No authenticated tool actions were recorded for this episode."
    elif protocol["tool_calling_appears_functional"] and primary["code"].startswith("precondition_"):
        summary = (
            "Tool calling protocol succeeded, but the model violated recovery/release "
            f"preconditions ({primary['code']}). This is workflow misuse, not a broken local tool adapter."
        )
    elif protocol["tool_calling_appears_functional"] and diagnostic_primary:
        summary = (
            "Tool calling protocol succeeded, but diagnostics used invalid public identifiers "
            f"({primary['code']}). Local adapters are working; the model is guessing aliases/sources."
        )
    elif not protocol["tool_calling_appears_functional"]:
        summary = f"Tool-calling protocol issue: {primary['title']}."
    else:
        summary = primary["title"]

    return {
        "summary": summary,
        "primary_cause": primary,
        "findings": findings,
        "coverage": counts,
        "workflow_phases": phases,
        "protocol_health": protocol,
        "expected_shortest_path": [
            "recovery.pause",
            "recovery.restore (S0 default)",
            "workspace.edit (candidate files)",
            "release.deploy",
            "runtime.run P1 / P2 / P3",
            "recovery.resume",
        ],
    }


def model_turn_debug_entry(response: Any, *, turn: int) -> dict[str, Any]:
    """Compact per-turn provider metadata safe for public episode records."""
    tool_calls = getattr(response, "tool_calls", ()) or ()
    text = getattr(response, "text", "") or ""
    reasoning = getattr(response, "reasoning", "") or ""
    return {
        "turn": turn,
        "finish_reason": getattr(response, "finish_reason", None),
        "tool_call_count": len(tool_calls),
        "tool_names": [getattr(call, "name", None) for call in tool_calls[:8]],
        "dropped_tool_calls": max(0, len(tool_calls) - 4),
        "has_text": bool(text.strip()),
        "text_chars": len(text),
        "has_reasoning": bool(reasoning.strip()),
        "reasoning_chars": len(reasoning),
        "input_tokens": int(getattr(response, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(response, "output_tokens", 0) or 0),
        "reasoning_tokens": int(getattr(response, "reasoning_tokens", 0) or 0),
        "latency_ms": round(float(getattr(response, "latency_ms", 0.0) or 0.0), 3),
    }
