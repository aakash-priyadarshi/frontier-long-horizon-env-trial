"""Talon Milestone 2 checks and source-bound receipt generation.

Development must use ``--check-only``. Receipt generation refuses a dirty tree
and is intentionally not part of the Milestone 2 implementation task.

Playwright on ``--check-only`` uses ``playwright test --list`` counts only
(``result: listed_only``). Full evidence mode requires executed browser results
and a clean working tree; it does not write evidence from a dirty tree.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
for value in (str(ROOT), str(ROOT / "src")):
    if value not in sys.path:
        sys.path.insert(0, value)

from scripts.verify_common import validate_source_commit  # noqa: E402


RECEIPT_PATH = Path("evidence/talon-milestone-2.json")
ALLOWED_RECEIPTS = (str(RECEIPT_PATH).replace("\\", "/"),)
REQUIRED_RECEIPT_KEYS = frozenset(
    {
        "receipt_version",
        "source_commit",
        "generated_at",
        "passed",
        "checks",
        "limitations",
    }
)
REQUIRED_EVIDENCE_RECEIPT_KEYS = frozenset(
    {
        "branch",
        "test_counts",
        "schema_versions",
        "scope",
        "environment_detail",
    }
)
REQUIRED_CHECK_KEYS = frozenset(
    {
        "dynamic_offline_rl",
        "physical_response_boundary",
        "milestone_1_receipt_unchanged",
        "td_backup_documentation",
        "frontier_integrity",
        "playwright",
        "product_hardenings",
        "bc_checkpoint_compatibility",
        "suite_verification",
        "receipt_completeness",
    }
)
SUITE_VERIFICATION_COMMAND_NAMES = (
    "talon_python",
    "complete_python",
    "dashboard_unit",
    "dashboard_lint",
    "dashboard_typecheck",
    "dashboard_build",
    "npm_audit",
    "compileall",
    "uv_lock",
    "diff_check",
    "cli_generate_dataset",
    "cli_train_gru",
    "cli_train_decision_transformer",
    "cli_train_cql",
    "cli_inspect_offline_dataset",
    "cli_inspect_offline_checkpoint",
    "cli_evaluate_cql",
)
REQUIRED_BC_ARCHITECTURES = frozenset({"gru", "decision_transformer"})
REQUIRED_BC_PROBE_KEYS = frozenset(
    {
        "valid_load",
        "missing_environment_rejected",
        "missing_verifier_rejected",
        "environment_mismatch_rejected",
        "verifier_mismatch_rejected",
        "action_schema_mismatch_rejected",
        "feature_schema_mismatch_rejected",
        "architecture_config_mismatch_rejected",
    }
)
REQUIRED_DYNAMIC_PROOF_KEYS = frozenset(
    {
        "immutable_record_rewrite_rejected",
        "caller_supplied_digest_is_not_provenance",
        "cross_run_substitution_rejected",
        "cross_dataset_substitution_rejected",
    }
)
REQUIRED_PRODUCT_HARDENING_KEYS = frozenset(
    {
        "policy_client_signature_absent",
        "product_policy_client_injection_rejected",
        "for_tests_helper_not_used_by_product",
        "expected_offline_dataset_digest_binding",
    }
)
REQUIRED_PRODUCT_HARDENING_CLASSIFICATIONS = {
    "policy_client_signature_absent": "static_source_inspection",
    "product_policy_client_injection_rejected": "dynamically_executed",
    "for_tests_helper_not_used_by_product": "static_source_inspection",
    "expected_offline_dataset_digest_binding": "dynamically_executed",
}
REQUIRED_PLAYWRIGHT_COMPONENTS = frozenset({"talon", "frontier", "complete"})
M1_RECEIPT = Path("evidence/talon-milestone-1.json")
FRONTIER_FREEZE_PATHS = ("src/training_ground", "src/strict_verifier")
PRODUCT_PATH_SCAN = (
    Path("src") / "drone_training" / "api.py",
    Path("src") / "drone_training" / "orchestration.py",
    Path("src") / "drone_training" / "worker.py",
    Path("src") / "drone_training" / "cli.py",
    Path("src") / "drone_training" / "persistence.py",
    Path("src") / "drone_training" / "offline_evaluation.py",
    Path("src") / "drone_training" / "offline_policy_isolation.py",
)
_PRIVATE_PATH_RE = re.compile(
    r"(?i)(?:[a-z]:\\users\\[^\\\"'\s]+|/users/[^/\"'\s]+|/home/[^/\"'\s]+)",
)
_TEMP_PATH_RE = re.compile(
    r"(?i)(?:[a-z]:\\users\\[^\\]+\\appdata\\local\\temp\\[^\\\"'\s]+|"
    r"/tmp/[^\\\"'\s]+|/var/folders/[^\\\"'\s]+|"
    r"[a-z]:\\temp\\[^\\\"'\s]+)",
)


def _python_executable() -> str:
    venv = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv.is_file():
        return str(venv)
    venv_unix = ROOT / ".venv" / "bin" / "python"
    if venv_unix.is_file():
        return str(venv_unix)
    return sys.executable


def _npm_executable() -> str:
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if npm is None:
        raise RuntimeError("npm is required for Talon Milestone 2 verification")
    return npm


def _uv_executable() -> str | None:
    return shutil.which("uv")


def _sanitize_text(text: str, *, temp_root: Path | None = None) -> str:
    sanitized = text
    if temp_root is not None:
        for candidate in {str(temp_root), str(temp_root.resolve())}:
            sanitized = sanitized.replace(candidate, "<temp>")
            sanitized = sanitized.replace(candidate.replace("\\", "/"), "<temp>")
    for candidate in {str(ROOT), str(ROOT.resolve())}:
        sanitized = sanitized.replace(candidate, ".")
        sanitized = sanitized.replace(candidate.replace("\\", "/"), ".")
    sanitized = _TEMP_PATH_RE.sub("<temp>", sanitized)
    sanitized = _PRIVATE_PATH_RE.sub("<user-home>", sanitized)
    return sanitized


def _render_command(command: list[str], *, temp_root: Path | None = None) -> str:
    executable = Path(command[0]).name
    lower = executable.lower()
    if lower.endswith(".exe") or lower.endswith(".cmd"):
        executable = executable.rsplit(".", 1)[0]
    if executable.lower().startswith("python"):
        executable = "python"
    rendered = subprocess.list2cmdline([executable, *command[1:]])
    return _sanitize_text(rendered, temp_root=temp_root)


def _test_count(output: str) -> int:
    cleaned = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output)
    patterns = (
        r"Tests\s+(\d+) passed",
        r"(\d+)\s+passed\s+\(",
        r"(\d+) passed",
    )
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            return int(match.group(1))
    return 0


def _playwright_report(output: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(output, index)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("stats"), dict):
            return value
    raise ValueError("Playwright JSON report was not produced")


def _extract_json_object(output: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(output, index)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _run_command(
    name: str,
    command: list[str],
    *,
    cwd: Path = ROOT,
    classification: str = "dynamically_executed",
    temp_root: Path | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    output = (result.stdout or "") + (result.stderr or "")
    record: dict[str, Any] = {
        "name": name,
        "command": _render_command(command, temp_root=temp_root),
        "exit_code": result.returncode,
        "passed": result.returncode == 0,
        "duration_seconds": round(time.monotonic() - started, 3),
        "classification": classification,
    }
    count = _test_count(output)
    if count or name in {"talon_python", "complete_python", "dashboard_unit"}:
        record["test_count"] = count
    record["_stdout"] = output
    return record


def _git(*arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def _git_quiet(*arguments: str) -> bool:
    result = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def refuse_dirty_evidence(status: str) -> None:
    if status.strip():
        raise RuntimeError("Milestone 2 evidence generation requires a clean working tree")


def _m1_receipt_blob_identity(source_commit: str) -> dict[str, Any]:
    """Compare working-tree M1 receipt to the blob at ``source_commit`` via git object identity.

    Uses ``git hash-object`` vs ``git rev-parse <commit>:path`` rather than raw
    byte equality so CRLF/autocrlf differences do not falsely fail.
    """

    committed = subprocess.run(
        ["git", "rev-parse", f"{source_commit}:{M1_RECEIPT.as_posix()}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if committed.returncode != 0:
        return {
            "passed": False,
            "integrity_method": "git_blob_identity",
            "reason": "milestone-1 receipt missing from source commit",
            "classification": "git_blob_identity",
        }
    committed_oid = committed.stdout.strip()
    working = subprocess.run(
        ["git", "hash-object", str(ROOT / M1_RECEIPT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if working.returncode != 0:
        return {
            "passed": False,
            "integrity_method": "git_blob_identity",
            "reason": "milestone-1 receipt missing from working tree",
            "classification": "git_blob_identity",
        }
    working_oid = working.stdout.strip()
    quiet_match = _git_quiet("diff", "--quiet", source_commit, "--", M1_RECEIPT.as_posix())
    return {
        "passed": working_oid == committed_oid,
        "integrity_method": "git_blob_identity",
        "working_oid": working_oid,
        "committed_oid": committed_oid,
        "git_diff_quiet": quiet_match,
        "classification": "git_blob_identity",
    }


def _frontier_integrity(source_commit: str) -> dict[str, Any]:
    """Frontier scoring freeze: training_ground / strict_verifier unchanged vs HEAD."""

    freeze_clean = _git_quiet("diff", "--quiet", "HEAD", "--", *FRONTIER_FREEZE_PATHS)
    evidence_clean = _git_quiet("diff", "--quiet", "HEAD", "--", "evidence")
    m1 = _m1_receipt_blob_identity(source_commit)
    return {
        "passed": freeze_clean and evidence_clean and m1["passed"],
        "integrity_method": "git_blob_identity",
        "frontier_scoring_freeze": {
            "passed": freeze_clean,
            "paths": list(FRONTIER_FREEZE_PATHS),
            "note": "Frontier scoring freeze via training_ground/strict_verifier unchanged",
            "classification": "git_diff",
        },
        "evidence_tree_unchanged": {
            "passed": evidence_clean,
            "classification": "git_diff",
        },
        "milestone_1_receipt": m1,
        "classification": "git_integrity",
    }


def _source_scan() -> dict[str, Any]:
    roots = (
        ROOT / "src" / "drone_training",
        ROOT / "src" / "drone_decision_ground",
        ROOT / "src" / "drone_decision_verifier",
        ROOT / "src" / "talon_policy_runtime",
        ROOT / "apps" / "dashboard" / "app" / "talon",
    )
    paths = sorted(
        path
        for root in roots
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".py", ".ts", ".tsx"}
    )
    source = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in paths)
    forbidden = (
        "jammer.activate", "intercept_target", "physical_engagement", "countermeasure.deploy",
        "weapon", "fire_control", "hardware_control",
    )
    hits = [item for item in forbidden if item in source.lower()]
    return {
        "passed": not hits,
        "forbidden_hits": hits,
        "files_scanned": len(paths),
        "classification": "static_source_scan",
    }


def _td_backup_documentation() -> dict[str, Any]:
    """Prove docs explicitly state TD backup is mask-aware, not safety-threshold-aware."""

    docs = [
        ROOT / "docs" / "talon-milestone-2.md",
        ROOT / "src" / "drone_training" / "offline_rl.py",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in docs if path.is_file())
    has_heading = "mask-aware, not safety-threshold-aware" in text or "public-mask-aware, not safety-threshold-aware" in text
    has_masked_max = "masked_max_q" in text
    has_selection_note = "not inside the TD max" in text or "runtime action selection" in text
    has_gate = "policy gate" in text.lower()
    return {
        "passed": has_heading and has_masked_max and has_selection_note and has_gate,
        "checks": {
            "contract_documented": has_heading,
            "mentions_masked_max_q": has_masked_max,
            "selection_vs_td_distinguished": has_selection_note,
            "mentions_policy_gate": has_gate,
        },
        "classification": "documentation_scan",
    }


def _parse_playwright_list_count(stdout: str) -> int:
    match = re.search(r"Total:\s*(\d+)\s+tests?", stdout)
    if match is None:
        raise ValueError("could not parse Playwright --list total")
    return int(match.group(1))


def _list_playwright_suite(spec: str | None) -> dict[str, Any]:
    """List Playwright tests without executing them (check-only / dirty-tree safe)."""

    dashboard = ROOT / "apps" / "dashboard"
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if npx is None:
        raise RuntimeError("npx is required to list Playwright suites")
    command = [npx, "playwright", "test", "--list", "--reporter=line"]
    if spec is not None:
        command.append(spec)
    result = subprocess.run(
        command,
        cwd=dashboard,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    if result.returncode != 0:
        raise RuntimeError(f"Playwright --list failed for {spec or 'e2e'}: {combined[-500:]}")
    count = _parse_playwright_list_count(combined)
    display = _render_command(command)
    return {
        "count": count,
        "result": "listed_only",
        "command": display,
        "skipped": 0,
    }


def _run_playwright_suite(name: str, npm: str, *, spec: str | None = None) -> dict[str, Any]:
    """Execute one Playwright suite with Chromium JSON reporting (evidence mode)."""

    command = [
        npm,
        "run",
        "test:e2e",
        "--",
        "--browser=chromium",
        "--reporter=json",
        "--workers=1",
    ]
    if spec is not None:
        command.append(spec)
    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=ROOT / "apps" / "dashboard",
        capture_output=True,
        text=True,
        check=False,
    )
    output = (result.stdout or "") + (result.stderr or "")
    try:
        stats = _playwright_report(output)["stats"]
        expected = int(stats.get("expected", 0))
        unexpected = int(stats.get("unexpected", 0))
        flaky = int(stats.get("flaky", 0))
        skipped = int(stats.get("skipped", 0))
        report_valid = True
    except (TypeError, ValueError, KeyError):
        expected = unexpected = flaky = skipped = 0
        report_valid = False
    count = expected + unexpected + flaky + skipped
    passed = result.returncode == 0 and report_valid and skipped == 0
    return {
        "count": count,
        "skipped": skipped,
        "result": "dynamically_executed",
        "command": _render_command(command),
        "duration_seconds": round(time.monotonic() - started, 3),
        "exit_code": result.returncode,
        "passed": passed,
        "report_valid": report_valid,
        "name": name,
    }


def _playwright_checks(*, list_only: bool) -> dict[str, Any]:
    """Populate Playwright receipt fields.

    ``--check-only`` prefers ``--list`` counts (``listed_only``) so dirty trees
    stay fast and evidence is never written. Full evidence mode executes Chromium
    sequentially for talon, frontier, and complete suites.
    """

    note = (
        "Full evidence mode requires executed Playwright results with workers=1 "
        "and skipped=0; --check-only populates counts via playwright test --list."
    )
    if not list_only:
        try:
            npm = _npm_executable()
            talon = _run_playwright_suite("talon", npm, spec="e2e/talon.spec.ts")
            frontier = _run_playwright_suite(
                "frontier", npm, spec="e2e/scripted-evaluation.spec.ts"
            )
            complete = _run_playwright_suite("complete", npm)
        except (RuntimeError, ValueError, subprocess.TimeoutExpired, OSError) as exc:
            return {
                "passed": False,
                "browser": "chromium",
                "workers": 1,
                "skipped": 0,
                "result": "dynamically_executed",
                "real_browser": True,
                "note": note,
                "error": _sanitize_text(str(exc)),
                "classification": "dynamically_executed",
            }

        components = {"talon": talon, "frontier": frontier, "complete": complete}
        missing = sorted(REQUIRED_PLAYWRIGHT_COMPONENTS - set(components))
        skipped_total = max(int(components[key].get("skipped", 0)) for key in REQUIRED_PLAYWRIGHT_COMPONENTS)
        counts_present = all(
            isinstance(components[key].get("count"), int) for key in REQUIRED_PLAYWRIGHT_COMPONENTS
        )
        consistent = (
            counts_present
            and components["talon"]["count"] + components["frontier"]["count"]
            == components["complete"]["count"]
        )
        all_passed = all(bool(components[key].get("passed")) for key in REQUIRED_PLAYWRIGHT_COMPONENTS)
        report_valid = all(bool(components[key].get("report_valid")) for key in REQUIRED_PLAYWRIGHT_COMPONENTS)
        exit_ok = all(int(components[key].get("exit_code", 1)) == 0 for key in REQUIRED_PLAYWRIGHT_COMPONENTS)
        passed = (
            not missing
            and all_passed
            and report_valid
            and exit_ok
            and skipped_total == 0
            and consistent
        )
        return {
            "passed": passed,
            "browser": "chromium",
            "workers": 1,
            "skipped": skipped_total,
            "result": "dynamically_executed",
            "real_browser": True,
            "note": note,
            "component_count_consistent": consistent,
            "missing_components": missing,
            "talon": {
                key: talon[key]
                for key in (
                    "count",
                    "skipped",
                    "result",
                    "command",
                    "duration_seconds",
                    "exit_code",
                    "passed",
                )
            },
            "frontier": {
                key: frontier[key]
                for key in (
                    "count",
                    "skipped",
                    "result",
                    "command",
                    "duration_seconds",
                    "exit_code",
                    "passed",
                )
            },
            "complete": {
                key: complete[key]
                for key in (
                    "count",
                    "skipped",
                    "result",
                    "command",
                    "duration_seconds",
                    "exit_code",
                    "passed",
                )
            },
            "classification": "dynamically_executed",
        }

    try:
        talon = _list_playwright_suite("e2e/talon.spec.ts")
        frontier = _list_playwright_suite("e2e/scripted-evaluation.spec.ts")
        complete = _list_playwright_suite(None)
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        return {
            "passed": False,
            "browser": "chromium",
            "workers": 1,
            "skipped": 0,
            "result": "listed_only",
            "note": note,
            "error": str(exc),
            "classification": "playwright_list",
        }

    components = {"talon": talon, "frontier": frontier, "complete": complete}
    missing = sorted(REQUIRED_PLAYWRIGHT_COMPONENTS - set(components))
    counts_present = all(isinstance(components[key].get("count"), int) for key in REQUIRED_PLAYWRIGHT_COMPONENTS)
    skipped_ok = all(int(components[key].get("skipped", -1)) == 0 for key in REQUIRED_PLAYWRIGHT_COMPONENTS)
    consistent = (
        counts_present
        and components["talon"]["count"] + components["frontier"]["count"] == components["complete"]["count"]
    )
    passed = not missing and counts_present and skipped_ok and consistent
    return {
        "passed": passed,
        "browser": "chromium",
        "workers": 1,
        "skipped": 0,
        "result": "listed_only",
        "note": note,
        "component_count_consistent": consistent,
        "missing_components": missing,
        "talon": talon,
        "frontier": frontier,
        "complete": complete,
        "classification": "playwright_list",
    }


def _validate_playwright_section(section: Any) -> list[str]:
    """Return schema problems for a playwright receipt block."""

    problems: list[str] = []
    if not isinstance(section, dict):
        return ["playwright section missing or not an object"]
    for key in ("browser", "workers", "skipped", "result"):
        if key not in section:
            problems.append(f"playwright.{key} missing")
    if section.get("browser") != "chromium":
        problems.append("playwright.browser must be chromium")
    if section.get("workers") != 1:
        problems.append("playwright.workers must be 1")
    if section.get("skipped") not in (0,):
        problems.append("playwright.skipped must be 0")
    executed = section.get("result") == "dynamically_executed"
    if executed:
        if section.get("real_browser") is not True:
            problems.append("playwright.real_browser must be true")
        if section.get("classification") != "dynamically_executed":
            problems.append("playwright.classification must be dynamically_executed")
    for name in REQUIRED_PLAYWRIGHT_COMPONENTS:
        component = section.get(name)
        if not isinstance(component, dict):
            problems.append(f"playwright.{name} missing")
            continue
        for field in ("count", "result", "command"):
            if field not in component:
                problems.append(f"playwright.{name}.{field} missing")
        if component.get("count") is None:
            problems.append(f"playwright.{name}.count missing")
        if int(component.get("skipped", 0) or 0) != 0:
            problems.append(f"playwright.{name}.skipped nonzero")
        if executed:
            for field in ("duration_seconds", "exit_code", "passed"):
                if field not in component:
                    problems.append(f"playwright.{name}.{field} missing")
            if component.get("result") != "dynamically_executed":
                problems.append(f"playwright.{name}.result must be dynamically_executed")
    if all(isinstance(section.get(name), dict) and isinstance(section[name].get("count"), int) for name in REQUIRED_PLAYWRIGHT_COMPONENTS):
        talon_n = section["talon"]["count"]
        frontier_n = section["frontier"]["count"]
        complete_n = section["complete"]["count"]
        if talon_n + frontier_n != complete_n:
            problems.append("playwright talon+frontier != complete when suites are disjoint")
    return problems


def _field(passed: bool, classification: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"passed": bool(passed), "classification": classification}
    payload.update(extra)
    return payload


def _field_passed(entry: Any) -> bool:
    if isinstance(entry, dict):
        return bool(entry.get("passed"))
    return bool(entry)


def _scan_product_paths_for_symbol(symbol: str) -> dict[str, Any]:
    """Static import/call scan of product modules for a forbidden helper symbol.

    The definition of ``evaluate_offline_checkpoint_for_tests`` inside
    ``offline_evaluation.py`` is allowed; any other mention (import, call, or
    reference) in product modules is a hit.
    """

    hits: list[str] = []
    for relative in PRODUCT_PATH_SCAN:
        path = ROOT / relative
        if not path.is_file():
            hits.append(f"missing:{relative.as_posix()}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if symbol not in text:
            continue
        if relative.name == "offline_evaluation.py":
            for line_number, line in enumerate(text.splitlines(), start=1):
                if symbol not in line:
                    continue
                stripped = line.lstrip()
                if stripped.startswith(f"def {symbol}"):
                    continue
                if stripped.startswith("#"):
                    continue
                hits.append(f"{relative.as_posix()}:{line_number}")
            continue
        hits.append(relative.as_posix())
    return {
        "passed": not hits,
        "symbol": symbol,
        "product_path_hits": hits,
        "classification": "static_source_inspection",
    }


def _product_hardenings() -> dict[str, Any]:
    """Product hardening probes with per-check classification (static + dynamic)."""

    checks: dict[str, Any] = {}
    notes: dict[str, str] = {}

    try:
        from pydantic import ValidationError

        from drone_training.bindings import (
            BindingSource,
            TrustedCheckpointBinding,
            logical_checkpoint_identity,
            resolve_bound_checkpoint,
        )
        from drone_training.offline_evaluation import (
            evaluate_offline_checkpoint,
            evaluate_offline_checkpoint_for_tests,
        )
        from drone_training.persistence import TalonStore
        from drone_training.schemas import EvaluationCreate
        from drone_training.worker import run_job
    except ImportError as exc:
        return {
            "passed": False,
            "checks": {
                "imports_available": _field(False, "dynamically_executed", error=str(exc)),
            },
            "notes": {"imports_available": str(exc)},
        }

    checks["imports_available"] = _field(True, "dynamically_executed")

    # Static: public evaluate_offline_checkpoint must not expose policy_client.
    signature = inspect.signature(evaluate_offline_checkpoint)
    checks["policy_client_signature_absent"] = _field(
        "policy_client" not in signature.parameters,
        "static_source_inspection",
    )

    # Static: test-only helper exists but is not wired into product API/orchestration.
    for_tests_exists = callable(evaluate_offline_checkpoint_for_tests)
    for_tests_sig = inspect.signature(evaluate_offline_checkpoint_for_tests)
    for_tests_accepts_client = "policy_client" in for_tests_sig.parameters
    product_isolation = _scan_product_paths_for_symbol("evaluate_offline_checkpoint_for_tests")
    checks["for_tests_helper_not_used_by_product"] = _field(
        for_tests_exists and for_tests_accepts_client and product_isolation["passed"],
        "static_source_inspection",
        for_tests_exists=for_tests_exists,
        for_tests_accepts_policy_client=for_tests_accepts_client,
        product_path_hits=product_isolation["product_path_hits"],
    )

    # Dynamic: policy_client injection rejected across API schema, worker, and for_tests.
    injection_probes: dict[str, Any] = {}

    try:
        EvaluationCreate(  # type: ignore[call-arg]
            training_run_id="talon_cql_" + ("0" * 32),
            policy_client="injected",
        )
        injection_probes["evaluation_create_rejects_policy_client"] = _field(
            False,
            "dynamically_executed",
            reason="EvaluationCreate accepted policy_client",
        )
    except ValidationError:
        injection_probes["evaluation_create_rejects_policy_client"] = _field(
            True,
            "dynamically_executed",
        )
    except Exception as exc:  # noqa: BLE001 — any rejection of the extra field is acceptable
        injection_probes["evaluation_create_rejects_policy_client"] = _field(
            True,
            "dynamically_executed",
            rejected_as=type(exc).__name__,
        )

    # Also reject when constructing from a dict payload (API-shaped).
    try:
        EvaluationCreate.model_validate(
            {
                "training_run_id": "talon_cql_" + ("0" * 32),
                "policy_client": {"foreign": True},
                "extra_inject": 1,
            }
        )
        injection_probes["evaluation_create_payload_rejects_extras"] = _field(
            False,
            "dynamically_executed",
            reason="EvaluationCreate accepted unknown fields",
        )
    except ValidationError:
        injection_probes["evaluation_create_payload_rejects_extras"] = _field(
            True,
            "dynamically_executed",
        )

    with tempfile.TemporaryDirectory() as temporary:
        import multiprocessing as mp

        context = mp.get_context("spawn")
        queue = context.Queue()
        cancelled = context.Event()
        worker_request = {
            "training_run_id": "talon_cql_" + ("w" * 32),
            "checkpoint_digest": "sha256:" + ("a" * 64),
            "artifact_identity": logical_checkpoint_identity("talon_cql_" + ("w" * 32)),
            "seed_start": 0,
            "seed_count": 1,
            "timeout_seconds": 5,
            "application_commit": "probe",
            "policy_client": "injected",
        }
        paths = {
            "data_root": temporary,
            "checkpoint": str(Path(temporary) / "missing.pt"),
            "private_evaluation": str(Path(temporary) / "private" / "eval" / "verification.json"),
            "dataset": str(Path(temporary) / "missing.pt"),
        }
        run_job("offline_evaluation", worker_request, paths, queue, cancelled)
        message = queue.get(timeout=30)
        worker_failed = message.get("type") == "failed"
        worker_category = str((message.get("data") or {}).get("error_category") or "")
        worker_source = inspect.getsource(run_job)
        worker_guard_present = (
            'if "policy_client" in request:' in worker_source
            and "cannot inject a policy client" in worker_source
        )
        # Failure payloads intentionally omit exception text; prove the guard via
        # source + that a policy_client-bearing request fails closed immediately.
        injection_probes["worker_rejects_policy_client_key"] = _field(
            worker_failed
            and worker_category == "offline_evaluation_failure"
            and worker_guard_present,
            "dynamically_executed",
            error_category=worker_category,
            guard_present_in_run_job_source=worker_guard_present,
        )

        # Foreign-weight client via for_tests helper (needs a real checkpoint).
        try:
            from drone_training.datasets import generate_dataset
            from drone_training.offline_checkpoints import load_offline_checkpoint, save_offline_checkpoint
            from drone_training.offline_rl import CQLConfig, derive_offline_dataset, train_discrete_cql

            source = generate_dataset(partition="train", seeds=[0], families=["authorised_inspection"])
            offline = derive_offline_dataset(source, context_length=4)
            config = CQLConfig(
                context_length=4,
                hidden_dim=8,
                layers=1,
                dropout=0,
                batch_size=16,
                epochs=1,
                target_update_interval=2,
                random_seed=11,
            )
            model, target, history = train_discrete_cql(offline, config)
            updates = int(history.pop("training_updates", [0.0])[-1]) if "training_updates" in history else 1
            ckpt_path = Path(temporary) / "hardening_checkpoint.pt"
            digest = save_offline_checkpoint(
                ckpt_path,
                model=model,
                target=target,
                dataset=offline,
                config=config,
                training_history=history if history else {"loss": [0.1]},
                training_updates=max(updates, 1),
            )

            class _ForeignClient:
                expected_digest = "sha256:" + ("f" * 64)
                profile_id = "uk_monitor_and_escalate"
                last_diagnostics: dict[str, Any] = {}

                def reset(self) -> None:
                    return None

                def recommend(self, observation):  # noqa: ANN001
                    raise AssertionError("foreign client must not be used")

                def close(self) -> None:
                    return None

            foreign_rejected = False
            try:
                evaluate_offline_checkpoint_for_tests(
                    ckpt_path,
                    family="authorised_inspection",
                    seed=0,
                    partition="evaluation",
                    expected_checkpoint_digest=digest,
                    policy_client=_ForeignClient(),
                )
            except ValueError as exc:
                foreign_rejected = "does not match" in str(exc).lower() or "digest" in str(exc).lower()
            injection_probes["foreign_weight_client_rejected"] = _field(
                foreign_rejected,
                "dynamically_executed",
            )

            # Evaluation-time expected_offline_dataset_digest binding (forged record).
            source_b = generate_dataset(partition="train", seeds=[1], families=["bird_false_positive"])
            offline_b = derive_offline_dataset(source_b, context_length=4)
            store = TalonStore(Path(temporary) / "talon.sqlite3")
            try:
                run_id = "talon_cql_" + ("d" * 32)
                record = _completed_training_record(
                    store,
                    run_id,
                    digest,
                    ckpt_path,
                    offline_dataset_digest=offline.manifest.dataset_digest,
                    source_dataset_digest=offline.manifest.source_dataset_digest,
                )
                forged = TrustedCheckpointBinding(
                    training_run_id=run_id,
                    checkpoint_id=run_id,
                    trusted_digest=digest,
                    artifact_identity=logical_checkpoint_identity(run_id),
                    binding_source=BindingSource.IMMUTABLE_DB_RECORD,
                    offline_dataset_digest=offline_b.manifest.dataset_digest,
                    source_dataset_digest=offline_b.manifest.source_dataset_digest,
                )
                forged_rejected = False
                try:
                    evaluate_offline_checkpoint(
                        binding=forged,
                        private_root=store.private_dir,
                        family="authorised_inspection",
                        seed=0,
                        partition="evaluation",
                        timeout_seconds=5,
                    )
                except ValueError as exc:
                    forged_rejected = "dataset" in str(exc).lower() and "mismatch" in str(exc).lower()

                fake = "sha256:" + ("ab" * 32)
                load_rejected = False
                try:
                    load_offline_checkpoint(
                        ckpt_path,
                        expected_digest=digest,
                        expected_offline_dataset_digest=fake,
                        expected_source_dataset_digest=offline.manifest.source_dataset_digest,
                    )
                except ValueError as exc:
                    load_rejected = "offline-dataset binding mismatch" in str(exc)

                checks["expected_offline_dataset_digest_binding"] = _field(
                    forged_rejected
                    and load_rejected
                    and offline.manifest.dataset_digest != offline_b.manifest.dataset_digest
                    and record.get("offline_dataset_digest") == offline.manifest.dataset_digest,
                    "dynamically_executed",
                    forged_binding_rejected=forged_rejected,
                    load_forged_digest_rejected=load_rejected,
                )
            finally:
                store.close()
        except Exception as exc:  # noqa: BLE001
            injection_probes.setdefault(
                "foreign_weight_client_rejected",
                _field(False, "dynamically_executed", error=str(exc)),
            )
            checks["expected_offline_dataset_digest_binding"] = _field(
                False,
                "dynamically_executed",
                error=str(exc),
            )

    checks["product_policy_client_injection_rejected"] = _field(
        all(_field_passed(value) for value in injection_probes.values()),
        "dynamically_executed",
        probes=injection_probes,
    )

    # CLI operator-supplied digest is explicitly not immutable DB provenance.
    cli_binding = TrustedCheckpointBinding.cli_operator_supplied(
        training_run_id="talon_cql_" + ("c" * 32),
        trusted_digest="sha256:" + ("a" * 64),
    )
    checks["cli_binding_source_is_not_immutable_db"] = _field(
        cli_binding.binding_source == BindingSource.CLI_OPERATOR_SUPPLIED
        and cli_binding.binding_source != BindingSource.IMMUTABLE_DB_RECORD,
        "dynamically_executed",
    )
    notes["cli_binding_source_is_not_immutable_db"] = (
        "Raw CLI digest uses BindingSource.CLI_OPERATOR_SUPPLIED and is not claimed as DB provenance"
    )

    with tempfile.TemporaryDirectory() as temporary:
        store = TalonStore(Path(temporary) / "talon_cleanup.sqlite3")
        try:
            active_id = "talon_cql_" + ("i" * 32)
            store.create_record(
                active_id,
                "training",
                {
                    "schema_version": "talon.public-training-record/2.0",
                    "configuration": {},
                    "application_commit": "probe",
                },
                status="running",
            )
            private = store._private_directory(active_id)
            checkpoint = private / "checkpoint.pt"
            checkpoint.write_bytes(b"orphan-weights")
            (private / ".checkpoint.pt.partial").write_bytes(b"partial")
            interrupted = store.mark_active_interrupted()
            checks["mark_active_interrupted_cleans_orphan_checkpoints"] = _field(
                interrupted == 1
                and store.get(active_id) is not None
                and store.get(active_id)["status"] == "interrupted"  # type: ignore[index]
                and not checkpoint.exists()
                and not list(private.glob("*.partial")),
                "dynamically_executed",
            )

            try:
                TrustedCheckpointBinding(
                    training_run_id=active_id,
                    trusted_digest="sha256:" + ("b" * 64),
                    artifact_identity=f"../outside/{active_id}/checkpoint.pt",
                    binding_source=BindingSource.IMMUTABLE_DB_RECORD,
                )
                checks["artifact_identity_rejects_traversal"] = _field(False, "dynamically_executed")
            except ValueError as exc:
                checks["artifact_identity_rejects_traversal"] = _field(
                    "artifact identity" in str(exc).lower() or "traversal" in str(exc).lower(),
                    "dynamically_executed",
                )

            forged_missing = TrustedCheckpointBinding(
                training_run_id=active_id,
                trusted_digest="sha256:" + ("b" * 64),
                artifact_identity=logical_checkpoint_identity(active_id),
                binding_source=BindingSource.IMMUTABLE_DB_RECORD,
            )
            try:
                resolve_bound_checkpoint(store.private_dir, forged_missing, require_digest_match=True)
                checks["resolve_bound_checkpoint_rejects_missing"] = _field(False, "dynamically_executed")
            except ValueError:
                checks["resolve_bound_checkpoint_rejects_missing"] = _field(True, "dynamically_executed")
        finally:
            store.close()

    return {
        "passed": all(_field_passed(value) for value in checks.values()),
        "checks": checks,
        "notes": notes,
    }


def _completed_training_record(
    store: Any,
    run_id: str,
    digest: str,
    checkpoint_src: Path,
    *,
    offline_dataset_digest: str | None = None,
    source_dataset_digest: str | None = None,
) -> dict[str, Any]:
    from drone_training.bindings import logical_checkpoint_identity

    store.create_record(
        run_id,
        "training",
        {
            "schema_version": "talon.public-training-record/2.0",
            "configuration": {"dataset_id": "dataset_" + ("0" * 24)},
            "application_commit": "milestone-2-verifier",
            "architecture": "cql_gru",
            "algorithm": "discrete_cql",
        },
        status="running",
    )
    private = store._private_directory(run_id)
    shutil.copyfile(checkpoint_src, private / "checkpoint.pt")
    result: dict[str, Any] = {
        "model_id": run_id,
        "checkpoint_digest": digest,
        "artifact_identity": logical_checkpoint_identity(run_id),
        "architecture": "cql_gru",
        "algorithm": "discrete_cql",
    }
    if offline_dataset_digest is not None:
        result["offline_dataset_digest"] = offline_dataset_digest
    if source_dataset_digest is not None:
        result["dataset_digest"] = source_dataset_digest
    completed = store.try_complete_with_checkpoint(run_id, result=result)
    if completed is None:
        raise RuntimeError(f"failed to complete training record {run_id}")
    record = store.get(run_id)
    if record is None:
        raise RuntimeError(f"missing completed training record {run_id}")
    return record


def _dynamic_checks() -> dict[str, Any]:
    import torch

    from drone_decision_ground.actions import DecisionAction
    from drone_decision_verifier.leak_detection import find_public_leaks
    from drone_training.bindings import (
        BindingSource,
        TrustedCheckpointBinding,
        assert_product_checkpoint_usable,
        logical_checkpoint_identity,
        resolve_bound_checkpoint,
    )
    from drone_training.datasets import generate_dataset
    from drone_training.offline_checkpoints import (
        inspect_offline_checkpoint,
        load_offline_checkpoint,
        save_offline_checkpoint,
    )
    from drone_training.offline_evaluation import evaluate_offline_checkpoint
    from drone_training.offline_rl import (
        CQLConfig,
        OfflineRLDataset,
        derive_offline_dataset,
        masked_argmax,
        recompute_offline_dataset_digest,
        train_discrete_cql,
        verify_offline_dataset_integrity,
    )
    from drone_training.persistence import ACTIVE_STATUSES, TalonImmutableRecordError, TalonStore

    source = generate_dataset(partition="train", seeds=[0], families=["authorised_inspection"])
    offline = derive_offline_dataset(source, context_length=4)
    checks: dict[str, bool] = {
        "source_digest_recomputed": offline.manifest.source_dataset_digest == source.manifest.dataset_digest,
        "offline_digest_recomputed": recompute_offline_dataset_digest(offline) == offline.manifest.dataset_digest,
        "static_transitions_only": offline.manifest.transition_count == len(offline.transitions),
        "action_schema_has_13_actions": len(DecisionAction) == 13,
    }
    mutated = offline.model_dump(mode="json")
    mutated["transitions"][0]["operational_reward"] = .125
    try:
        verify_offline_dataset_integrity(OfflineRLDataset.model_validate(mutated))
        checks["mutation_rejected"] = False
    except ValueError:
        checks["mutation_rejected"] = True
    selected = masked_argmax(torch.ones((1, 13)), torch.ones((1, 13)), torch.ones((1, 13), dtype=torch.bool), .05)
    checks["empty_safe_set_abstains"] = int(selected[0]) == list(DecisionAction).index(DecisionAction.ABSTAIN_INSUFFICIENT_EVIDENCE)
    config = CQLConfig(context_length=4, hidden_dim=8, layers=1, dropout=0, batch_size=16, epochs=1, target_update_interval=2, random_seed=7)
    first, first_target, history = train_discrete_cql(offline, config)
    second, second_target, _ = train_discrete_cql(offline, config)
    checks["deterministic_training"] = all(
        torch.equal(first.state_dict()[key], second.state_dict()[key]) for key in first.state_dict()
    ) and all(torch.equal(first_target.state_dict()[key], second_target.state_dict()[key]) for key in first_target.state_dict())
    public_manifest = {
        "schema_version": offline.schema_version,
        "dataset_digest": offline.manifest.dataset_digest,
        "transition_count": offline.manifest.transition_count,
    }
    checks["public_probe_has_no_hidden_state"] = find_public_leaks(public_manifest) == []

    # Second dataset / training for cross-run and cross-dataset proofs.
    source_b = generate_dataset(partition="train", seeds=[1], families=["authorised_inspection"])
    offline_b = derive_offline_dataset(source_b, context_length=4)
    config_b = CQLConfig(context_length=4, hidden_dim=8, layers=1, dropout=0, batch_size=16, epochs=1, target_update_interval=2, random_seed=99)
    model_b, target_b, history_b = train_discrete_cql(offline_b, config_b)
    checks["distinct_offline_dataset_digests"] = offline.manifest.dataset_digest != offline_b.manifest.dataset_digest

    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "checkpoint.pt"
        updates = int(history.pop("training_updates", [0.0])[-1]) if "training_updates" in history else 1
        digest = save_offline_checkpoint(
            path,
            model=first,
            target=first_target,
            dataset=offline,
            config=config,
            training_history=history if history else {"loss": [0.1]},
            training_updates=max(updates, 1),
        )
        path_b = Path(temporary) / "checkpoint_b.pt"
        updates_b = int(history_b.pop("training_updates", [0.0])[-1]) if "training_updates" in history_b else 1
        digest_b = save_offline_checkpoint(
            path_b,
            model=model_b,
            target=target_b,
            dataset=offline_b,
            config=config_b,
            training_history=history_b if history_b else {"loss": [0.1]},
            training_updates=max(updates_b, 1),
        )
        checks["distinct_checkpoint_digests"] = digest != digest_b

        # eval/inspect requires a trusted expected digest from the caller.
        try:
            load_offline_checkpoint(path)  # type: ignore[call-arg]
            checks["eval_requires_trusted_digest"] = False
        except TypeError:
            checks["eval_requires_trusted_digest"] = True
        try:
            inspect_offline_checkpoint(path)  # type: ignore[call-arg]
            checks["inspect_requires_trusted_digest"] = False
        except TypeError:
            checks["inspect_requires_trusted_digest"] = True
        load_sig = inspect.signature(load_offline_checkpoint)
        inspect_sig = inspect.signature(inspect_offline_checkpoint)
        checks["load_expected_digest_required"] = (
            "expected_digest" in load_sig.parameters
            and load_sig.parameters["expected_digest"].default is inspect.Parameter.empty
        )
        checks["inspect_expected_digest_required"] = (
            "expected_digest" in inspect_sig.parameters
            and inspect_sig.parameters["expected_digest"].default is inspect.Parameter.empty
        )

        model, target, metadata = load_offline_checkpoint(path, expected_digest=digest)
        checks["target_net_present_in_schema"] = (
            "target_state_dict" not in metadata
            and "online_state_dict" not in metadata
            and all(torch.equal(a, b) for a, b in zip(target.parameters(), first_target.parameters()))
            and metadata.get("format_version") == "talon.offline-rl-checkpoint/2.0"
        )
        payload = torch.load(path, map_location="cpu", weights_only=True)
        checks["target_net_keys_on_disk"] = (
            isinstance(payload.get("online_state_dict"), dict)
            and isinstance(payload.get("target_state_dict"), dict)
            and set(payload["online_state_dict"]) == set(payload["target_state_dict"])
        )
        from drone_decision_ground.environment import ENVIRONMENT_VERSION
        from drone_decision_verifier.scoring import VERIFIER_VERSION

        checks["environment_verifier_versions_bound"] = (
            payload.get("environment_version") == ENVIRONMENT_VERSION
            and payload.get("verifier_version") == VERIFIER_VERSION
            and metadata.get("environment_version") == ENVIRONMENT_VERSION
            and metadata.get("verifier_version") == VERIFIER_VERSION
        )

        # Incomplete target rejected.
        bad = Path(temporary) / "incomplete.pt"
        truncated = dict(payload)
        truncated["target_state_dict"] = {key: value for key, value in list(payload["target_state_dict"].items())[:1]}
        torch.save(truncated, bad)
        bad_digest = "sha256:" + hashlib.sha256(bad.read_bytes()).hexdigest()
        try:
            load_offline_checkpoint(bad, expected_digest=bad_digest)
            checks["incomplete_target_rejected"] = False
        except ValueError:
            checks["incomplete_target_rejected"] = True

        store = TalonStore(Path(temporary) / "talon.sqlite3")
        try:
            run_a = "talon_cql_" + ("a" * 32)
            run_b = "talon_cql_" + ("b" * 32)
            record_a = _completed_training_record(
                store,
                run_a,
                digest,
                path,
                offline_dataset_digest=offline.manifest.dataset_digest,
                source_dataset_digest=offline.manifest.source_dataset_digest,
            )
            record_b = _completed_training_record(
                store,
                run_b,
                digest_b,
                path_b,
                offline_dataset_digest=offline_b.manifest.dataset_digest,
                source_dataset_digest=offline_b.manifest.source_dataset_digest,
            )
            checks["two_completed_runs_distinct"] = (
                record_a["checkpoint_digest"] != record_b["checkpoint_digest"]
                and record_a.get("offline_dataset_digest") != record_b.get("offline_dataset_digest")
            )

            def _overwrite_checkpoint(destination: Path, source: Path) -> None:
                try:
                    destination.chmod(0o600)
                except OSError:
                    pass
                shutil.copyfile(source, destination)
                try:
                    destination.chmod(0o444)
                except OSError:
                    pass

            # --- immutable_record_rewrite_rejected ---
            # True rewrite of bytes + recomputed attacker digest, but evaluation trust
            # anchor remains the immutable DB completed record's original digest.
            rewrite_path = store.private_dir / run_a / "checkpoint.pt"
            original_digest = str(record_a["checkpoint_digest"])
            rewrite_payload = torch.load(rewrite_path, map_location="cpu", weights_only=False)
            for key, tensor in list(rewrite_payload["online_state_dict"].items()):
                rewrite_payload["online_state_dict"][key] = tensor + 0.001
            for key, tensor in list(rewrite_payload["target_state_dict"].items()):
                rewrite_payload["target_state_dict"][key] = tensor + 0.001
            rewrite_payload["final_training_metrics"] = {
                **(rewrite_payload.get("final_training_metrics") or {}),
                "attacker": 1.0,
            }
            rewrite_path.chmod(0o600)
            torch.save(rewrite_payload, rewrite_path)
            rewrite_path.chmod(0o444)
            attacker_digest = "sha256:" + hashlib.sha256(rewrite_path.read_bytes()).hexdigest()
            checks["attacker_digest_differs_from_record"] = attacker_digest != original_digest
            rewrite_rejected = False
            try:
                assert_product_checkpoint_usable(store.private_dir, record_a)
            except ValueError as exc:
                rewrite_rejected = "digest mismatch" in str(exc)
            if not rewrite_rejected:
                try:
                    binding = TrustedCheckpointBinding.from_completed_training(record_a)
                    evaluate_offline_checkpoint(
                        binding=binding,
                        private_root=store.private_dir,
                        family="authorised_inspection",
                        seed=0,
                        partition="evaluation",
                        timeout_seconds=5,
                    )
                except ValueError as exc:
                    rewrite_rejected = "digest mismatch" in str(exc)
                except Exception:
                    rewrite_rejected = False
            checks["immutable_record_rewrite_rejected"] = (
                rewrite_rejected and checks["attacker_digest_differs_from_record"]
            )
            try:
                store.update(run_a, "completed", {"checkpoint_digest": attacker_digest})
                checks["immutable_record_digest_unwritable"] = False
            except TalonImmutableRecordError:
                checks["immutable_record_digest_unwritable"] = True

            # Restore authentic A checkpoint for subsequent probes.
            _overwrite_checkpoint(rewrite_path, path)

            # --- caller_supplied_digest_is_not_provenance ---
            cli_binding = TrustedCheckpointBinding.cli_operator_supplied(
                training_run_id=run_a,
                trusted_digest=attacker_digest,
            )
            cli_docs = (
                (ROOT / "docs" / "talon-milestone-2.md").read_text(encoding="utf-8")
                if (ROOT / "docs" / "talon-milestone-2.md").is_file()
                else ""
            )
            cli_help_ok = False
            try:
                from drone_training.cli import build_parser

                parser = build_parser()
                evaluate_help = parser.format_help()
                subparsers = getattr(parser, "_subparsers", None)
                if subparsers is not None:
                    for action in subparsers._group_actions:
                        for name, sub in action.choices.items():
                            if name in {"evaluate-cql", "evaluate"}:
                                evaluate_help += "\n" + sub.format_help()
                cli_help_ok = (
                    "immutable" in evaluate_help.lower()
                    or "operator-supplied" in evaluate_help.lower()
                    or "cli_operator_supplied" in evaluate_help.lower()
                )
            except Exception:
                cli_help_ok = "cli_operator_supplied" in cli_docs or "operator-supplied" in cli_docs.lower()
            checks["caller_supplied_digest_is_not_provenance"] = (
                cli_binding.binding_source == BindingSource.CLI_OPERATOR_SUPPLIED
                and cli_binding.binding_source != BindingSource.IMMUTABLE_DB_RECORD
                and (cli_help_ok or "provenance" in cli_docs.lower() or "operator-supplied" in cli_docs.lower())
            )

            # --- cross_run_substitution_rejected ---
            run_b_ckpt = store.private_dir / run_b / "checkpoint.pt"
            _overwrite_checkpoint(run_b_ckpt, path)  # A's weights under B's path
            cross_run_rejected = False
            try:
                assert_product_checkpoint_usable(store.private_dir, record_b)
            except ValueError as exc:
                cross_run_rejected = "digest mismatch" in str(exc)
            if not cross_run_rejected:
                try:
                    load_offline_checkpoint(path, expected_digest=digest_b)
                except ValueError as exc:
                    cross_run_rejected = "digest mismatch" in str(exc)
            binding_a = TrustedCheckpointBinding.from_completed_training(record_a)
            resolved_a = resolve_bound_checkpoint(store.private_dir, binding_a, require_digest_match=True)
            path_ok = resolved_a.parent.name == run_a
            _overwrite_checkpoint(store.private_dir / run_a / "checkpoint.pt", path_b)
            try:
                assert_product_checkpoint_usable(store.private_dir, record_a)
                cross_run_eval = False
            except ValueError as exc:
                cross_run_eval = "digest mismatch" in str(exc)
            checks["cross_run_substitution_rejected"] = cross_run_rejected and path_ok and cross_run_eval
            _overwrite_checkpoint(run_b_ckpt, path_b)
            _overwrite_checkpoint(store.private_dir / run_a / "checkpoint.pt", path)

            # --- cross_dataset_substitution_rejected ---
            _overwrite_checkpoint(run_b_ckpt, path)  # dataset-A weights under dataset-B record
            cross_dataset_product = False
            try:
                assert_product_checkpoint_usable(store.private_dir, record_b)
            except ValueError as exc:
                cross_dataset_product = "digest mismatch" in str(exc)
            cross_dataset_payload = False
            try:
                load_offline_checkpoint(
                    path,
                    expected_digest=digest,
                    expected_offline_dataset_digest=offline_b.manifest.dataset_digest,
                )
            except ValueError as exc:
                cross_dataset_payload = (
                    "offline-dataset binding mismatch" in str(exc) or "dataset" in str(exc).lower()
                )
            checks["cross_dataset_substitution_rejected"] = cross_dataset_product and cross_dataset_payload
            _overwrite_checkpoint(run_b_ckpt, path_b)

            # Cancel cannot publish after losing the CAS race (probe store helper).
            cancel_id = "run_" + ("c" * 24)
            store.create_record(
                cancel_id,
                "training",
                {
                    "schema_version": "talon.public-training-record/2.0",
                    "configuration": {},
                    "progress": {"phase": "running"},
                },
            )
            store.update(cancel_id, "cancelling", {"progress": {"phase": "cancelling"}})
            lost = store.try_complete_with_checkpoint(
                cancel_id,
                result={"checkpoint_digest": digest},
                expected_statuses=frozenset({"queued", "running"}),
            )
            checks["cancel_blocks_complete_when_cancelling"] = lost is None
            won = store.try_complete_with_checkpoint(
                cancel_id,
                result={"checkpoint_digest": digest, "model_id": cancel_id},
                expected_statuses=ACTIVE_STATUSES,
            )
            checks["complete_can_win_over_soft_cancel"] = (
                won is not None and store.get(cancel_id)["status"] == "completed"
            )
            again = store.try_complete_with_checkpoint(cancel_id, result={"checkpoint_digest": digest})
            checks["second_complete_rejected"] = again is None
        finally:
            store.close()

    return {"passed": all(checks.values()), "checks": checks, "classification": "dynamically_executed"}


def _bc_architecture_probes(architecture: str, temporary: Path) -> dict[str, Any]:
    """Dynamically exercise load_checkpoint compatibility for one BC architecture."""

    import torch

    from drone_decision_ground.environment import ENVIRONMENT_VERSION
    from drone_decision_verifier.scoring import VERIFIER_VERSION
    from drone_training.behaviour_cloning import TrainingConfig, train_behavior_cloning
    from drone_training.checkpoints import file_digest, load_checkpoint, save_checkpoint
    from drone_training.datasets import generate_dataset
    from drone_training.features import ACTIONS, FEATURE_SCHEMA_VERSION

    results: dict[str, Any] = {key: False for key in REQUIRED_BC_PROBE_KEYS}
    dataset = generate_dataset(partition="train", seeds=[0], families=["authorised_inspection"])
    config = TrainingConfig(
        architecture=architecture,  # type: ignore[arg-type]
        epochs=1,
        learning_rate=0.01,
        batch_size=8,
        context_length=4,
        random_seed=3,
        hidden_dim=16 if architecture == "gru" else 32,
        layers=1,
        heads=4,
        dropout=0.0,
    )
    model, _history = train_behavior_cloning(dataset, config)
    path = temporary / f"{architecture}.pt"
    target = max(sum(step.training_reward for step in trajectory.steps) for trajectory in dataset.trajectories)
    digest = save_checkpoint(
        path,
        model=model,
        architecture=architecture,
        dataset_digest=dataset.manifest.dataset_digest,
        context_length=4,
        normalization=dataset.manifest.normalization,  # type: ignore[arg-type]
        training_instance_digests=dataset.manifest.scenario_instance_digests,
        seed_domain_digest=dataset.manifest.seed_domain_digest,
        return_conditioning_target=target,
    )
    loaded, metadata = load_checkpoint(path, expected_digest=digest)
    results["valid_load"] = (
        metadata.get("architecture") == architecture
        and metadata.get("environment_version") == ENVIRONMENT_VERSION
        and metadata.get("verifier_version") == VERIFIER_VERSION
        and loaded is not None
    )

    def _mutate_and_reject(mutator, *, match: str) -> bool:
        payload = torch.load(path, map_location="cpu", weights_only=False)
        mutator(payload)
        mutated = temporary / f"{architecture}-{match}.pt"
        torch.save(payload, mutated)
        mutated_digest = file_digest(mutated)
        try:
            load_checkpoint(mutated, expected_digest=mutated_digest)
            return False
        except ValueError as exc:
            return match in str(exc).lower() or "incompatible" in str(exc).lower() or "unsupported" in str(exc).lower()
        except TypeError:
            # Architecture/config mismatches must raise sanitized ValueError, not TypeError.
            return False

    results["missing_environment_rejected"] = _mutate_and_reject(
        lambda payload: payload.pop("environment_version", None),
        match="unsupported",
    )
    results["missing_verifier_rejected"] = _mutate_and_reject(
        lambda payload: payload.pop("verifier_version", None),
        match="unsupported",
    )
    results["environment_mismatch_rejected"] = _mutate_and_reject(
        lambda payload: payload.__setitem__("environment_version", "talon.environment/incompatible"),
        match="environment",
    )
    results["verifier_mismatch_rejected"] = _mutate_and_reject(
        lambda payload: payload.__setitem__("verifier_version", "talon.verifier/incompatible"),
        match="verifier",
    )
    results["action_schema_mismatch_rejected"] = _mutate_and_reject(
        lambda payload: payload.__setitem__("actions", [item.value for item in ACTIONS][:-1]),
        match="action",
    )
    results["feature_schema_mismatch_rejected"] = _mutate_and_reject(
        lambda payload: payload.__setitem__("feature_schema_version", FEATURE_SCHEMA_VERSION + "-forged"),
        match="feature",
    )

    def _architecture_config_mismatch(payload: dict[str, Any]) -> None:
        # Keep foreign / architecture-incompatible model_config keys so
        # load_checkpoint raises a sanitized ValueError before construction.
        config = dict(payload.get("model_config") or {})
        if architecture == "gru":
            config["heads"] = 8
            config["context_length"] = 20
            payload["model_config"] = config
        else:
            payload["architecture"] = "gru"

    results["architecture_config_mismatch_rejected"] = _mutate_and_reject(
        _architecture_config_mismatch,
        match="configuration",
    )
    results["passed"] = all(bool(results[key]) for key in REQUIRED_BC_PROBE_KEYS)
    return results


def _bc_checkpoint_compatibility() -> dict[str, Any]:
    """Dynamic BC GRU/DT environment, verifier, schema and architecture probes."""

    import tempfile

    architectures: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="talon-m2-bc-compat-") as temporary:
        root = Path(temporary)
        for architecture in ("gru", "decision_transformer"):
            try:
                architectures[architecture] = _bc_architecture_probes(architecture, root / architecture)
            except Exception as exc:  # noqa: BLE001 — record probe failure without aborting the receipt
                architectures[architecture] = {
                    **{key: False for key in REQUIRED_BC_PROBE_KEYS},
                    "passed": False,
                    "error": type(exc).__name__,
                }
    missing = sorted(REQUIRED_BC_ARCHITECTURES - set(architectures))
    passed = not missing and all(
        isinstance(architectures.get(name), dict) and architectures[name].get("passed") is True
        for name in REQUIRED_BC_ARCHITECTURES
    )
    return {
        "classification": "dynamically_executed",
        "passed": passed,
        "missing_architectures": missing,
        "gru": architectures.get("gru", {}),
        "decision_transformer": architectures.get("decision_transformer", {}),
    }


def _schema_versions() -> dict[str, Any]:
    from drone_decision_ground.actions import ACTION_SCHEMA_VERSION
    from drone_decision_ground.environment import ENVIRONMENT_VERSION
    from drone_decision_verifier.scoring import VERIFIER_VERSION
    from drone_training.features import FEATURE_SCHEMA_VERSION
    from drone_training.offline_checkpoints import OFFLINE_CHECKPOINT_FORMAT_VERSION
    from drone_training.offline_rl import OFFLINE_DATASET_SCHEMA_VERSION

    return {
        "receipt_version": "talon.milestone-2-verification/1.0",
        "environment_version": ENVIRONMENT_VERSION,
        "verifier_version": VERIFIER_VERSION,
        "action_schema_version": ACTION_SCHEMA_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "offline_dataset_schema": OFFLINE_DATASET_SCHEMA_VERSION,
        "cql_checkpoint_schema": OFFLINE_CHECKPOINT_FORMAT_VERSION,
    }


def _environment_detail() -> dict[str, Any]:
    custom = bool(os.environ.get("PLAYWRIGHT_BROWSERS_PATH"))
    return {
        "used_custom_playwright_browsers_path": custom,
        "reason": (
            "PLAYWRIGHT_BROWSERS_PATH is set; browser binaries resolved via a custom "
            "path without recording absolute private paths in the receipt"
            if custom
            else "Playwright used its default browser install location; absolute private "
            "paths are omitted from the receipt"
        ),
    }


def _public_scope() -> dict[str, Any]:
    return {
        "simulation_only": True,
        "decision_support_only": True,
        "human_approval_mandatory": True,
        "external_effect": False,
        "research_baseline": True,
        "production_safety_certification": False,
        "resume_training_unsupported": True,
    }


def _strip_internal_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if not key.startswith("_")}


def _cli_smokes(python: str, temporary: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run generate/train/inspect/evaluate-cql CLI smokes under a temp directory."""

    commands: list[dict[str, Any]] = []
    dataset = temporary / "dataset.json"
    train_gru_dir = temporary / "train-gru"
    train_dt_dir = temporary / "train-dt"
    train_cql_dir = temporary / "train-cql"
    train_gru_dir.mkdir()
    train_dt_dir.mkdir()
    train_cql_dir.mkdir()

    generate = _run_command(
        "cli_generate_dataset",
        [
            python,
            "-m",
            "drone_training",
            "generate-dataset",
            "--output",
            str(dataset),
            "--partition",
            "train",
            "--seed-start",
            "0",
            "--seed-count",
            "1",
            "--family",
            "authorised_inspection",
            "--timeout-seconds",
            "120",
        ],
        temp_root=temporary,
        timeout=180,
    )
    commands.append(generate)

    for name, subcommand, output_dir, extra in (
        ("cli_train_gru", "train-gru", train_gru_dir, ["--epochs", "1", "--batch-size", "8", "--context-length", "4"]),
        (
            "cli_train_decision_transformer",
            "train-decision-transformer",
            train_dt_dir,
            ["--epochs", "1", "--batch-size", "8", "--context-length", "4"],
        ),
        (
            "cli_train_cql",
            "train-cql",
            train_cql_dir,
            [
                "--epochs",
                "1",
                "--batch-size",
                "16",
                "--context-length",
                "4",
                "--hidden-dim",
                "8",
                "--layers",
                "1",
                "--dropout",
                "0",
                "--target-update-interval",
                "2",
                "--timeout-seconds",
                "300",
            ],
        ),
    ):
        commands.append(
            _run_command(
                name,
                [
                    python,
                    "-m",
                    "drone_training",
                    subcommand,
                    "--dataset",
                    str(dataset),
                    "--output-dir",
                    str(output_dir),
                    *extra,
                ],
                temp_root=temporary,
                timeout=600,
            )
        )

    cql_payload = _extract_json_object(commands[-1].get("_stdout") or "") or {}
    run_id = str(cql_payload.get("training_run_id") or "")
    cql_run = train_cql_dir / run_id if run_id else None
    checkpoint = (cql_run / "checkpoint.pt") if cql_run is not None else temporary / "missing-checkpoint.pt"
    offline_dataset = (cql_run / "offline_dataset.json") if cql_run is not None else temporary / "missing-offline.json"
    checkpoint_digest = str(cql_payload.get("checkpoint_digest") or "")
    offline_digest = str(cql_payload.get("offline_dataset_digest") or "")
    source_digest = str(cql_payload.get("dataset_digest") or "")

    inspect_dataset = _run_command(
        "cli_inspect_offline_dataset",
        [
            python,
            "-m",
            "drone_training",
            "inspect-offline-dataset",
            "--dataset",
            str(offline_dataset),
        ],
        temp_root=temporary,
        timeout=120,
    )
    commands.append(inspect_dataset)
    inspected_dataset = _extract_json_object(inspect_dataset.get("_stdout") or "") or {}
    if inspected_dataset.get("dataset_digest"):
        offline_digest = str(inspected_dataset["dataset_digest"])
    if inspected_dataset.get("source_dataset_digest"):
        source_digest = str(inspected_dataset["source_dataset_digest"])

    inspect_checkpoint = _run_command(
        "cli_inspect_offline_checkpoint",
        [
            python,
            "-m",
            "drone_training",
            "inspect-offline-checkpoint",
            "--checkpoint",
            str(checkpoint),
            "--trusted-checkpoint-digest",
            checkpoint_digest or "sha256:" + ("0" * 64),
            "--offline-dataset-digest",
            offline_digest or "sha256:" + ("0" * 64),
            "--source-dataset-digest",
            source_digest or "sha256:" + ("0" * 64),
        ],
        temp_root=temporary,
        timeout=120,
    )
    commands.append(inspect_checkpoint)
    inspected_checkpoint = _extract_json_object(inspect_checkpoint.get("_stdout") or "") or {}
    if inspected_checkpoint.get("checkpoint_digest"):
        checkpoint_digest = str(inspected_checkpoint["checkpoint_digest"])
    if inspected_checkpoint.get("offline_dataset_digest"):
        offline_digest = str(inspected_checkpoint["offline_dataset_digest"])
    if inspected_checkpoint.get("source_dataset_digest"):
        source_digest = str(inspected_checkpoint["source_dataset_digest"])

    evaluate = _run_command(
        "cli_evaluate_cql",
        [
            python,
            "-m",
            "drone_training",
            "evaluate-cql",
            "--checkpoint",
            str(checkpoint),
            "--trusted-checkpoint-digest",
            checkpoint_digest or "sha256:" + ("0" * 64),
            "--offline-dataset-digest",
            offline_digest or "sha256:" + ("0" * 64),
            "--source-dataset-digest",
            source_digest or "sha256:" + ("0" * 64),
            "--family",
            "authorised_inspection",
            "--seed",
            "0",
            "--partition",
            "validation",
            "--timeout-seconds",
            "60",
        ],
        temp_root=temporary,
        timeout=180,
    )
    commands.append(evaluate)
    evaluation_payload = _extract_json_object(evaluate.get("_stdout") or "") or {}
    nested_result = evaluation_payload.get("result")
    nested_result = nested_result if isinstance(nested_result, dict) else {}
    frozen = {
        "passed": bool(evaluate.get("passed")) and bool(evaluation_payload),
        "classification": "dynamically_executed",
        "partition": "validation",
        "family": "authorised_inspection",
        "seed": 0,
        "checkpoint_digest": evaluation_payload.get("checkpoint_digest") or checkpoint_digest,
        "offline_dataset_digest": offline_digest,
        "source_dataset_digest": source_digest,
        "result": {
            key: nested_result[key]
            for key in ("strict_success", "gate_accepted", "recommended_action", "outcome")
            if key in nested_result
        }
        or {
            key: evaluation_payload[key]
            for key in (
                "schema_version",
                "evaluation_id",
                "algorithm",
                "environment_version",
                "verifier_version",
                "elapsed_ms",
            )
            if key in evaluation_payload
        },
    }
    return commands, frozen


def _suite_verification(*, deferred: bool) -> dict[str, Any]:
    """Run full suite verification in evidence mode, or defer under --check-only."""

    if deferred:
        return {
            "passed": True,
            "classification": "deferred_to_evidence_mode",
            "note": (
                "Suite verification (pytest, dashboard npm scripts, compileall, "
                "uv lock, git diff --check, and CLI smokes) is deferred to evidence mode"
            ),
        }

    python = _python_executable()
    npm = _npm_executable()
    uv = _uv_executable()
    dashboard = ROOT / "apps" / "dashboard"
    commands: list[dict[str, Any]] = []

    pytest_prefix: list[str]
    if uv is not None:
        pytest_prefix = [uv, "run", "--extra", "talon", "--extra", "test", "python", "-m", "pytest"]
    else:
        pytest_prefix = [python, "-m", "pytest"]

    commands.append(
        _run_command("talon_python", [*pytest_prefix, "tests/talon", "-q"], timeout=1800)
    )
    commands.append(
        _run_command("complete_python", [*pytest_prefix, "tests", "-q"], timeout=3600)
    )
    commands.append(
        _run_command("dashboard_unit", [npm, "test", "--", "--run"], cwd=dashboard, timeout=900)
    )
    commands.append(
        _run_command(
            "dashboard_lint",
            [npm, "run", "lint"],
            cwd=dashboard,
            classification="static",
            timeout=600,
        )
    )
    commands.append(
        _run_command(
            "dashboard_typecheck",
            [npm, "run", "typecheck"],
            cwd=dashboard,
            classification="static",
            timeout=600,
        )
    )
    commands.append(
        _run_command("dashboard_build", [npm, "run", "build"], cwd=dashboard, timeout=900)
    )
    commands.append(
        _run_command(
            "npm_audit",
            [npm, "audit", "--audit-level=high"],
            cwd=dashboard,
            classification="dependency_scan",
            timeout=300,
        )
    )
    commands.append(
        _run_command(
            "compileall",
            [python, "-m", "compileall", "-q", "src", "scripts", "tests"],
            classification="static",
            timeout=300,
        )
    )
    if uv is not None:
        commands.append(
            _run_command(
                "uv_lock",
                [uv, "lock", "--check"],
                classification="dependency_scan",
                timeout=120,
            )
        )
    else:
        commands.append(
            {
                "name": "uv_lock",
                "command": "uv lock --check",
                "exit_code": 1,
                "passed": False,
                "duration_seconds": 0.0,
                "classification": "dependency_scan",
                "error": "uv executable not found",
            }
        )
    commands.append(
        _run_command(
            "diff_check",
            ["git", "diff", "--check"],
            classification="static",
            timeout=60,
        )
    )

    with tempfile.TemporaryDirectory(prefix="talon-m2-suite-") as temporary:
        cli_commands, frozen = _cli_smokes(python, Path(temporary))
        commands.extend(cli_commands)

    public_commands = [_strip_internal_fields(item) for item in commands]
    by_name = {item["name"]: item for item in public_commands}
    missing = [name for name in SUITE_VERIFICATION_COMMAND_NAMES if name not in by_name]
    passed = not missing and all(bool(item.get("passed")) for item in public_commands) and bool(frozen.get("passed"))
    return {
        "passed": passed,
        "classification": "dynamically_executed",
        "commands": public_commands,
        "missing_commands": missing,
        "frozen_cql_evaluation": frozen,
    }


def _receipt_completeness(report: dict[str, Any]) -> dict[str, Any]:
    missing_top = sorted(REQUIRED_RECEIPT_KEYS - set(report))
    checks_block = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    missing_checks = sorted(REQUIRED_CHECK_KEYS - set(checks_block))
    nested_ok = all(
        isinstance(checks_block.get(key), dict) and "passed" in checks_block[key]
        for key in REQUIRED_CHECK_KEYS
        if key in checks_block
    )

    dynamic = checks_block.get("dynamic_offline_rl") if isinstance(checks_block.get("dynamic_offline_rl"), dict) else {}
    dynamic_proofs = dynamic.get("checks") if isinstance(dynamic.get("checks"), dict) else {}
    missing_dynamic = sorted(REQUIRED_DYNAMIC_PROOF_KEYS - set(dynamic_proofs))

    playwright_problems = _validate_playwright_section(checks_block.get("playwright"))

    frontier = checks_block.get("frontier_integrity") if isinstance(checks_block.get("frontier_integrity"), dict) else {}
    frontier_ok = frontier.get("integrity_method") == "git_blob_identity"

    hardenings = (
        checks_block.get("product_hardenings") if isinstance(checks_block.get("product_hardenings"), dict) else {}
    )
    hardening_checks = hardenings.get("checks") if isinstance(hardenings.get("checks"), dict) else {}
    missing_hardenings = sorted(REQUIRED_PRODUCT_HARDENING_KEYS - set(hardening_checks))
    hardening_classification_problems: list[str] = []
    # Reject a sole top-level dynamically_executed classification when required
    # static checks are present — classifications must be per nested field.
    if hardenings.get("classification") == "dynamically_executed" and (
        "policy_client_signature_absent" in hardening_checks
        or "for_tests_helper_not_used_by_product" in hardening_checks
    ):
        hardening_classification_problems.append(
            "product_hardenings must not use a sole top-level dynamically_executed classification when mixing static checks"
        )
    for key, expected in REQUIRED_PRODUCT_HARDENING_CLASSIFICATIONS.items():
        entry = hardening_checks.get(key)
        if not isinstance(entry, dict):
            if key in hardening_checks:
                hardening_classification_problems.append(f"product_hardenings.checks.{key} must be an object with classification")
            continue
        actual = entry.get("classification")
        if actual != expected:
            hardening_classification_problems.append(
                f"product_hardenings.checks.{key}.classification must be {expected!r} (got {actual!r})"
            )
        if "passed" not in entry:
            hardening_classification_problems.append(f"product_hardenings.checks.{key}.passed missing")

    bc = (
        checks_block.get("bc_checkpoint_compatibility")
        if isinstance(checks_block.get("bc_checkpoint_compatibility"), dict)
        else {}
    )
    bc_problems: list[str] = []
    if bc.get("classification") != "dynamically_executed":
        bc_problems.append("bc_checkpoint_compatibility.classification must be dynamically_executed")
    for architecture in REQUIRED_BC_ARCHITECTURES:
        arch = bc.get(architecture)
        if not isinstance(arch, dict):
            bc_problems.append(f"bc_checkpoint_compatibility.{architecture} missing")
            continue
        missing_probes = sorted(REQUIRED_BC_PROBE_KEYS - set(arch))
        if missing_probes:
            bc_problems.append(f"bc_checkpoint_compatibility.{architecture} missing probes: {missing_probes}")
        for probe in REQUIRED_BC_PROBE_KEYS:
            if arch.get(probe) is not True:
                bc_problems.append(f"bc_checkpoint_compatibility.{architecture}.{probe} must be true")
        if arch.get("passed") is not True:
            bc_problems.append(f"bc_checkpoint_compatibility.{architecture}.passed must be true")

    suite = (
        checks_block.get("suite_verification") if isinstance(checks_block.get("suite_verification"), dict) else {}
    )
    suite_problems: list[str] = []
    evidence_top_problems: list[str] = []
    if suite.get("classification") == "dynamically_executed":
        if suite.get("passed") is not True:
            suite_problems.append("suite_verification.passed must be true in evidence mode")
        commands = suite.get("commands")
        if not isinstance(commands, list):
            suite_problems.append("suite_verification.commands missing")
        else:
            names = {item.get("name") for item in commands if isinstance(item, dict)}
            missing_suite = [name for name in SUITE_VERIFICATION_COMMAND_NAMES if name not in names]
            if missing_suite:
                suite_problems.append(f"suite_verification missing commands: {missing_suite}")
        frozen = suite.get("frozen_cql_evaluation")
        if not isinstance(frozen, dict) or frozen.get("passed") is not True:
            suite_problems.append("suite_verification.frozen_cql_evaluation.passed must be true")
        missing_evidence_top = sorted(REQUIRED_EVIDENCE_RECEIPT_KEYS - set(report))
        if missing_evidence_top:
            evidence_top_problems.append(f"missing evidence top-level keys: {missing_evidence_top}")
        playwright = checks_block.get("playwright") if isinstance(checks_block.get("playwright"), dict) else {}
        if playwright.get("result") != "dynamically_executed":
            evidence_top_problems.append("playwright.result must be dynamically_executed in evidence mode")
        if playwright.get("real_browser") is not True:
            evidence_top_problems.append("playwright.real_browser must be true in evidence mode")
        test_counts = report.get("test_counts")
        if not isinstance(test_counts, dict):
            evidence_top_problems.append("test_counts missing")
        else:
            for key in (
                "talon_python",
                "complete_python",
                "dashboard_unit",
                "playwright_talon",
                "playwright_frontier",
                "playwright_total",
            ):
                if key not in test_counts:
                    evidence_top_problems.append(f"test_counts.{key} missing")
        schema = report.get("schema_versions")
        if not isinstance(schema, dict):
            evidence_top_problems.append("schema_versions missing")
        else:
            for key in (
                "receipt_version",
                "environment_version",
                "verifier_version",
                "action_schema_version",
                "feature_schema_version",
                "offline_dataset_schema",
                "cql_checkpoint_schema",
            ):
                if key not in schema:
                    evidence_top_problems.append(f"schema_versions.{key} missing")
        scope = report.get("scope")
        if not isinstance(scope, dict):
            evidence_top_problems.append("scope missing")
        else:
            for key, expected in (
                ("simulation_only", True),
                ("decision_support_only", True),
                ("human_approval_mandatory", True),
                ("external_effect", False),
                ("research_baseline", True),
                ("production_safety_certification", False),
                ("resume_training_unsupported", True),
            ):
                if scope.get(key) is not expected:
                    evidence_top_problems.append(f"scope.{key} must be {expected!r}")
        detail = report.get("environment_detail")
        if not isinstance(detail, dict) or "used_custom_playwright_browsers_path" not in detail:
            evidence_top_problems.append("environment_detail.used_custom_playwright_browsers_path missing")
    elif suite.get("classification") == "deferred_to_evidence_mode":
        if suite.get("passed") is not True:
            suite_problems.append("deferred suite_verification.passed must be true")
    else:
        suite_problems.append("suite_verification.classification must be dynamically_executed or deferred_to_evidence_mode")

    return {
        "passed": (
            not missing_top
            and not missing_checks
            and nested_ok
            and not missing_dynamic
            and not playwright_problems
            and frontier_ok
            and not missing_hardenings
            and not hardening_classification_problems
            and not bc_problems
            and not suite_problems
            and not evidence_top_problems
        ),
        "missing_top_level_keys": missing_top,
        "missing_check_keys": missing_checks,
        "missing_dynamic_proof_keys": missing_dynamic,
        "missing_product_hardening_keys": missing_hardenings,
        "product_hardening_classification_problems": hardening_classification_problems,
        "bc_checkpoint_compatibility_problems": bc_problems,
        "suite_verification_problems": suite_problems,
        "evidence_top_level_problems": evidence_top_problems,
        "playwright_schema_problems": playwright_problems,
        "frontier_integrity_method_ok": frontier_ok,
        "classification": "receipt_schema",
    }


def build_report(source_commit: str, *, list_only_playwright: bool = True) -> dict[str, Any]:
    dynamic = _dynamic_checks()
    physical = _source_scan()
    td_docs = _td_backup_documentation()
    frontier = _frontier_integrity(source_commit)
    playwright = _playwright_checks(list_only=list_only_playwright)
    hardenings = _product_hardenings()
    bc_compat = _bc_checkpoint_compatibility()
    suite = _suite_verification(deferred=list_only_playwright)
    m1 = frontier.get("milestone_1_receipt") or _m1_receipt_blob_identity(source_commit)
    checks: dict[str, Any] = {
        "dynamic_offline_rl": dynamic,
        "physical_response_boundary": physical,
        "milestone_1_receipt_unchanged": m1,
        "td_backup_documentation": td_docs,
        "frontier_integrity": frontier,
        "playwright": playwright,
        "product_hardenings": hardenings,
        "bc_checkpoint_compatibility": bc_compat,
        "suite_verification": suite,
    }
    limitations = [
        "Discrete CQL is a research baseline and is not certified for production safety.",
        "The first encoder is GRU-based and learns from static private simulation trajectories only.",
        "TD backup is mask-aware only; safety-threshold filtering applies at action selection and the policy gate remains authoritative.",
        "Playwright --check-only uses listed_only counts; full evidence mode requires executed browser results.",
        "Frontier scoring freeze is attested via unchanged training_ground/strict_verifier (git integrity).",
        "Research baseline only: no production safety certification is claimed.",
        "Resume/continued training from offline RL checkpoints is unsupported.",
        "CLI --trusted-checkpoint-digest values are operator-supplied provenance, not immutable DB bindings.",
        "No physical-response or external-effect capability is implemented; human approval remains mandatory where required.",
    ]
    report: dict[str, Any] = {
        "receipt_version": "talon.milestone-2-verification/1.0",
        "source_commit": source_commit,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": all(item["passed"] for item in checks.values()),
        "checks": checks,
        "limitations": limitations,
    }
    if not list_only_playwright:
        suite_commands = {
            item["name"]: item
            for item in (suite.get("commands") or [])
            if isinstance(item, dict) and "name" in item
        }
        report["branch"] = _git("rev-parse", "--abbrev-ref", "HEAD")
        report["test_counts"] = {
            "talon_python": int((suite_commands.get("talon_python") or {}).get("test_count") or 0),
            "complete_python": int((suite_commands.get("complete_python") or {}).get("test_count") or 0),
            "dashboard_unit": int((suite_commands.get("dashboard_unit") or {}).get("test_count") or 0),
            "playwright_talon": int((playwright.get("talon") or {}).get("count") or 0),
            "playwright_frontier": int((playwright.get("frontier") or {}).get("count") or 0),
            "playwright_total": int((playwright.get("complete") or {}).get("count") or 0),
        }
        report["schema_versions"] = _schema_versions()
        report["scope"] = _public_scope()
        report["environment_detail"] = _environment_detail()
    # Seed before validation so REQUIRED_CHECK_KEYS (incl. self) can pass.
    report["checks"]["receipt_completeness"] = {
        "passed": False,
        "missing_top_level_keys": [],
        "missing_check_keys": [],
        "missing_dynamic_proof_keys": [],
        "missing_product_hardening_keys": [],
        "product_hardening_classification_problems": [],
        "bc_checkpoint_compatibility_problems": [],
        "suite_verification_problems": [],
        "evidence_top_level_problems": [],
        "playwright_schema_problems": [],
        "classification": "receipt_schema",
    }
    completeness = _receipt_completeness(report)
    report["checks"]["receipt_completeness"] = completeness
    report["passed"] = report["passed"] and completeness["passed"]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--source-commit")
    parser.add_argument("--output", type=Path, default=RECEIPT_PATH)
    args = parser.parse_args(argv)
    source_commit = args.source_commit or _git("rev-parse", "HEAD")
    if not args.check_only:
        refuse_dirty_evidence(_git("status", "--short"))
        validate_source_commit(ROOT, source_commit, ALLOWED_RECEIPTS)
    # --check-only: list Playwright tests only (no evidence write, dirty tree OK).
    # Evidence mode executes Playwright + suite verification and requires a clean tree.
    report = build_report(source_commit, list_only_playwright=bool(args.check_only))
    if args.check_only:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        output = ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
