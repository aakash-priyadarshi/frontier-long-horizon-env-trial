from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_surface import ToolError


# ---------------------------------------------------------------------------
# Surface and tool inventory
# ---------------------------------------------------------------------------


def test_release_status_initial_surface_is_deterministic(sessions) -> None:
    a, b = sessions
    sa, sb = a.release_status(), b.release_status()
    for key in (
        "active_source_root",
        "active_config_root",
        "candidate_root",
        "attempt_budget",
        "public_canary",
        "incident",
        "tool_inventory",
    ):
        assert sa[key] == sb[key], key
    assert sa["public_canary_receipts"] == sb["public_canary_receipts"] == []
    assert sa["active_revision"] == sb["active_revision"] == "r1"
    assert sa["attempt_budget"] == sb["attempt_budget"] == 1


def test_tool_inventory_lists_twelve_bounded_tools(sessions) -> None:
    a, _ = sessions
    inventory = a.tool_inventory()
    assert len(inventory) == 12
    assert set(inventory) == {
        "release.status",
        "workspace.read",
        "workspace.edit",
        "telemetry.logs",
        "telemetry.trace",
        "state.inspect",
        "runtime.run",
        "recovery.pause",
        "recovery.restore",
        "release.rollback",
        "release.deploy",
        "recovery.resume",
    }


def test_workspace_read_is_bounded_to_active_workspace(sessions) -> None:
    a, _ = sessions
    text = a.workspace_read("service/contract.md")
    assert "settlement" in text.lower()
    with pytest.raises(ToolError, match="path outside workspace"):
        a.workspace_read("../service.sqlite3")
    with pytest.raises(ToolError, match="file not found"):
        a.workspace_read("service/missing.py")


# ---------------------------------------------------------------------------
# Release rollbacks and deployments
# ---------------------------------------------------------------------------


def test_release_rollback_to_r0_changes_attempt_budget(sessions) -> None:
    a, _ = sessions
    a.recovery_pause()
    result = a.release_rollback("r0")
    assert result["revision"] == "r0"
    status = a.release_status()
    assert status["active_revision"] == "r0"
    assert status["attempt_budget"] == 3


def test_release_deploy_activates_candidate_workspace(sessions) -> None:
    a, _ = sessions
    a.recovery_pause()
    a.workspace_edit("service/contract.md", "# modified contract\n")
    deploy = a.release_deploy()
    assert deploy["revision"] == "candidate"
    status = a.release_status()
    assert status["active_revision"] == "candidate"
    assert a.workspace_read("service/contract.md").startswith("# modified contract")


# ---------------------------------------------------------------------------
# Runtime workloads and diagnostics
# ---------------------------------------------------------------------------


def test_public_workloads_pass_after_r0_rollback(sessions) -> None:
    a, _ = sessions
    a.recovery_pause()
    a.release_rollback("r0")
    a.recovery_restore()
    r1 = a.runtime_run("P1")
    r2 = a.runtime_run("P2")
    r3 = a.runtime_run("P3")
    assert r1["outcome"] == r2["outcome"] == r3["outcome"] == "pass"
    assert r1["effect_count"] == r2["effect_count"] == 1
    assert r3["effect_count"] == 3


def test_public_workloads_fail_with_r1_attempt_budget(sessions) -> None:
    a, _ = sessions
    a.recovery_pause()
    a.recovery_restore()
    with pytest.raises(ToolError, match="attempt budget"):
        a.runtime_run("P1")


def test_public_workloads_pass_after_candidate_config_edit(sessions) -> None:
    a, _ = sessions
    a.recovery_pause()
    a.recovery_restore()
    a.workspace_edit("service/settings.toml", "[service]\nattempt_budget = 2\n")
    a.release_deploy()
    assert a.runtime_run("P1")["outcome"] == "pass"
    assert a.runtime_run("P2")["outcome"] == "pass"
    assert a.runtime_run("P3")["outcome"] == "pass"


def test_s5_exit_diagnostic_shows_duplicate_effects(sessions) -> None:
    a, _ = sessions
    a.recovery_pause()
    a.release_rollback("r0")
    a.recovery_restore()
    receipt = a.runtime_run("s5", cutpoint="s5.exit")
    assert receipt["outcome"] == "cutpoint"
    assert receipt["effect_count"] == 2
    trace = a.telemetry_trace(receipt["handle"])
    assert len(trace["spans"]) == 10
    assert any(s["stage"] == "cutpoint" for s in trace["spans"])
    assert len(trace["selectors"]) == 1
    event_id = trace["selectors"][0]["event_id"]
    effects = a.state_inspect(receipt["handle"], {"event_id": event_id}, "effects")
    assert len(effects["rows"]) == 2
    journal = a.state_inspect(receipt["handle"], {"event_id": event_id}, "journal")
    assert len(journal["rows"]) == 1


def test_s2_exit_diagnostic_shows_two_events_and_keys(sessions) -> None:
    _, b = sessions
    b.recovery_pause()
    b.release_rollback("r0")
    b.recovery_restore()
    receipt = b.runtime_run("s2", cutpoint="s2.exit")
    assert receipt["outcome"] == "cutpoint"
    assert receipt["event_count"] == 2
    trace = b.telemetry_trace(receipt["handle"])
    event_ids = [s["event_id"] for s in trace["spans"] if s["event_id"]]
    assert len(set(event_ids)) == 2
    assert len(trace["selectors"]) == 2
    keys = b.state_inspect(
        receipt["handle"],
        {"command_key": "cmd_diagnostic", "occurrence_id": "occ_diagnostic"},
        "keys",
    )
    assert len(keys["rows"]) == 1
    registered_event_id = keys["rows"][0][2]
    assert registered_event_id in set(event_ids)


# ---------------------------------------------------------------------------
# Telemetry and state chains
# ---------------------------------------------------------------------------


def test_telemetry_logs_and_trace_chain_for_initial_alias(sessions) -> None:
    a, _ = sessions
    logs = a.telemetry_logs("Q-41")
    assert len(logs["lines"]) == 5
    trace = a.telemetry_trace(logs["handle"])
    assert trace["spans"]


def test_telemetry_logs_and_trace_chain_for_public_workload(sessions) -> None:
    a, _ = sessions
    a.recovery_pause()
    a.release_rollback("r0")
    a.recovery_restore()
    a.runtime_run("P1")
    logs = a.telemetry_logs("P1")
    assert any("settlement observed" in line for line in logs["lines"])
    trace = a.telemetry_trace(logs["handle"])
    assert any(s["stage"] == "s5" for s in trace["spans"])
    assert trace["selectors"]
    event_id = next(s["event_id"] for s in trace["selectors"] if s["event_id"])
    assert a.state_inspect(logs["handle"], {"event_id": event_id}, "effects")["rows"]


def test_state_inspect_public_recovery_and_progress(sessions) -> None:
    a, _ = sessions
    recovery = a.state_inspect("public", {"snapshot_id": "S0"}, "recovery")
    assert recovery["rows"][0]["authenticated"] is True
    progress = a.state_inspect("public", {"stream": "settlement"}, "progress")
    assert progress["rows"][0]["stream"] == "settlement"


# ---------------------------------------------------------------------------
# Full recovery/resume flow
# ---------------------------------------------------------------------------


def test_full_recovery_resume_closes_incident(sessions) -> None:
    a, _ = sessions
    a.recovery_pause()
    a.release_rollback("r0")
    a.recovery_restore()
    a.runtime_run("P1")
    a.runtime_run("P2")
    a.runtime_run("P3")
    a.release_deploy()
    tick = a.recovery_resume()
    status = a.release_status()
    assert status["intake"] == "open"
    assert status["incident"] == "closed"
    assert status["public_canary"] == "pass"
    assert tick > status["tick"] - 10


# ---------------------------------------------------------------------------
# Workspace boundaries and leak probes
# ---------------------------------------------------------------------------


def test_leak_probe_passes_and_session_has_no_privileged_files(sessions) -> None:
    a, _ = sessions
    probe = a.leak_probe()
    assert probe["passed"], probe["problems"]
    assert not (a.session_dir / "service.sqlite3").exists()
    assert not (a.session_dir / "src").exists()


def test_session_workspace_cannot_import_event_service_substrate(
    sessions, tmp_path: Path
) -> None:
    a, _ = sessions
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import sys; sys.path.insert(0, sys.argv[1]);\n"
        "try:\n"
        "    import event_service_substrate\n"
        "    print('reachable')\n"
        "except ImportError:\n"
        "    print('isolated')\n",
        encoding="utf-8",
    )
    env = dict(**os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-S", str(probe), str(a.session_dir)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.stdout.strip() == "isolated"
