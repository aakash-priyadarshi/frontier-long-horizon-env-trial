from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from event_service_substrate import build_fixture
from event_service_substrate.canonical import canonical_json
from event_service_substrate.instance import TICKET

from conftest import TEST_KEYS, TEST_SCOPES, authority_for_test


PUBLIC_ROOTS = (
    "source",
    "config",
    "deployment",
    "runtime",
    "telemetry",
    "audit",
    "snapshot",
)


def _visible_exception(fixture) -> str:
    try:
        fixture.restore()
    except Exception as error:  # noqa: BLE001 - public exception enumeration.
        return f"{type(error).__name__}: {error}"
    raise AssertionError("restore without pause unexpectedly succeeded")


def _enumerate_public_surface(fixture) -> dict[str, object]:
    workspace = {
        path.relative_to(fixture.workspace).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(fixture.workspace.rglob("*"))
        if path.is_file()
    }
    roots = fixture.roots()
    return {
        "workspace": workspace,
        "status": fixture.public_status(),
        "ticket": TICKET,
        "logs": list(fixture.visible_logs()),
        "revision_diff": fixture.revision_diff(),
        "visible_exception": _visible_exception(fixture),
        "public_roots": {name: roots[name] for name in PUBLIC_ROOTS},
        "public_bytes": hashlib.sha256(fixture.public_bytes()).hexdigest(),
    }


def test_complete_intended_public_surface_is_equal(fixtures) -> None:
    first, second = fixtures
    first_surface = _enumerate_public_surface(first)
    second_surface = _enumerate_public_surface(second)
    assert first_surface.keys() == {
        "workspace",
        "status",
        "ticket",
        "logs",
        "revision_diff",
        "visible_exception",
        "public_roots",
        "public_bytes",
    }
    assert first_surface == second_surface
    public_text = canonical_json(first_surface).decode("utf-8").lower()
    secondary_forbidden = (
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
    assert all(token not in public_text for token in secondary_forbidden)
    assert all(key.hex() not in public_text for key in TEST_KEYS)


def test_construction_order_does_not_change_roots(tmp_path: Path) -> None:
    forward = (
        build_fixture(tmp_path / "forward-1", 0, authority_for_test(0)),
        build_fixture(tmp_path / "forward-2", 1, authority_for_test(1)),
    )
    reverse_second = build_fixture(tmp_path / "reverse-2", 1, authority_for_test(1))
    reverse_first = build_fixture(tmp_path / "reverse-1", 0, authority_for_test(0))
    try:
        assert forward[0].roots() == reverse_first.roots()
        assert forward[1].roots() == reverse_second.roots()
    finally:
        for fixture in (*forward, reverse_second, reverse_first):
            fixture.close()


def test_unicode_and_spaces_in_paths_do_not_change_roots(tmp_path: Path) -> None:
    plain = build_fixture(tmp_path / "plain", 0, authority_for_test(0))
    decorated = build_fixture(tmp_path / "space and Δ unicode" / "fixture", 0, authority_for_test(0))
    try:
        assert plain.roots() == decorated.roots()
        assert plain.public_bytes() == decorated.public_bytes()
    finally:
        plain.close()
        decorated.close()


def test_irrelevant_environment_variables_do_not_change_roots(
    tmp_path: Path, monkeypatch
) -> None:
    baseline = build_fixture(tmp_path / "baseline", 0, authority_for_test(0))
    monkeypatch.setenv("EVENT_SERVICE_MEMBER", "unrelated-value")
    monkeypatch.setenv("fixture_profile", "unrelated-value")
    changed = build_fixture(tmp_path / "changed", 0, authority_for_test(0))
    try:
        assert baseline.roots() == changed.roots()
    finally:
        baseline.close()
        changed.close()


def test_repeated_fresh_process_construction_is_deterministic(tmp_path: Path) -> None:
    probe = Path(__file__).with_name("_process_probe.py")
    environment = dict(os.environ)
    environment["IRRELEVANT_PROBE_VALUE"] = "α value with spaces"
    outputs = []
    for cwd in (tmp_path, tmp_path / "cwd with spaces"):
        cwd.mkdir(exist_ok=True)
        result = subprocess.run(
            [sys.executable, str(probe)],
            cwd=cwd,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        outputs.append(json.loads(result.stdout))
    assert outputs[0] == outputs[1]


def test_fixture_package_does_not_consume_process_metadata() -> None:
    package_root = Path(__file__).parents[2] / "src" / "event_service_substrate"
    source = "\n".join(path.read_text(encoding="utf-8") for path in package_root.glob("*.py"))
    assert all(
        token not in source
        for token in ("os.environ", "os.getenv", "getenv(", "sys.argv")
    )


def test_authority_key_and_fixture_scope_are_not_persisted_or_public(fixtures) -> None:
    for fixture, key, scope in zip(fixtures, TEST_KEYS, TEST_SCOPES, strict=True):
        database_text = "\n".join(fixture.store.connection.iterdump()).lower()
        public_text = fixture.public_bytes().decode("utf-8").lower()
        workspace_bytes = b"\n".join(
            path.read_bytes()
            for path in fixture.workspace.rglob("*")
            if path.is_file()
        ).lower()
        assert key.hex() not in database_text
        assert key.hex() not in public_text
        assert key not in workspace_bytes
        assert scope.lower() not in database_text
        assert scope.lower() not in public_text
        assert scope.lower().encode("utf-8") not in workspace_bytes
