"""Build bounded, sanitized candidate diffs for local run retention."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ARTIFACT_VERSION = "1.0"
MAX_DIFF_BYTES = 480 * 1024
MAX_DIFF_LINE_BYTES = 16 * 1024
EDITABLE_PATHS = (
    "service/contract.md",
    "service/flow.py",
    "service/store.py",
    "service/runtime.py",
    "service/settings.toml",
)

_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_-]?key|authorization|cookie|password|secret|access[_-]?token|refresh[_-]?token)\s*[:=]"
)
_FORBIDDEN_INTERNAL = re.compile(
    r"(?i)(?:member_selector|fixture_profile|auth_tag|trace_authority|recovery_authority)"
)
_PRIVATE_PATH = re.compile(
    r"(?:[A-Za-z]:\\|/)(?:[^\s]+[/\\])+(?:service\.sqlite3|strict_verifier|workloads\.py)",
    re.I,
)
_HIDDEN_WORKLOAD = re.compile(r"\bH-[A-Za-z0-9_.-]+\b")
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\b(?:sk-ant-|sk-proj-|sk-)[A-Za-z0-9_-]{8,}\b", re.I),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{8,}\b", re.I),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}=*"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"https?://[^\s/:@]+:[^\s/@]+@", re.I),
)


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")


def candidate_artifact_digest(artifact: dict[str, Any]) -> str:
    """Return the digest of an artifact without trusting its declared digest."""
    payload = {key: value for key, value in artifact.items() if key != "artifact_digest"}
    return _sha256(_canonical(payload))


def _sanitize_diff_line(line: str) -> tuple[str, int, bool]:
    prefix = line[:1] if line[:1] in {"+", "-", " "} else ""
    body = line[1:] if prefix else line
    if line.startswith(("+++ ", "--- ", "@@ ")):
        return line, 0, False
    if _SENSITIVE_ASSIGNMENT.search(body) or _FORBIDDEN_INTERNAL.search(body):
        return prefix + "<redacted-sensitive-line>\n", 1, False

    redactions = 0
    cleaned = body
    replacements = (
        (_PRIVATE_PATH, "<redacted-private-path>"),
        (_HIDDEN_WORKLOAD, "<redacted-hidden-workload>"),
        *((pattern, "<redacted-secret>") for pattern in _SECRET_VALUE_PATTERNS),
    )
    for pattern, replacement in replacements:
        cleaned, count = pattern.subn(replacement, cleaned)
        redactions += count

    encoded = cleaned.encode("utf-8")
    line_truncated = False
    if len(encoded) > MAX_DIFF_LINE_BYTES:
        cleaned = encoded[:MAX_DIFF_LINE_BYTES].decode("utf-8", errors="ignore") + "<truncated-line>\n"
        redactions += 1
        line_truncated = True
    return prefix + cleaned, redactions, line_truncated


def build_candidate_diff(initial_workspace: Path, candidate_workspace: Path) -> dict[str, Any] | None:
    """Create a sanitized unified diff for the bounded model-editable files."""
    files: list[dict[str, Any]] = []
    redaction_count = 0
    diff_bytes = 0
    truncated = False

    for relative_path in EDITABLE_PATHS:
        initial_path = initial_workspace / Path(relative_path)
        candidate_path = candidate_workspace / Path(relative_path)
        if not initial_path.is_file() or not candidate_path.is_file():
            continue
        before_bytes = initial_path.read_bytes()
        after_bytes = candidate_path.read_bytes()
        if before_bytes == after_bytes:
            continue
        before = before_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)
        after = after_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)
        raw_lines = difflib.unified_diff(
            before,
            after,
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
            n=3,
        )
        retained_lines: list[str] = []
        file_truncated = False
        for raw_line in raw_lines:
            safe_line, count, line_truncated = _sanitize_diff_line(raw_line)
            redaction_count += count
            if line_truncated:
                file_truncated = True
                truncated = True
            line_bytes = len(safe_line.encode("utf-8"))
            if diff_bytes + line_bytes > MAX_DIFF_BYTES:
                retained_lines.append("<candidate-diff-truncated>\n")
                file_truncated = True
                truncated = True
                break
            retained_lines.append(safe_line)
            diff_bytes += line_bytes
        files.append({
            "path": relative_path,
            "before_sha256": _sha256(before_bytes),
            "after_sha256": _sha256(after_bytes),
            "after_bytes": len(after_bytes),
            "diff": "".join(retained_lines),
            "truncated": file_truncated,
        })
        if truncated:
            break

    if not files:
        return None
    artifact: dict[str, Any] = {
        "artifact_version": ARTIFACT_VERSION,
        "format": "unified_diff",
        "files": files,
        "file_count": len(files),
        "changed_paths": [item["path"] for item in files],
        "redaction_count": redaction_count,
        "truncated": truncated,
    }
    artifact["artifact_digest"] = candidate_artifact_digest(artifact)
    return artifact
