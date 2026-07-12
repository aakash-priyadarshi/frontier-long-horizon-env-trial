"""Run Milestone 1 tests and regenerate the live evidence receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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

from event_service_substrate import RecoveryAuthority, build_fixture  # noqa: E402
from event_service_substrate.canonical import canonical_json  # noqa: E402
from event_service_substrate.instance import TICKET  # noqa: E402


_KEYS = (
    bytes.fromhex("a740d62c0860d7f2d8c0b7261a622d9c8ab44298984e65ff8d53d365e486f731"),
    bytes.fromhex("29e8bc7f706cfe3c428b18b8e41cf03843d8dc4b6f1a3976bccb5e885c1a427e"),
)
_SCOPES = (
    "scope-71e5a88c9bdc47f0",
    "scope-c92f60ad3e7641bb",
)

_PUBLIC_ROOT_NAMES = (
    "source",
    "config",
    "deployment",
    "runtime",
    "telemetry",
    "audit",
    "snapshot",
)


def _authority(index: int) -> RecoveryAuthority:
    return RecoveryAuthority(_KEYS[index], _SCOPES[index])


def _workspace_manifest(workspace: Path) -> dict[str, str]:
    return {
        path.relative_to(workspace).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(workspace.rglob("*"))
        if path.is_file()
    }


def _visible_exception(fixture: Any) -> str:
    try:
        fixture.restore()
    except Exception as error:  # noqa: BLE001 - evidence records the public exception.
        return f"{type(error).__name__}: {error}"
    raise AssertionError("restore without pause unexpectedly succeeded")


def _public_surface(fixture: Any) -> dict[str, Any]:
    roots = fixture.roots()
    return {
        "workspace_manifest": _workspace_manifest(fixture.workspace),
        "status": fixture.public_status(),
        "ticket": TICKET,
        "logs": list(fixture.visible_logs()),
        "revision_diff": fixture.revision_diff(),
        "visible_exception": _visible_exception(fixture),
        "public_roots": {name: roots[name] for name in _PUBLIC_ROOT_NAMES},
        "public_bytes_sha256": hashlib.sha256(fixture.public_bytes()).hexdigest(),
    }


def _secondary_leak_scan(surface: dict[str, Any]) -> bool:
    text = canonical_json(surface).decode("utf-8").lower()
    forbidden = (
        "instance a",
        "instance b",
        "member selector",
        "fixture_profile",
        "effect commit",
        "relay progress",
        "journal append",
        "command-key registration",
        "evt-041-a",
        "evt-041-b",
    )
    return all(token not in text for token in forbidden)


def _copy_snapshot(source: Any, target: Any) -> None:
    columns = (
        "snapshot_id",
        "state_root",
        "cursor_seq",
        "journal_root",
        "effect_root",
        "payload",
        "auth_tag",
        "created_tick",
    )
    row = source.store.rows(
        f"SELECT {', '.join(columns)} FROM recovery_snapshots WHERE snapshot_id = 'S0'"
    )[0]
    with target.store.connection:
        target.store.connection.execute("DELETE FROM recovery_snapshots")
        target.store.connection.execute(
            f"INSERT INTO recovery_snapshots({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            row,
        )


def _reset_service_rows_without_recovery(fixture: Any) -> None:
    with fixture.store.connection:
        fixture.store.connection.execute("DELETE FROM effects")
        fixture.store.connection.execute("DELETE FROM journal")
        fixture.store.connection.execute("DELETE FROM command_keys")
        fixture.store.connection.execute(
            "UPDATE cursor SET committed_seq = 0 WHERE stream = 'settlement'"
        )


def _snapshot_checks(base: Path) -> dict[str, bool]:
    fixtures: list[Any] = []

    def make(name: str, member: int) -> Any:
        fixture = build_fixture(base / name, member, _authority(member))
        fixtures.append(fixture)
        return fixture

    try:
        valid_left = make("auth-1", 0)
        valid_right = make("auth-2", 1)
        initially_authenticated = (
            valid_left.store.snapshot_is_valid("S0")
            and valid_right.store.snapshot_is_valid("S0")
        )

        payload_case = make("payload-case", 0)
        with payload_case.store.connection:
            payload_case.store.connection.execute(
                "UPDATE recovery_snapshots SET payload = payload || ' ' WHERE snapshot_id = 'S0'"
            )
        payload_modification_rejected = not payload_case.store.snapshot_is_valid("S0")

        tag_case = make("tag-case", 0)
        with tag_case.store.connection:
            tag_case.store.connection.execute(
                "UPDATE recovery_snapshots SET auth_tag = ? WHERE snapshot_id = 'S0'",
                ("0" * 64,),
            )
        tag_modification_rejected = not tag_case.store.snapshot_is_valid("S0")

        cross_left = make("cross-1", 0)
        cross_right = make("cross-2", 1)
        _copy_snapshot(cross_left, cross_right)
        cross_fixture_substitution_rejected = not cross_right.store.snapshot_is_valid("S0")

        forged_case = make("forged-snapshot", 0)
        source_row = forged_case.store.rows(
            """
            SELECT state_root, cursor_seq, journal_root, effect_root, payload, created_tick
            FROM recovery_snapshots WHERE snapshot_id = 'S0'
            """
        )[0]
        with forged_case.store.connection:
            forged_case.store.connection.execute(
                """
                INSERT INTO recovery_snapshots(
                    snapshot_id, state_root, cursor_seq, journal_root, effect_root,
                    payload, auth_tag, created_tick
                ) VALUES ('SX', ?, ?, ?, ?, ?, ?, ?)
                """,
                (*source_row[:-1], "f" * 64, source_row[-1]),
            )
        forged_snapshot_rejected = not forged_case.store.snapshot_is_valid("SX")

        restored_results = []
        for fixture in (valid_left, valid_right):
            telemetry_before = fixture.store.count("telemetry")
            audit_before = fixture.store.count("audit_chain")
            expected_root = fixture.store.rows(
                "SELECT state_root FROM recovery_snapshots WHERE snapshot_id = 'S0'"
            )[0][0]
            fixture.pause_intake()
            restored_root = fixture.restore()
            restored_results.append(
                restored_root == expected_root
                and fixture.store.count("telemetry") >= telemetry_before
                and fixture.store.count("audit_chain") == audit_before + 2
                and fixture.store.recovery_is_valid()
            )

        forged_recovery = make("forged-recovery", 0)
        _reset_service_rows_without_recovery(forged_recovery)
        forged_recovery.store.append_audit(
            "snapshot_restore",
            forged_recovery.store.state_root(),
            "operator",
            forged_recovery.store.tick(),
        )
        forged_recovery.store.connection.commit()
        direct_mutation_plus_audit_rejected = not forged_recovery.store.recovery_is_valid()

        return {
            "initial_snapshots_authenticated": initially_authenticated,
            "payload_modification_rejected": payload_modification_rejected,
            "authentication_tag_modification_rejected": tag_modification_rejected,
            "cross_fixture_substitution_rejected": cross_fixture_substitution_rejected,
            "forged_snapshot_rejected": forged_snapshot_rejected,
            "authenticated_restore_valid": all(restored_results),
            "direct_mutation_plus_audit_rejected": direct_mutation_plus_audit_rejected,
        }
    finally:
        for fixture in fixtures:
            fixture.close()


def _package_metadata_inputs_absent() -> bool:
    package_root = REPOSITORY_ROOT / "src" / "event_service_substrate"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in package_root.glob("*.py")
    )
    return all(
        token not in source
        for token in ("os.environ", "os.getenv", "getenv(", "sys.argv")
    )


def _receipt_is_safe(receipt: dict[str, Any]) -> bool:
    text = canonical_json(receipt).decode("utf-8").lower()
    forbidden = (
        "auth_tag",
        "authority_scope",
        "member_selector",
        "fixture_profile",
        "effect commit",
        "relay progress",
        "journal append",
        "command-key registration",
        *[key.hex() for key in _KEYS],
    )
    return all(token not in text for token in forbidden)


def collect_live_evidence(
    *,
    source_commit: str,
    verification_command: str,
    pytest_command: str,
    test_count: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="milestone-1-live-") as directory:
        base = Path(directory)
        first = build_fixture(base / "fixture-7f2a", 0, _authority(0))
        second = build_fixture(base / "fixture-c4d1", 1, _authority(1))
        try:
            roots = {"A": first.roots(), "B": second.roots()}
            surface_first = _public_surface(first)
            surface_second = _public_surface(second)
            channel_equality = {
                channel: surface_first[channel] == surface_second[channel]
                for channel in surface_first
            }
            shared_root_equality = {
                name: roots["A"][name] == roots["B"][name]
                for name in _PUBLIC_ROOT_NAMES
            }
            service_state_diverges = (
                roots["A"]["service_state"] != roots["B"]["service_state"]
            )
            leak_results = {
                "enumerated_channels": sorted(surface_first),
                "workspace_file_count": len(surface_first["workspace_manifest"]),
                "channel_equality": channel_equality,
                "shared_root_equality": shared_root_equality,
                "service_state_diverges": service_state_diverges,
                "secondary_forbidden_token_scan": (
                    _secondary_leak_scan(surface_first)
                    and _secondary_leak_scan(surface_second)
                ),
                "fixture_process_metadata_inputs_absent": _package_metadata_inputs_absent(),
            }
        finally:
            first.close()
            second.close()

        snapshot_results = _snapshot_checks(base / "snapshot-checks")

    required = [
        *leak_results["channel_equality"].values(),
        *leak_results["shared_root_equality"].values(),
        leak_results["service_state_diverges"],
        leak_results["secondary_forbidden_token_scan"],
        leak_results["fixture_process_metadata_inputs_absent"],
        *snapshot_results.values(),
    ]
    if not all(required):
        raise AssertionError("live Milestone 1 evidence contains a failed required check")

    receipt: dict[str, Any] = {
        "schema_version": 2,
        "milestone": "milestone-1-substrate-hardened",
        "tested_source_commit": source_commit,
        "git_sha_status": "tested-source-commit",
        "verification": {
            "command": verification_command,
            "python_version": sys.version.split()[0],
            "pytest_command": pytest_command,
            "test_count": test_count,
            "outcome": "pass",
        },
        "semantic_roots": roots,
        "public_equality": leak_results,
        "authenticated_snapshot_checks": snapshot_results,
        "limitations": [
            "Local HMAC authentication is not production OS or container isolation.",
            "Future agent-mount isolation is NOT VERIFIED; privileged builder package source, fixture databases, audit receipts, tests, and key material must not be mounted.",
            "Agent tools, hidden grading, workload controls, and model evaluation remain outside Milestone 1.",
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        ),
    }
    if not _receipt_is_safe(receipt):
        raise AssertionError("receipt contains privileged or causal material")
    receipt["public_equality"]["receipt_fields_safe"] = True
    if not _receipt_is_safe(receipt):
        raise AssertionError("final receipt contains privileged or causal material")
    return receipt


def write_receipt(receipt: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _run_pytest() -> tuple[str, int]:
    command = [sys.executable, "-m", "pytest", "tests/milestone_1", "-q"]
    result = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode != 0:
        raise RuntimeError("Milestone 1 pytest suite failed")
    match = re.search(r"(\d+) passed", result.stdout)
    if match is None:
        raise RuntimeError("could not determine passing test count")
    return subprocess.list2cmdline(command), int(match.group(1))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "evidence" / "milestone-1-substrate.json",
    )
    args = parser.parse_args()
    try:
        pytest_command, test_count = _run_pytest()
        verification_command = subprocess.list2cmdline([sys.executable, *sys.argv])
        receipt = collect_live_evidence(
            source_commit=_git_head(),
            verification_command=verification_command,
            pytest_command=pytest_command,
            test_count=test_count,
        )
        write_receipt(receipt, args.output)
        print(f"wrote {args.output}")
        return 0
    except Exception as error:  # noqa: BLE001 - command must fail closed.
        print(f"verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
