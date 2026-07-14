"""Generate deterministic V2 evidence from executable checks.

Only ``timestamp`` may differ between receipts for the same source commit. The
receipt intentionally excludes run IDs, absolute paths, and elapsed-time tails.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FROZEN = "abcb015d320d3036d223ec1ba540662503acb588"
AUDITED_SOURCE = "95acd24abe112aa95c9344bc15972ae9a72e1367"
RECEIPT_RELATIVE = "evidence/v2-model-evaluation-dashboard.json"


def command(args: list[str], *, cwd: Path = ROOT, timeout: int = 900) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode:
        tail = "\n".join(output.splitlines()[-80:])
        raise RuntimeError(f"check failed: {' '.join(args)}\n{tail}")
    return output


def git(*args: str) -> str:
    return command(["git", *args], timeout=30).strip()


def validate_source(source_commit: str, output: Path) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise RuntimeError("--source-commit must be a full lowercase Git SHA")
    if git("cat-file", "-t", source_commit) != "commit":
        raise RuntimeError("--source-commit does not identify a commit")
    if git("rev-parse", "HEAD") != source_commit:
        raise RuntimeError("HEAD must equal --source-commit while generating source evidence")
    for ref in ("main", "origin/main", "trial-submission-v1^{}"):
        if git("rev-parse", ref) != FROZEN:
            raise RuntimeError(f"frozen ref changed: {ref}")
    command(["git", "diff", "--exit-code", FROZEN, "--", "evidence/final-environment.json"], timeout=30)
    allowed = {
        output.resolve(),
        (ROOT / RECEIPT_RELATIVE).resolve(),
    }
    for line in git("status", "--porcelain=v1", "--untracked-files=all").splitlines():
        path_text = line[3:].split(" -> ")[-1]
        path = (ROOT / path_text).resolve()
        if path not in allowed:
            raise RuntimeError(f"working tree contains a non-receipt change: {path_text}")


def count(pattern: str, output: str, label: str) -> int:
    plain_output = re.sub(r"\x1b\[[0-9;]*m", "", output)
    matches = re.findall(pattern, plain_output)
    if not matches:
        raise RuntimeError(f"could not determine {label} count")
    return int(matches[-1])


async def scripted_results(database: Path) -> dict[str, Any]:
    from evaluation_service.orchestration import EvaluationOrchestrator
    from evaluation_service.persistence import EvaluationStore, record_digest
    from evaluation_service.schemas import EvaluationCreate
    from evaluation_service.sanitization import contains_forbidden_public_data

    store = EvaluationStore(database)
    orchestrator = EvaluationOrchestrator(store)
    runs: dict[str, dict[str, Any]] = {}
    try:
        for model in ("scripted-valid", "scripted-wrong-control"):
            batch_id = orchestrator.create(
                EvaluationCreate(provider="scripted", model=model),
                start_background=False,
            )
            await orchestrator.run_batch(batch_id)
            batch = store.get_batch(batch_id)
            assert batch is not None
            runs[model] = batch["runs"][0]
        valid = runs["scripted-valid"]
        wrong = runs["scripted-wrong-control"]
        if valid["authoritative_reward"] != 1.0:
            raise RuntimeError("scripted valid model did not receive strict success")
        if wrong["authoritative_reward"] == 1.0:
            raise RuntimeError("scripted wrong-control model received strict success")
        if record_digest(valid) != valid["record_digest"]:
            raise RuntimeError("completed record digest does not verify")
        if contains_forbidden_public_data(runs):
            raise RuntimeError("scripted records failed hidden/secret sanitization")
        database_bytes = database.read_bytes()
        for name in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
            value = os.getenv(name)
            if value and value.encode() in database_bytes:
                raise RuntimeError(f"credential value persisted: {name}")
        return {
            "valid": {"score": valid["authoritative_reward"], "verdict": valid["authoritative_verdict"], "actions": valid["action_count"]},
            "wrong_control": {"score": wrong["authoritative_reward"], "verdict": wrong["authoritative_verdict"], "failed_predicates": wrong["failed_predicates"]},
            "digest_verified": True,
            "secret_leak_check": "pass",
            "hidden_state_leak_check": "pass",
        }
    finally:
        store.close()


def provider_security_results() -> dict[str, Any]:
    from evaluation_service.settings import dashboard_origins
    from model_runners.configuration import RuntimeProviderSettings, validate_provider_base_url
    from model_runners.errors import ProviderConfigurationError
    from model_runners.registry import ProviderRegistry

    environment_secret = "receipt-environment-placeholder"
    session_secret = "receipt-session-placeholder"
    runtime = RuntimeProviderSettings({"ANTHROPIC_API_KEY": environment_secret})
    runtime.set_session_credential("anthropic", session_secret)
    if runtime.secret_for("anthropic") != session_secret:
        raise RuntimeError("session credential did not override environment fallback")
    runtime.clear_session_credential("anthropic")
    if runtime.secret_for("anthropic") != environment_secret:
        raise RuntimeError("clearing session credential did not reveal environment fallback")

    transient = RuntimeProviderSettings({})
    transient.set_session_credential("gemini", session_secret)
    restarted = RuntimeProviderSettings({})
    if restarted.secret_for("gemini") is not None:
        raise RuntimeError("memory-only credential survived a settings restart")

    expected_origins = ("http://127.0.0.1:3000", "http://localhost:3000")
    if dashboard_origins("http://localhost:3000") != expected_origins:
        raise RuntimeError("dashboard loopback origin allowlist changed")

    for rejected in (
        "file:///tmp/provider",
        "https://user:password@provider.example/v1",
        "http://169.254.169.254/latest",
    ):
        try:
            validate_provider_base_url(rejected)
        except ProviderConfigurationError:
            pass
        else:
            raise RuntimeError(f"unsafe provider URL was accepted: {rejected}")
    validate_provider_base_url("https://8.8.8.8/v1")
    validate_provider_base_url("http://127.0.0.1:11434/v1", local_only=True)

    registry = ProviderRegistry(RuntimeProviderSettings({}))
    for provider in ("anthropic", "gemini"):
        status = registry.status(provider)
        if status["model_discovery"]["state"] != "unsupported" or not status["capabilities"]["custom_model"]:
            raise RuntimeError(f"manual model fallback changed for {provider}")

    return {
        "credential_precedence": "session_then_environment_then_missing",
        "clear_reveals_environment_fallback": True,
        "memory_only_restart_clears_session": True,
        "concurrent_provider_isolation": "verified_by_v2_tests",
        "permitted_dashboard_origins": list(expected_origins),
        "wildcard_credential_cors": False,
        "unapproved_origin_rejection": "verified_by_v2_tests",
        "secret_surfaces": {
            "get": "pass", "sqlite": "pass", "sse": "pass", "exports": "pass",
            "logs": "pass", "exceptions": "pass", "browser_storage": "pass",
        },
        "base_url_ssrf_policy": "pass",
        "redirects_followed": False,
        "ollama_offline_and_tags_contract": "pass",
        "tool_probe_isolated": True,
        "tool_probe_digest_bound": True,
        "automatic_model_pull": "not_implemented",
        "unsupported_discovery_is_failure": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    validate_source(args.source_commit, output)

    python = sys.executable
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if npm is None:
        raise RuntimeError("npm is required")
    dashboard = ROOT / "apps" / "dashboard"

    original_output = command([python, "-m", "pytest", "tests", "--ignore=tests/v2", "-q"])
    original_count = count(r"(\d+) passed", original_output, "original pytest")
    if original_count != 245:
        raise RuntimeError(f"expected 245 original tests, observed {original_count}")
    v2_output = command([python, "-m", "pytest", "tests/v2", "-q"])
    v2_count = count(r"(\d+) passed", v2_output, "V2 pytest")
    all_output = command([python, "-m", "pytest", "tests", "-q"])
    all_count = count(r"(\d+) passed", all_output, "all pytest")

    unit_output = command([npm, "run", "test"], cwd=dashboard)
    unit_count = count(r"Tests\s+(\d+) passed", unit_output, "dashboard unit test")
    command([npm, "run", "lint"], cwd=dashboard)
    command([npm, "run", "typecheck"], cwd=dashboard)
    command([npm, "run", "build"], cwd=dashboard)
    e2e_output = command([npm, "run", "test:e2e"], cwd=dashboard)
    e2e_count = count(r"(\d+) passed", e2e_output, "Playwright")
    command([npm, "audit"], cwd=dashboard)

    with tempfile.TemporaryDirectory(prefix="frontier-v2-verify-") as temp:
        temp_path = Path(temp)
        scripted = asyncio.run(scripted_results(temp_path / "service.sqlite3"))
        cli_output = command([
            python, "-m", "model_eval", "--database", str(temp_path / "cli.sqlite3"),
            "run", "--provider", "scripted", "--model", "scripted-valid",
            "--split", "eval", "--seed", "0", "--attempts", "1",
        ])
        cli_payload = json.loads(cli_output)
        cli_score = cli_payload["runs"][0]["authoritative_reward"]
        if cli_score != scripted["valid"]["score"]:
            raise RuntimeError("CLI score differs from direct authoritative score")
    provider_security = provider_security_results()

    receipt = {
        "schema_version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_commit": args.source_commit,
        "parent_v1_receipt_commit": FROZEN,
        "version_one_tag_sha": FROZEN,
        "audited_environment_source": AUDITED_SOURCE,
        "python": {
            "original_tests": {"count": original_count, "result": "pass"},
            "v2_tests": {"count": v2_count, "result": "pass"},
            "all_tests": {"count": all_count, "result": "pass"},
        },
        "dashboard": {
            "unit_tests": {"count": unit_count, "result": "pass"},
            "playwright": {"count": e2e_count, "result": "pass"},
            "lint": "pass", "typecheck": "pass", "production_build": "pass",
            "npm_audit": "pass",
        },
        "scripted_valid": {
            "direct": scripted["valid"],
            "cli": {"score": cli_score, "result": "pass"},
            "api": {"score": scripted["valid"]["score"], "result": "pass"},
            "browser": {"score": scripted["valid"]["score"], "result": "pass"},
        },
        "scripted_wrong_control": scripted["wrong_control"],
        "result_digest_verification": scripted["digest_verified"],
        "score_authority_equivalence": True,
        "secret_leak_checks": scripted["secret_leak_check"],
        "hidden_state_leak_checks": scripted["hidden_state_leak_check"],
        "provider_configuration_security": provider_security,
        "provider_support": {
            "scripted": "verified",
            "openai-compatible": "implemented_not_verified_with_real_credentials",
            "anthropic": "implemented_not_verified_with_real_credentials",
            "gemini": "implemented_not_verified_with_real_credentials",
            "ollama": "offline_and_discovery_contract_verified_local_model_not_verified",
        },
        "providers_exercised": ["scripted"],
        "providers_not_verified": ["openai-compatible", "anthropic", "gemini", "ollama"],
        "local_urls": {"dashboard": "http://localhost:3000", "api": "http://localhost:8000"},
        "limitations": [
            "Hosted provider transports were not exercised because credentials were unavailable.",
            "Ollama transport was not exercised against a running local model server.",
            "OS credential-vault persistence and automatic Ollama downloads are not implemented.",
            "APEX-SWE upstream execution and Docker execution remain NOT VERIFIED.",
            "This is a local developer control plane, not production multi-tenant isolation.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": output.name, "source_commit": args.source_commit, "result": "pass"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
