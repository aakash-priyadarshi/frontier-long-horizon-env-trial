from __future__ import annotations

import json

from scripts.verify_milestone_1 import collect_live_evidence, write_receipt


def test_receipt_is_regenerated_from_live_checks(tmp_path) -> None:
    receipt = collect_live_evidence(
        source_commit="test-source-commit",
        verification_command="python scripts/verify_milestone_1.py",
        pytest_command="python -m pytest tests/milestone_1 -q",
        test_count=1,
    )
    output = tmp_path / "live-receipt.json"
    write_receipt(receipt, output)
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded["tested_source_commit"] == "test-source-commit"
    assert loaded["verification"]["outcome"] == "pass"
    assert all(loaded["public_equality"]["channel_equality"].values())
    assert all(loaded["public_equality"]["shared_root_equality"].values())
    assert loaded["public_equality"]["service_state_diverges"] is True
    assert all(loaded["authenticated_snapshot_checks"].values())
    text = output.read_text(encoding="utf-8").lower()
    assert "auth_tag" not in text
    assert "member_selector" not in text
