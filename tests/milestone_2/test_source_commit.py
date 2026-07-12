from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def repo(tmp_path: Path):
    """Create a tiny temporary git repo for source-commit binding tests."""
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts))
    import verify_common

    os.environ["GIT_AUTHOR_NAME"] = "Test"
    os.environ["GIT_AUTHOR_EMAIL"] = "test@example.com"
    os.environ["GIT_COMMITTER_NAME"] = "Test"
    os.environ["GIT_COMMITTER_EMAIL"] = "test@example.com"

    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    (root / "src" / "main.py").parent.mkdir(parents=True, exist_ok=True)
    (root / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (root / "evidence" / "milestone-1-substrate.json").parent.mkdir(parents=True, exist_ok=True)
    (root / "evidence" / "milestone-1-substrate.json").write_text("{}", encoding="utf-8")
    (root / "evidence" / "milestone-2-interaction-layer.json").write_text("{}", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "source"], cwd=root, check=True, capture_output=True)
    return root, verify_common


@pytest.fixture
def source_sha(repo):
    root, _ = repo
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _commit_file(root: Path, path: str, content: str) -> str:
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", path], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", f"update {path}"], cwd=root, check=True, capture_output=True)
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def test_valid_source_commit_clean_tree(repo, source_sha) -> None:
    root, verify_common = repo
    assert verify_common.validate_source_commit(root, source_sha, _allowed()) == source_sha


def test_missing_source_commit_fails(repo, source_sha) -> None:
    root, verify_common = repo
    bad_sha = source_sha[:39] + ("1" if source_sha[-1] != "1" else "0")
    with pytest.raises(ValueError, match="does not exist"):
        verify_common.validate_source_commit(root, bad_sha, _allowed())


def test_garbage_source_commit_fails(repo) -> None:
    root, verify_common = repo
    with pytest.raises(ValueError, match="malformed"):
        verify_common.validate_source_commit(root, "not-a-sha", _allowed())
    with pytest.raises(ValueError, match="malformed"):
        verify_common.validate_source_commit(root, "1234", _allowed())


def test_blob_source_commit_fails(repo) -> None:
    root, verify_common = repo
    result = subprocess.run(
        ["git", "rev-parse", "HEAD:src/main.py"], cwd=root, check=True, capture_output=True, text=True
    )
    blob_sha = result.stdout.strip()
    with pytest.raises(ValueError, match="not a commit object"):
        verify_common.validate_source_commit(root, blob_sha, _allowed())


def test_tree_differing_source_fails(repo, source_sha) -> None:
    root, verify_common = repo
    _commit_file(root, "src/main.py", "changed\n")
    with pytest.raises(ValueError, match="disallowed files"):
        verify_common.validate_source_commit(root, source_sha, _allowed())


def test_uncommitted_source_file_fails(repo, source_sha) -> None:
    root, verify_common = repo
    (root / "src" / "main.py").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ValueError, match="disallowed files"):
        verify_common.validate_source_commit(root, source_sha, _allowed())


def test_receipt_only_tip_with_explicit_source_passes(repo, source_sha) -> None:
    root, verify_common = repo
    _commit_file(root, "evidence/milestone-2-interaction-layer.json", "{\"updated\": true}")
    # HEAD is now a receipt-only tip.
    assert verify_common.validate_source_commit(root, source_sha, _allowed()) == source_sha


def test_receipt_only_tip_default_resolves_to_source(repo, source_sha) -> None:
    root, verify_common = repo
    _commit_file(root, "evidence/milestone-2-interaction-layer.json", "{\"updated\": true}")
    resolved = verify_common.validate_source_commit(root, None, _allowed())
    assert resolved == source_sha


def test_receipt_only_tip_with_disallowed_extra_file_fails(repo, source_sha) -> None:
    root, verify_common = repo
    (root / "src" / "extra.py").write_text("extra\n", encoding="utf-8")
    with pytest.raises(ValueError, match="disallowed files"):
        verify_common.validate_source_commit(root, source_sha, _allowed())


def test_receipt_only_tip_with_untracked_file_fails(repo, source_sha) -> None:
    root, verify_common = repo
    (root / "src" / "untracked.py").write_text("x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="disallowed files"):
        verify_common.validate_source_commit(root, source_sha, _allowed())


def test_m1_allowed_receipts_restricted(repo) -> None:
    root, verify_common = repo
    source_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    _commit_file(root, "evidence/milestone-2-interaction-layer.json", '{"updated": true}')
    # M1 verifier only allows evidence/milestone-1-substrate.json.
    allowed = ("evidence/milestone-1-substrate.json",)
    with pytest.raises(ValueError, match="disallowed files"):
        verify_common.validate_source_commit(root, source_sha, allowed)


def test_short_sha_resolves_to_full(repo, source_sha) -> None:
    root, verify_common = repo
    short_sha = source_sha[:12]
    resolved = verify_common.validate_source_commit(root, short_sha, _allowed())
    assert resolved == source_sha


_allowed = lambda: (
    "evidence/milestone-1-substrate.json",
    "evidence/milestone-2-interaction-layer.json",
)
