from __future__ import annotations

import pytest

from agent_surface import ToolError


def test_initial_telemetry_handle_traces_and_rejects_invalid(sessions) -> None:
    a, b = sessions
    logs = a.telemetry_logs("Q-41")
    handle = logs["handle"]
    trace = a.telemetry_trace(handle)
    assert trace["spans"]
    assert trace["handle"] == handle

    with pytest.raises(ToolError, match="invalid trace capability"):
        a.telemetry_trace(handle + "0")
    with pytest.raises(ToolError, match="invalid trace capability"):
        a.telemetry_trace(handle[:-4] + "abcd")
    with pytest.raises(ToolError, match="invalid trace capability"):
        b.telemetry_trace(handle)


def test_trace_capability_rejects_guessed_and_random(sessions) -> None:
    a, _ = sessions
    with pytest.raises(ToolError, match="invalid trace capability"):
        a.telemetry_trace("h_00000000000000000000000000000000")
    with pytest.raises(ToolError, match="invalid trace capability"):
        a.telemetry_trace("not-a-token")
    with pytest.raises(ToolError, match="invalid trace capability"):
        a.telemetry_trace("")


def test_runtime_handle_allows_trace_and_bound_state_views(sessions) -> None:
    a, _ = sessions
    a.recovery_pause()
    a.release_rollback("r0")
    a.recovery_restore()
    receipt = a.runtime_run("P1")
    handle = receipt["handle"]
    trace = a.telemetry_trace(handle)
    assert any(s["stage"] == "s5" for s in trace["spans"])
    selector = next(s for s in trace["selectors"] if s["event_id"])
    event_id = selector["event_id"]
    assert a.state_inspect(handle, {"event_id": event_id}, "journal")["rows"]
    assert a.state_inspect(handle, {"event_id": event_id}, "effects")["rows"]
    assert a.state_inspect(
        handle,
        {"command_key": selector["command_key"], "occurrence_id": selector["occurrence_id"]},
        "keys",
    )["rows"]


def test_state_view_broadening_and_selector_broadening_fail(sessions) -> None:
    a, _ = sessions
    a.recovery_pause()
    a.release_rollback("r0")
    a.recovery_restore()
    receipt = a.runtime_run("P1")
    handle = receipt["handle"]
    trace = a.telemetry_trace(handle)
    event_id = next(s["event_id"] for s in trace["selectors"] if s["event_id"])

    # progress/recovery are public-only views, not granted by a trace handle.
    with pytest.raises(ToolError, match="view not allowed"):
        a.state_inspect(handle, {"stream": "settlement"}, "progress")
    with pytest.raises(ToolError, match="view not allowed"):
        a.state_inspect(handle, {"snapshot_id": "S0"}, "recovery")

    # fabricating an event_id outside the trace should fail.
    with pytest.raises(ToolError, match="selector not allowed"):
        a.state_inspect(handle, {"event_id": "evt_00000000000000000000000000000000"}, "effects")
    # broadening the command_key/occurrence_id pair should fail.
    with pytest.raises(ToolError, match="selector not allowed"):
        a.state_inspect(handle, {"command_key": "cmd_missing", "occurrence_id": "occ_missing"}, "keys")


def test_trace_capability_invalidates_after_transitions(sessions) -> None:
    a, _ = sessions
    a.recovery_pause()
    a.release_rollback("r0")
    a.recovery_restore()
    receipt = a.runtime_run("P1")
    handle = receipt["handle"]
    a.telemetry_trace(handle)

    a.release_rollback("r0")
    with pytest.raises(ToolError, match="expired"):
        a.telemetry_trace(handle)

    a.recovery_restore()
    with pytest.raises(ToolError, match="expired"):
        a.telemetry_trace(handle)

    a.workspace_edit("service/settings.toml", "[service]\nattempt_budget = 2\n")
    a.release_deploy()
    with pytest.raises(ToolError, match="expired"):
        a.telemetry_trace(handle)

    a.runtime_run("P1")
    a.runtime_run("P2")
    a.runtime_run("P3")
    a.recovery_resume()
    with pytest.raises(ToolError, match="expired"):
        a.telemetry_trace(handle)


def test_state_inspect_rejects_empty_and_missing_trace_source(sessions) -> None:
    a, _ = sessions
    a.recovery_pause()
    a.release_rollback("r0")
    a.recovery_restore()
    receipt = a.runtime_run("P1")
    handle = receipt["handle"]
    with pytest.raises(ToolError, match="selector is empty"):
        a.state_inspect(handle, {}, "effects")
    with pytest.raises(ToolError, match="invalid trace capability"):
        a.state_inspect("h_not_a_real_handle", {"event_id": "evt_0"}, "effects")
