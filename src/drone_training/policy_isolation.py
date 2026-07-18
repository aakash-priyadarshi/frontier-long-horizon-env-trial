"""Narrow client for a public-only isolated policy process."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from queue import Empty, Queue
from typing import Any

import torch

from drone_decision_ground.actions import DecisionRecommendation
from drone_decision_ground.observation import PublicObservation

from .checkpoints import load_checkpoint
from .features import ACTIONS, FEATURE_DIM


class PolicyIsolationError(RuntimeError):
    pass


def _readline_bounded(stream: Any, timeout: float) -> str:
    output: Queue[str | BaseException] = Queue(maxsize=1)

    def read() -> None:
        try:
            output.put(stream.readline())
        except BaseException as exc:
            output.put(exc)

    threading.Thread(target=read, daemon=True).start()
    try:
        value = output.get(timeout=timeout)
    except Empty as exc:
        raise TimeoutError("isolated policy response timed out") from exc
    if isinstance(value, BaseException):
        raise PolicyIsolationError("isolated policy stream failed") from value
    if not value or len(value.encode("utf-8")) > 65_536:
        raise PolicyIsolationError("isolated policy returned an invalid response")
    return value


class IsolatedPolicyClient:
    def __init__(self, checkpoint: Path, *, expected_digest: str, timeout_seconds: float = 10.0) -> None:
        model, metadata = load_checkpoint(checkpoint, expected_digest=expected_digest)
        self.timeout_seconds = timeout_seconds
        self._temporary = tempfile.TemporaryDirectory(prefix="talon-policy-")
        root = Path(self._temporary.name)
        worker_source = Path(__file__).resolve().parents[1] / "talon_policy_runtime" / "standalone_worker.py"
        shutil.copyfile(worker_source, root / "worker.py")
        bundle = {
            "format_version": "talon.public-policy-bundle/1.0",
            "architecture": metadata["architecture"],
            "model_config": metadata["model_config"],
            "feature_dim": FEATURE_DIM,
            "actions": [action.value for action in ACTIONS],
            "normalization": metadata["normalization"],
            "context_length": metadata["context_length"],
            "return_conditioning_target": metadata["return_conditioning_target"],
            "state_dict": model.state_dict(),
        }
        torch.save(bundle, root / "policy.pt")
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP", "CUDA_PATH"}
        }
        self._process = subprocess.Popen(
            [sys.executable, "-I", "worker.py"],
            cwd=root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        ready = self._read()
        if ready != {"type": "ready", "feature_dim": FEATURE_DIM}:
            self.close(force=True)
            raise PolicyIsolationError("isolated policy failed its startup handshake")

    def _read(self) -> dict[str, Any]:
        if self._process.stdout is None:
            raise PolicyIsolationError("isolated policy output is unavailable")
        try:
            value = json.loads(_readline_bounded(self._process.stdout, self.timeout_seconds))
        except (json.JSONDecodeError, TimeoutError) as exc:
            self.close(force=True)
            raise PolicyIsolationError("isolated policy returned a malformed response") from exc
        if not isinstance(value, dict) or value.get("type") == "error":
            raise PolicyIsolationError("isolated policy rejected the request")
        return value

    def _send(self, payload: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 65_536 or self._process.stdin is None:
            raise PolicyIsolationError("isolated policy request is invalid")
        self._process.stdin.write(encoded + "\n")
        self._process.stdin.flush()
        return self._read()

    def reset(self) -> None:
        if self._send({"type": "reset"}).get("type") != "reset":
            raise PolicyIsolationError("isolated policy reset failed")

    def recommend(self, observation: PublicObservation) -> DecisionRecommendation:
        result = self._send({"type": "recommend", "observation": observation.public_dict()})
        if result.get("type") != "recommendation":
            raise PolicyIsolationError("isolated policy recommendation failed")
        return DecisionRecommendation(
            recommended_action=result["recommended_action"],
            target_track_id=observation.track_id,
            valid_until_ms=observation.timestamp_ms + 1_000,
            action_confidence=result["action_confidence"],
            threat_probability=result["threat_probability"],
            uncertainty=result["uncertainty"],
            missing_evidence=tuple(result["missing_evidence"]),
            reason_codes=("isolated_learned_policy",),
        )

    def probe(self) -> dict[str, bool]:
        result = self._send({"type": "probe"})
        if result.get("type") != "probe":
            raise PolicyIsolationError("isolated policy probe failed")
        return {
            key: bool(result[key])
            for key in (
                "privileged_imports_blocked",
                "privileged_source_absent",
                "metadata_environment_absent",
                "filesystem_reads_blocked",
                "package_listing_blocked",
                "process_arguments_safe",
            )
        }

    def close(self, *, force: bool = False) -> None:
        if getattr(self, "_process", None) is not None and self._process.poll() is None:
            if not force:
                try:
                    self._send({"type": "close"})
                except Exception:
                    force = True
            if force and self._process.poll() is None:
                self._process.kill()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
        if getattr(self, "_temporary", None) is not None:
            self._temporary.cleanup()

    def __enter__(self) -> "IsolatedPolicyClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
