"""Authenticated, epoch-bound trace capabilities for the agent surface.

Trace capabilities are HMAC-SHA256 tokens issued by the privileged controller.
Each capability binds a session identity, capability epoch, trace/run identity,
workload identity, fake-clock issue tick, exact allowed selectors, and exact
allowed state views. The key is never written to SQLite, session files, the
workspace, responses, logs, roots, or receipts.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any

from event_service_substrate.canonical import canonical_json

from .errors import ToolError


DOMAIN: str = "trace-capability-v1"
GRANT_DOMAIN: str = "trace-grant-v1"
PLACEHOLDER_DOMAIN: str = "trace-handle-v1"


def _urlsafe_b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_urlsafe_b64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except Exception as exc:
        raise ValueError("invalid capability encoding") from exc


class TraceCapabilityAuthority:
    """Issue and validate opaque trace/state capabilities.

    The capability key is derived from the privileged fixture authority with a
    domain-separating HMAC. It remains in the controller process memory only.
    """

    def __init__(self, key: bytes, scope: str) -> None:
        if len(key) < 32:
            raise ValueError("trace capability key must contain at least 32 bytes")
        if not scope:
            raise ValueError("trace capability scope must be non-empty")
        self._key = key
        self._scope = scope

    @classmethod
    def derive_from_recovery_authority(
        cls, recovery_key: bytes, recovery_scope: str, profile: int
    ) -> "TraceCapabilityAuthority":
        """Derive a domain-separated trace capability authority."""
        trace_key = hmac.new(
            recovery_key,
            f"{DOMAIN}\x00{recovery_scope}\x00{profile}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
        trace_scope = f"trace-{recovery_scope}-{profile}"
        return cls(trace_key, trace_scope)

    def _mac(self, grant: dict[str, Any]) -> str:
        message = GRANT_DOMAIN.encode("utf-8") + b"\x00" + canonical_json(grant)
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def _check_mac(self, grant: dict[str, Any], mac: str) -> None:
        expected = self._mac(grant)
        if not hmac.compare_digest(expected, mac):
            raise ToolError("invalid trace capability", code="invalid_trace_capability")

    def issue(
        self,
        *,
        session_id: str,
        epoch: int,
        run_id: int,
        workload_id: str,
        alias: str,
        tick: int,
        selectors: list[dict[str, Any]],
        views: list[str],
    ) -> str:
        """Issue a new capability token for a trace/run context."""
        grant: dict[str, Any] = {
            "session_id": session_id,
            "epoch": epoch,
            "run_id": run_id,
            "workload_id": workload_id,
            "alias": alias,
            "tick": tick,
            "selectors": selectors,
            "views": sorted(set(views)),
        }
        body = canonical_json(grant)
        mac = hmac.new(self._key, GRANT_DOMAIN.encode("utf-8") + b"\x00" + body, hashlib.sha256).hexdigest()
        return f"{_urlsafe_b64(body)}.{_urlsafe_b64(mac.encode('ascii'))}"

    def derive_placeholder(
        self,
        *,
        session_id: str,
        epoch: int,
        run_id: int,
        workload_id: str,
        alias: str,
        tick: int,
    ) -> str:
        """Return a deterministic, session-local handle placeholder.

        Placeholders are used only during runtime span collection. The final
        correlation handle is a full capability token issued after the run.
        """
        grant: dict[str, Any] = {
            "session_id": session_id,
            "epoch": epoch,
            "run_id": run_id,
            "workload_id": workload_id,
            "alias": alias,
            "tick": tick,
        }
        return "h_" + hashlib.sha256(
            PLACEHOLDER_DOMAIN.encode("utf-8") + b"\x00" + canonical_json(grant)
        ).hexdigest()[:32]

    def parse(self, token: str) -> dict[str, Any]:
        """Parse a token and verify its HMAC; return the decoded grant."""
        if not isinstance(token, str) or "." not in token:
            raise ToolError("invalid trace capability", code="invalid_trace_capability")
        body_b64, mac_b64 = token.split(".", 1)
        try:
            body = _decode_urlsafe_b64(body_b64)
            mac = _decode_urlsafe_b64(mac_b64).decode("ascii")
            grant = json_decode(body)
        except Exception as exc:
            raise ToolError("invalid trace capability", code="invalid_trace_capability") from exc
        if not isinstance(grant, dict):
            raise ToolError("invalid trace capability", code="invalid_trace_capability")
        self._check_mac(grant, mac)
        return grant

    def validate(
        self,
        token: str,
        *,
        session_id: str,
        epoch: int,
        view: str,
        selector: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate a token for the current session, epoch, view and selector."""
        grant = self.parse(token)
        if grant.get("session_id") != session_id:
            raise ToolError("trace capability session mismatch", code="invalid_trace_capability")
        if grant.get("epoch") != epoch:
            raise ToolError("trace capability expired", code="invalid_trace_capability")
        if view not in grant.get("views", []):
            raise ToolError("trace capability view not allowed", code="invalid_trace_capability")
        if selector is not None:
            if not any(value is not None for value in selector.values()):
                raise ToolError("selector is empty", code="invalid_trace_capability")
            allowed = grant.get("selectors", [])
            for allowed_selector in allowed:
                if all(
                    allowed_selector.get(key) == value
                    for key, value in selector.items()
                    if value is not None
                ):
                    return grant
            raise ToolError("selector not allowed by trace capability", code="invalid_trace_capability")
        return grant


def json_decode(data: bytes) -> Any:
    """Decode JSON with explicit error handling."""
    import json

    return json.loads(data.decode("utf-8"))
