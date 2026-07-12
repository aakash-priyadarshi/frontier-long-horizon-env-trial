"""Process-separated JSON tool gateway for the evaluated agent surface.

The privileged controller process owns the AgentSession, RuntimeEngine, StateStore,
fixture, and authority material. The evaluated side communicates only through a
JSON-lines request/response protocol over stdin/stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Any, Type

from .errors import ToolError


class ToolClient:
    """Evaluated-side client that speaks the JSON-lines gateway protocol.

    This object holds only a stdin/stdout pipe pair. It does not have a live
    AgentSession, StateStore, fixture, or profile selector.
    """

    def __init__(self, stdin: Any, stdout: Any, process: subprocess.Popen) -> None:
        self._stdin = stdin
        self._stdout = stdout
        self._process = process
        self._request_id = 0
        self.session_dir: Path | None = None

    def _call(self, tool: str, **arguments: Any) -> Any:
        request_id = str(self._request_id)
        self._request_id += 1
        payload = json.dumps(
            {"id": request_id, "tool": tool, "arguments": arguments},
            ensure_ascii=True,
        )
        self._stdin.write(payload + "\n")
        self._stdin.flush()
        line = self._stdout.readline()
        if not line:
            raise ToolError("gateway closed connection")
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ToolError(f"gateway returned invalid JSON: {exc}") from exc
        if response.get("id") != request_id:
            raise ToolError("gateway response id mismatch")
        if "error" in response:
            raise ToolError(response["error"]["message"])
        return response["result"]

    def release_status(self) -> dict[str, Any]:
        return self._call("release.status")

    def workspace_read(self, path: str) -> str:
        return self._call("workspace.read", path=path)

    def workspace_edit(self, path: str, content: str) -> dict[str, Any]:
        return self._call("workspace.edit", path=path, content=content)

    def telemetry_logs(
        self, alias: str, window: tuple[int, int] | None = None
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"alias": alias}
        if window is not None:
            kwargs["window"] = list(window)
        return self._call("telemetry.logs", **kwargs)

    def telemetry_trace(self, handle: str) -> dict[str, Any]:
        return self._call("telemetry.trace", handle=handle)

    def state_inspect(self, source: str, selector: dict[str, Any], view: str) -> dict[str, Any]:
        return self._call("state.inspect", source=source, selector=selector, view=view)

    def runtime_run(self, workload_id: str, cutpoint: str | None = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"workload_id": workload_id}
        if cutpoint is not None:
            kwargs["cutpoint"] = cutpoint
        return self._call("runtime.run", **kwargs)

    def recovery_pause(self) -> int:
        return self._call("recovery.pause")

    def recovery_restore(self, snapshot_id: str = "S0") -> str:
        return self._call("recovery.restore", snapshot_id=snapshot_id)

    def release_rollback(self, revision: str) -> dict[str, Any]:
        return self._call("release.rollback", revision=revision)

    def release_deploy(self) -> dict[str, Any]:
        return self._call("release.deploy")

    def recovery_resume(self) -> int:
        return self._call("recovery.resume")

    def tool_inventory(self) -> list[str]:
        return self.release_status()["tool_inventory"]

    def leak_probe(self) -> dict[str, Any]:
        return self._call("system.leak_probe")

    def close(self) -> None:
        try:
            self._call("system.close")
        except ToolError:
            pass


class ToolGateway:
    """Builder-side launcher for the privileged controller process.

    Entering the gateway starts the controller and returns a ToolClient that
    exposes only the JSON tool protocol.
    """

    def __init__(
        self,
        profile: int,
        session_dir: Path | str,
        fixture_dir: Path | str,
        authority: Any,
        src_dir: Path | str | None = None,
    ) -> None:
        self.profile = profile
        self.session_dir = Path(session_dir)
        self.fixture_dir = Path(fixture_dir)
        self.authority = authority
        if src_dir is None:
            src_dir = Path(__file__).resolve().parents[2] / "src"
        self.src_dir = Path(src_dir)
        self._process: subprocess.Popen | None = None
        self._client: ToolClient | None = None

    def __enter__(self) -> ToolClient:
        self.session_dir.parent.mkdir(parents=True, exist_ok=True)
        self.fixture_dir.parent.mkdir(parents=True, exist_ok=True)
        config = {
            "profile": self.profile,
            "session_dir": str(self.session_dir),
            "fixture_dir": str(self.fixture_dir),
            "key_hex": self.authority.key.hex(),
            "scope": self.authority.scope,
        }
        config_path = Path(tempfile.mktemp(suffix=".json"))
        config_path.write_text(json.dumps(config), encoding="utf-8")
        env = dict(os.environ)
        pythonpath = env.get("PYTHONPATH", "")
        if pythonpath:
            env["PYTHONPATH"] = f"{self.src_dir}{os.pathsep}{pythonpath}"
        else:
            env["PYTHONPATH"] = str(self.src_dir)
        self._process = subprocess.Popen(
            [sys.executable, "-m", "agent_surface.gateway", "--config", str(config_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            bufsize=1,
            env=env,
        )
        line = self._process.stdout.readline()
        if not line:
            stderr = self._process.stderr.read() if self._process.stderr else ""
            raise RuntimeError(f"gateway controller did not start: {stderr}")
        try:
            ready = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"gateway controller returned invalid ready: {line}") from exc
        if "error" in ready:
            raise RuntimeError(f"gateway controller ready error: {ready['error']}")
        self._client = ToolClient(self._process.stdin, self._process.stdout, self._process)
        self._client.session_dir = Path(ready["result"]["session_dir"])
        return self._client

    def __exit__(
        self,
        exc_type: Type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
        if self._process is not None:
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()


class _Controller:
    """Privileged controller that dispatches JSON tool calls to an AgentSession."""

    _TOOL_MAP: dict[str, str] = {
        "release.status": "release_status",
        "workspace.read": "workspace_read",
        "workspace.edit": "workspace_edit",
        "telemetry.logs": "telemetry_logs",
        "telemetry.trace": "telemetry_trace",
        "state.inspect": "state_inspect",
        "runtime.run": "runtime_run",
        "recovery.pause": "recovery_pause",
        "recovery.restore": "recovery_restore",
        "release.rollback": "release_rollback",
        "release.deploy": "release_deploy",
        "recovery.resume": "recovery_resume",
    }

    def __init__(self, session: Any) -> None:
        self._session = session

    def _dispatch(self, tool: str, arguments: dict[str, Any]) -> Any:
        if tool == "system.close":
            return {}
        if tool == "system.leak_probe":
            return self._session.leak_probe()
        method_name = self._TOOL_MAP.get(tool)
        if method_name is None:
            raise ToolError(f"unknown tool {tool}")
        method = getattr(self._session, method_name)
        return method(**arguments)

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = request.get("id", "unknown")
        try:
            tool = request["tool"]
            arguments = request.get("arguments", {})
            if not isinstance(arguments, dict):
                raise ToolError("arguments must be an object")
            result = self._dispatch(tool, arguments)
            return {"id": request_id, "result": result}
        except ToolError as exc:
            return {"id": request_id, "error": {"message": str(exc)}}
        except RuntimeError as exc:
            return {"id": request_id, "error": {"message": str(exc)}}
        except (ValueError, TypeError, KeyError) as exc:
            return {"id": request_id, "error": {"message": "tool execution failed"}}
        except Exception as exc:
            print(f"gateway controller internal error: {exc}", file=sys.stderr)
            return {"id": request_id, "error": {"message": "tool execution failed"}}

    def serve(self, infile: Any, outfile: Any) -> None:
        while True:
            line = infile.readline()
            if not line:
                break
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                outfile.write(json.dumps({"id": "unknown", "error": {"message": "invalid JSON"}}) + "\n")
                outfile.flush()
                continue
            response = self.handle(request)
            outfile.write(json.dumps(response) + "\n")
            outfile.flush()
            if request.get("tool") == "system.close":
                break


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config_path.unlink(missing_ok=True)

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

    from event_service_substrate import RecoveryAuthority, build_fixture
    from agent_surface.session import AgentSession

    authority = RecoveryAuthority(bytes.fromhex(config["key_hex"]), config["scope"])
    fixture = build_fixture(Path(config["fixture_dir"]), config["profile"], authority)
    session = AgentSession(fixture, config["profile"], Path(config["session_dir"]))
    try:
        controller = _Controller(session)
        sys.stdout.write(
            json.dumps(
                {"id": "ready", "result": {"session_dir": str(session.session_dir)}}
            )
            + "\n"
        )
        sys.stdout.flush()
        controller.serve(sys.stdin, sys.stdout)
    finally:
        session.close()
        fixture.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
