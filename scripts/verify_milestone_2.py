"""Run Milestone 2 tests and regenerate the live evidence receipt."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from agent_surface import ToolGateway, ToolClient  # noqa: E402
from event_service_substrate import RecoveryAuthority  # noqa: E402
from event_service_substrate.canonical import canonical_json  # noqa: E402
from verify_common import parse_test_count, validate_source_commit  # noqa: E402


_KEYS = (
    bytes.fromhex("a740d62c0860d7f2d8c0b7261a622d9c8ab44298984e65ff8d53d365e486f731"),
    bytes.fromhex("29e8bc7f706cfe3c428b18b8e41cf03843d8dc4b6f1a3976bccb5e885c1a427e"),
)
_SCOPES = (
    "scope-71e5a88c9bdc47f0",
    "scope-c92f60ad3e7641bb",
)

_ALLOWED_RECEIPT_FILES = (
    "evidence/milestone-1-substrate.json",
    "evidence/milestone-2-interaction-layer.json",
)


def _authority(index: int) -> RecoveryAuthority:
    return RecoveryAuthority(_KEYS[index], _SCOPES[index])


def _run_public_flow(session: ToolClient) -> dict[str, Any]:
    """Execute the canonical pause/restore/edit/deploy/run/resume flow."""
    session.recovery_pause()
    session.release_rollback("r0")
    session.recovery_restore()
    session.workspace_edit("service/settings.toml", "[service]\nattempt_budget = 2\n")
    session.release_deploy()
    r1 = session.runtime_run("P1")
    r2 = session.runtime_run("P2")
    r3 = session.runtime_run("P3")
    session.recovery_resume()
    return {
        "P1": r1,
        "P2": r2,
        "P3": r3,
        "final_status": session.release_status(),
    }


def _diagnostic_evidence(session: ToolClient, workload_id: str) -> dict[str, Any]:
    """Run a diagnostic cutpoint and collect its trace/state evidence."""
    session.recovery_pause()
    session.release_rollback("r0")
    session.recovery_restore()
    receipt = session.runtime_run(workload_id, cutpoint=f"{workload_id}.exit")
    trace = session.telemetry_trace(receipt["handle"])
    selectors = [dict(s) for s in trace["selectors"]]
    events: list[dict[str, Any]] = []
    for sel in selectors:
        event_id = sel.get("event_id")
        if not event_id:
            continue
        events.append(
            {
                "event_id": event_id,
                "effects": session.state_inspect(
                    receipt["handle"], {"event_id": event_id}, "effects"
                )["rows"],
                "journal": session.state_inspect(
                    receipt["handle"], {"event_id": event_id}, "journal"
                )["rows"],
            }
        )
    keys = session.state_inspect(
        receipt["handle"],
        {"command_key": "cmd_diagnostic", "occurrence_id": "occ_diagnostic"},
        "keys",
    )["rows"]
    return {
        "workload_id": workload_id,
        "receipt": receipt,
        "events": events,
        "keys": keys,
        "trace_spans": len(trace["spans"]),
    }


def _collect_session_evidence(
    session: ToolClient, *, public: dict[str, Any], diagnostic: dict[str, Any]
) -> dict[str, Any]:
    status = session.release_status()
    return {
        "initial_status": status,
        "public_flow": public,
        "diagnostic": diagnostic,
        "leak_probe": session.leak_probe(),
        "snapshot": session.state_inspect(
            "public", {"snapshot_id": "S0"}, "recovery"
        )["rows"][0],
        "progress": session.state_inspect(
            "public", {"stream": "settlement"}, "progress"
        )["rows"][0],
        "roots": status["roots"],
    }


def _public_receipts_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    keys = (
        "workload_id",
        "cutpoint",
        "outcome",
        "effect_count",
        "event_count",
        "net_effect_count",
        "cursor_seq",
        "alias",
        "active_config_root",
    )
    return all(a[k] == b[k] for k in keys)


def _receipt_is_safe(receipt: dict[str, Any]) -> bool:
    text = canonical_json(receipt).decode("utf-8").lower()
    forbidden = (
        "auth_tag",
        "authority_scope",
        "member_selector",
        "fixture_profile",
        "profile",
        "instance a",
        "instance b",
        *[key.hex() for key in _KEYS],
    )
    return all(token not in text for token in forbidden)


def collect_live_evidence(
    *,
    source_commit: str,
    verification_command: str,
    pytest_summary: dict[str, Any],
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="milestone-2-live-") as directory:
        base = Path(directory)
        gateway_a = ToolGateway(0, base / "session-a", base / "fixture-a", _authority(0))
        gateway_b = ToolGateway(1, base / "session-b", base / "fixture-b", _authority(1))
        with gateway_a as session_a, gateway_b as session_b:
            public_a = _run_public_flow(session_a)
            public_b = _run_public_flow(session_b)

            diagnostic_a = _diagnostic_evidence(session_a, "s5")
            diagnostic_b = _diagnostic_evidence(session_b, "s2")

            evidence_a = _collect_session_evidence(
                session_a, public=public_a, diagnostic=diagnostic_a
            )
            evidence_b = _collect_session_evidence(
                session_b, public=public_b, diagnostic=diagnostic_b
            )

            public_receipts_equal = (
                _public_receipts_equal(public_a["P1"], public_b["P1"])
                and _public_receipts_equal(public_a["P2"], public_b["P2"])
                and _public_receipts_equal(public_a["P3"], public_b["P3"])
            )
            service_state_diverges_after_diagnostics = (
                evidence_a["roots"]["service_state"] != evidence_b["roots"]["service_state"]
            )
            leak_checks_pass = (
                evidence_a["leak_probe"]["passed"]
                and evidence_b["leak_probe"]["passed"]
            )
            snapshot_authenticated = (
                evidence_a["snapshot"]["authenticated"]
                and evidence_b["snapshot"]["authenticated"]
            )
            incident_closed_after_resume = (
                public_a["final_status"]["incident"] == "closed"
                and public_b["final_status"]["incident"] == "closed"
            )
            tool_inventory = session_a.tool_inventory()
            correct_tool_count = len(tool_inventory) == 12

            results = {
                "public_receipts_equal": public_receipts_equal,
                "service_state_diverges_after_diagnostics": service_state_diverges_after_diagnostics,
                "leak_checks_pass": leak_checks_pass,
                "snapshot_authenticated": snapshot_authenticated,
                "incident_closed_after_resume": incident_closed_after_resume,
                "correct_tool_count": correct_tool_count,
            }

            if not all(results.values()):
                raise AssertionError("live Milestone 2 evidence contains a failed required check")

            receipt: dict[str, Any] = {
                "schema_version": 2,
                "milestone": "milestone-2-agent-interaction-layer",
                "tested_source_commit": source_commit,
                "git_sha_status": "tested-source-commit",
                "verification": {
                    "command": verification_command,
                    "python_version": sys.version.split()[0],
                    "milestone_1_pytest_command": pytest_summary["milestone_1_pytest_command"],
                    "milestone_1_test_count": pytest_summary["milestone_1_test_count"],
                    "milestone_2_pytest_command": pytest_summary["milestone_2_pytest_command"],
                    "milestone_2_test_count": pytest_summary["milestone_2_test_count"],
                    "total_test_count": pytest_summary["total_test_count"],
                    "test_count": pytest_summary["total_test_count"],
                    "outcome": "pass",
                },
                "semantic_roots": {
                    "A": evidence_a["roots"],
                    "B": evidence_b["roots"],
                },
                "public_flow": {
                    "A": evidence_a["public_flow"],
                    "B": evidence_b["public_flow"],
                },
                "diagnostic_evidence": {
                    "A": evidence_a["diagnostic"],
                    "B": evidence_b["diagnostic"],
                },
                "required_checks": results,
                "leak_probe": {
                    "A": evidence_a["leak_probe"],
                    "B": evidence_b["leak_probe"],
                },
                "limitations": [
                    "Agent-visible runtime uses a deterministic workload engine with the candidate configuration; arbitrary source execution is deferred to later verifier integration.",
                    "Network access is not required by the runtime and is not tested here.",
                    "Long-horizon and model-evaluation claims remain outside Milestone 2.",
                ],
                "timestamp": datetime.now(timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
            }
            if not _receipt_is_safe(receipt):
                raise AssertionError("receipt contains privileged or causal material")
            receipt["required_checks"]["receipt_fields_safe"] = True
            if not _receipt_is_safe(receipt):
                raise AssertionError("final receipt contains privileged or causal material")
            return receipt


def write_receipt(receipt: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run_pytest_suite(path: str) -> tuple[str, int]:
    command = [sys.executable, "-m", "pytest", path, "-q"]
    result = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"pytest suite {path} failed")
    return subprocess.list2cmdline(command), parse_test_count(result.stdout)


def _run_pytests() -> dict[str, Any]:
    m1_command, m1_count = _run_pytest_suite("tests/milestone_1")
    m2_command, m2_count = _run_pytest_suite("tests/milestone_2")
    return {
        "milestone_1_pytest_command": m1_command,
        "milestone_1_test_count": m1_count,
        "milestone_2_pytest_command": m2_command,
        "milestone_2_test_count": m2_count,
        "total_test_count": m1_count + m2_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "evidence" / "milestone-2-interaction-layer.json",
    )
    parser.add_argument(
        "--source-commit",
        default=None,
        help="override the source commit the receipt is bound to (default: git HEAD)",
    )
    args = parser.parse_args()
    try:
        source_commit = validate_source_commit(
            REPOSITORY_ROOT, args.source_commit, _ALLOWED_RECEIPT_FILES
        )
        pytest_summary = _run_pytests()
        verification_command = subprocess.list2cmdline([sys.executable, *sys.argv])
        receipt = collect_live_evidence(
            source_commit=source_commit,
            verification_command=verification_command,
            pytest_summary=pytest_summary,
        )
        write_receipt(receipt, args.output)
        print(f"wrote {args.output}")
        return 0
    except Exception as error:  # noqa: BLE001 - command must fail closed.
        print(f"verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
