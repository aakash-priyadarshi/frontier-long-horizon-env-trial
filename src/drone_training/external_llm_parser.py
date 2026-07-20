"""Strict parser for TALON external-LLM JSON recommendations."""

from __future__ import annotations

import json
import math
import re
from typing import Any

from drone_decision_ground.actions import DecisionAction

from .external_llm_schemas import (
    MAX_DECISION_SUMMARY_CHARS,
    MAX_EVIDENCE_REFS,
    MAX_RESPONSE_BYTES,
    ExternalLLMResponseContract,
)


class ExternalLLMParseError(ValueError):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


_FENCE_RE = re.compile(r"```")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def parse_external_llm_response(
    raw: str | bytes | None,
    *,
    allowed_actions: set[str],
    allowed_evidence_refs: set[str],
    max_bytes: int = MAX_RESPONSE_BYTES,
) -> ExternalLLMResponseContract:
    """Accept exactly one plain JSON object matching the TALON external contract."""

    if raw is None:
        raise ExternalLLMParseError("invalid_json", "response body is missing")
    if isinstance(raw, bytes):
        if len(raw) > max_bytes:
            raise ExternalLLMParseError("oversized_response", "response exceeds byte limit")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ExternalLLMParseError("invalid_json", "response is not UTF-8") from exc
    else:
        text = str(raw)
        if len(text.encode("utf-8")) > max_bytes:
            raise ExternalLLMParseError("oversized_response", "response exceeds byte limit")

    stripped = text.strip()
    if not stripped:
        raise ExternalLLMParseError("invalid_json", "response is empty")
    if _FENCE_RE.search(stripped):
        raise ExternalLLMParseError("invalid_json", "markdown fences are not allowed")
    if _CONTROL_RE.search(stripped):
        raise ExternalLLMParseError("invalid_json", "control characters are not allowed")
    if not stripped.startswith("{"):
        raise ExternalLLMParseError("invalid_json", "response must start with a JSON object")

    decoder = json.JSONDecoder()
    try:
        payload, end = decoder.raw_decode(stripped)
    except json.JSONDecodeError as exc:
        raise ExternalLLMParseError("invalid_json", "response is not valid JSON") from exc
    remainder = stripped[end:].strip()
    if remainder:
        raise ExternalLLMParseError("invalid_json", "extra prose or multiple JSON values are not allowed")
    if not isinstance(payload, dict):
        raise ExternalLLMParseError("schema_invalid", "response must be a JSON object")

    try:
        contract = ExternalLLMResponseContract.model_validate(payload)
    except Exception as exc:  # pydantic ValidationError
        message = str(exc)
        if "confidence" in message.lower() or "nan" in message.lower() or "inf" in message.lower():
            raise ExternalLLMParseError("schema_invalid", "confidence must be a finite value in [0, 1]") from exc
        if "extra" in message.lower() or "forbidden" in message.lower():
            raise ExternalLLMParseError("schema_invalid", "unknown fields are not allowed") from exc
        raise ExternalLLMParseError("schema_invalid", "response does not match the required schema") from exc

    if not math.isfinite(contract.confidence):
        raise ExternalLLMParseError("schema_invalid", "confidence must be finite")
    if len(contract.decision_summary) > MAX_DECISION_SUMMARY_CHARS:
        raise ExternalLLMParseError("schema_invalid", "decision_summary exceeds length bound")
    if len(contract.evidence_refs) > MAX_EVIDENCE_REFS:
        raise ExternalLLMParseError("schema_invalid", "too many evidence_refs")
    if len(set(contract.evidence_refs)) != len(contract.evidence_refs):
        raise ExternalLLMParseError("schema_invalid", "evidence_refs must be unique")
    for ref in contract.evidence_refs:
        if not ref or len(ref) > 80 or not ref.replace("_", "").replace("-", "").isalnum():
            raise ExternalLLMParseError("invalid_evidence_reference", "evidence_refs must be bounded identifiers")
        if ref not in allowed_evidence_refs:
            raise ExternalLLMParseError("invalid_evidence_reference", "evidence_refs must be publicly supplied")

    try:
        action = DecisionAction(contract.action)
    except ValueError as exc:
        raise ExternalLLMParseError("unknown_action", "action is not a known TALON abstract action") from exc
    if action.value not in allowed_actions:
        raise ExternalLLMParseError("action_not_publicly_allowed", "action is outside the public action mask")

    return contract


def contract_to_public_dict(contract: ExternalLLMResponseContract) -> dict[str, Any]:
    return contract.model_dump(mode="json")
