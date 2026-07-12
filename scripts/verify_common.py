"""Shared source-commit binding and helper utilities for the verifiers."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _run_git_checked(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(
            f"git {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout.strip()


def _is_receipt_only_commit(repo: Path, sha: str, allowed_receipt_files: tuple[str, ...]) -> bool:
    """Return True if the commit changes only allowed receipt files."""
    if _git_object_type(repo, sha) != "commit":
        return False
    parent = _run_git(repo, "rev-parse", "--verify", f"{sha}^")
    if parent == sha or not parent:
        # First commit or no parent; inspect the commit itself.
        files = _run_git(repo, "show", "--stat=", "--format=", "--name-only", sha).splitlines()
    else:
        files = _run_git(repo, "diff", "--name-only", f"{parent}..{sha}").splitlines()
    files = [f for f in files if f.strip()]
    return files and all(f in allowed_receipt_files for f in files)


def _git_object_type(repo: Path, sha: str) -> str | None:
    result = subprocess.run(
        ["git", "cat-file", "-t", sha],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _resolve_to_full_sha(repo: Path, value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value, re.IGNORECASE):
        raise ValueError(f"malformed source commit: {value!r}")
    obj_type = _git_object_type(repo, value)
    if obj_type is None:
        raise ValueError(f"source commit does not exist: {value!r}")
    if obj_type != "commit":
        raise ValueError(f"source commit is not a commit object: {value!r}")
    return _run_git_checked(repo, "rev-parse", "--verify", f"{value}^{{commit}}")


def _working_tree_diff_files(repo: Path, commit: str) -> set[str]:
    """Return tracked and untracked paths that differ from ``commit``."""
    tracked = _run_git(repo, "diff", "--name-only", commit).splitlines()
    tracked = [f for f in tracked if f.strip()]
    untracked = _run_git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
    untracked = [f for f in untracked if f.strip()]
    return set(tracked + untracked)


def validate_source_commit(
    repo: Path,
    source_commit: str | None,
    allowed_receipt_files: tuple[str, ...],
) -> str:
    """Resolve and validate a source commit for an evidence receipt.

    The function returns the full 40-character SHA of the source commit that the
    evidence will be bound to. It enforces:

    * The SHA exists and is a commit object.
    * The working tree matches that commit except for explicitly allowed receipt
      files.
    * If ``source_commit`` is omitted, the latest commit that is not a
      receipt-only tip is used.
    """
    head = _run_git_checked(repo, "rev-parse", "--verify", "HEAD^{commit}")

    if source_commit is None:
        candidate = head
        while _is_receipt_only_commit(repo, candidate, allowed_receipt_files):
            parent = _run_git(repo, "rev-parse", "--verify", f"{candidate}^")
            if not parent or parent == candidate:
                raise ValueError(
                    "could not determine a non-receipt source commit from HEAD"
                )
            candidate = parent
        resolved = candidate
    else:
        resolved = _resolve_to_full_sha(repo, source_commit)

    diff_files = _working_tree_diff_files(repo, resolved)
    disallowed = [f for f in diff_files if f not in allowed_receipt_files]
    if disallowed:
        raise ValueError(
            f"working tree differs from {resolved} in disallowed files: {sorted(disallowed)}"
        )

    return resolved


def parse_test_count(stdout: str) -> int:
    match = re.search(r"(\d+) passed", stdout)
    if match is None:
        raise ValueError("could not determine passing test count")
    return int(match.group(1))
