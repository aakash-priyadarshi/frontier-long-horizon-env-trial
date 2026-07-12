from __future__ import annotations

from training_adapters.protocol import ALLOWED_TOOLS, AdapterRequest, PROTOCOL_VERSION
from training_adapters.tools import ToolFilter, ToolFilterError


def test_allowed_tools_are_exactly_twelve() -> None:
    assert len(ALLOWED_TOOLS) == 12
    assert len(set(ALLOWED_TOOLS)) == 12


def test_filter_rejects_unknown_and_harness_tools() -> None:
    filt = ToolFilter()
    for tool in ("_store", "bash", "system.leak_probe", "system.close", ""):
        try:
            filt.check(tool)
            raise AssertionError(f"expected reject for {tool}")
        except ToolFilterError:
            pass


def test_filter_accepts_inventory() -> None:
    filt = ToolFilter()
    for tool in ALLOWED_TOOLS:
        assert filt.check(tool) == tool


def test_request_roundtrip() -> None:
    req = AdapterRequest(id="1", tool="release.status", arguments={})
    data = req.to_dict()
    assert data["protocol_version"] == PROTOCOL_VERSION
    again = AdapterRequest.from_dict(data)
    assert again.tool == "release.status"
