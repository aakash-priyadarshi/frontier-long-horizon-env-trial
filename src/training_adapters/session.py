"""Gateway-backed client that enforces the shared adapter protocol."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Iterator

from agent_surface import ToolClient, ToolError, ToolGateway
from event_service_substrate import RecoveryAuthority

from .protocol import ALLOWED_TOOLS, AdapterRequest, AdapterResponse
from .sanitize import sanitize_adapter_result, sanitize_error_message, sanitize_payload
from .tools import ToolFilter, ToolFilterError

# Deterministic builder-only keys for local adapter sessions (never agent-mounted).
_ADAPTER_KEYS = (
    bytes.fromhex("a740d62c0860d7f2d8c0b7261a622d9c8ab44298984e65ff8d53d365e486f731"),
    bytes.fromhex("29e8bc7f706cfe3c428b18b8e41cf03843d8dc4b6f1a3976bccb5e885c1a427e"),
)
_ADAPTER_SCOPES = (
    "scope-71e5a88c9bdc47f0",
    "scope-c92f60ad3e7641bb",
)


def authority_for_profile(profile: int) -> RecoveryAuthority:
    return RecoveryAuthority(_ADAPTER_KEYS[profile], _ADAPTER_SCOPES[profile])


class ProtocolSession:
    """Evaluated-facing session: twelve tools only, sanitized responses."""

    def __init__(self, client: ToolClient, *, allow_harness_tools: bool = False) -> None:
        self._client = client
        self._filter = ToolFilter(allow_harness_tools=allow_harness_tools)
        self._next_id = 0

    @property
    def session_dir(self) -> Path | None:
        return self._client.session_dir

    def allowed_tools(self) -> list[str]:
        return sorted(self._filter.allowed_tools & set(ALLOWED_TOOLS))

    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> AdapterResponse:
        request = AdapterRequest(id=str(self._next_id), tool=tool, arguments=arguments or {})
        self._next_id += 1
        try:
            filtered = self._filter.filter_request(request)
        except ToolFilterError as exc:
            return AdapterResponse(
                id=request.id,
                ok=False,
                error_code=exc.code,
                error_message=sanitize_error_message(str(exc)),
            )
        try:
            raw = self._client._call(filtered.tool, **dict(filtered.arguments))
            return AdapterResponse(
                id=request.id,
                ok=True,
                result=sanitize_adapter_result(raw),
            )
        except ToolError as exc:
            return AdapterResponse(
                id=request.id,
                ok=False,
                error_code=getattr(exc, "code", "tool_error"),
                error_message=sanitize_error_message(str(exc)),
            )

    def observation(self) -> dict[str, Any]:
        response = self.call("release.status")
        if not response.ok:
            return {"ok": False, "error": response.to_dict()["error"]}
        return {"ok": True, "status": sanitize_payload(response.result)}


class ProtocolGateway:
    """Context manager that owns temp fixture dirs and a ToolGateway."""

    def __init__(self, profile: int = 0, *, work_dir: Path | None = None) -> None:
        self.profile = profile
        self._work_dir = work_dir
        self._temp: tempfile.TemporaryDirectory[str] | None = None
        self._gateway: ToolGateway | None = None
        self.session: ProtocolSession | None = None

    def __enter__(self) -> ProtocolSession:
        if self._work_dir is None:
            self._temp = tempfile.TemporaryDirectory(prefix="training-adapter-")
            base = Path(self._temp.name)
        else:
            base = Path(self._work_dir)
            base.mkdir(parents=True, exist_ok=True)
        self._gateway = ToolGateway(
            self.profile,
            base / "session",
            base / "fixture",
            authority_for_profile(self.profile),
        )
        client = self._gateway.__enter__()
        self.session = ProtocolSession(client)
        return self.session

    def __exit__(self, *exc: Any) -> None:
        if self._gateway is not None:
            self._gateway.__exit__(*exc)
        if self._temp is not None:
            self._temp.cleanup()


def open_protocol_session(profile: int = 0) -> Iterator[ProtocolSession]:
    """Convenience generator for tests and smoke scripts."""
    with ProtocolGateway(profile) as session:
        yield session
