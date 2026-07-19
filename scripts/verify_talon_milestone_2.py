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
import re
import shutil
import subprocess
import sys
import tempfile
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
        "receipt_completeness",
    }
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
    display = " ".join(command)
    return {
        "count": count,
        "result": "listed_only",
        "command": display,
        "skipped": 0,
    }


def _playwright_checks(*, list_only: bool) -> dict[str, Any]:
    """Populate Playwright receipt fields.

    ``--check-only`` prefers ``--list`` counts (``listed_only``) so dirty trees
    stay fast and evidence is never written. Full evidence mode must use
    executed results; this verifier still refuses dirty-tree evidence writes.
    """

    note = (
        "Full evidence mode requires executed Playwright results with workers=1 "
        "and skipped=0; --check-only populates counts via playwright test --list."
    )
    if not list_only:
        # Evidence generation path: still refuse to invent executed results here.
        # Callers must not write evidence without a clean tree and real runs.
        return {
            "passed": False,
            "browser": "chromium",
            "workers": 1,
            "skipped": 0,
            "result": "executed_required",
            "note": note,
            "classification": "playwright_schema",
            "reason": "executed Playwright results are required for evidence mode",
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
        ),
        "missing_top_level_keys": missing_top,
        "missing_check_keys": missing_checks,
        "missing_dynamic_proof_keys": missing_dynamic,
        "missing_product_hardening_keys": missing_hardenings,
        "product_hardening_classification_problems": hardening_classification_problems,
        "bc_checkpoint_compatibility_problems": bc_problems,
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
    }
    report = {
        "receipt_version": "talon.milestone-2-verification/1.0",
        "source_commit": source_commit,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": all(item["passed"] for item in checks.values()),
        "checks": checks,
        "limitations": [
            "Discrete CQL is a research baseline and is not certified for production safety.",
            "The first encoder is GRU-based and learns from static private simulation trajectories only.",
            "TD backup is mask-aware only; safety-threshold filtering applies at action selection and the policy gate remains authoritative.",
            "Playwright --check-only uses listed_only counts; full evidence mode requires executed browser results.",
            "Frontier scoring freeze is attested via unchanged training_ground/strict_verifier (git integrity).",
        ],
    }
    # Seed before validation so REQUIRED_CHECK_KEYS (incl. self) can pass.
    report["checks"]["receipt_completeness"] = {
        "passed": False,
        "missing_top_level_keys": [],
        "missing_check_keys": [],
        "missing_dynamic_proof_keys": [],
        "missing_product_hardening_keys": [],
        "product_hardening_classification_problems": [],
        "bc_checkpoint_compatibility_problems": [],
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
    # Evidence mode requires executed results (not invented here) and a clean tree.
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
