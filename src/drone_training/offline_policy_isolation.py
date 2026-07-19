"""Narrow isolated-process client for frozen Talon CQL inference."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import torch

from drone_decision_ground.actions import DecisionRecommendation
from drone_decision_ground.observation import PublicObservation

from .features import ACTIONS, FEATURE_DIM, apply_normalization, encode_observation
from .manifests import NormalizationStats
from .offline_checkpoints import load_offline_checkpoint
from .offline_rl import public_action_mask
from .policy_isolation import PolicyIsolationError, _readline_bounded


class IsolatedCQLPolicyClient:
    def __init__(
        self,
        checkpoint: Path,
        *,
        expected_digest: str,
        expected_offline_dataset_digest: str | None = None,
        expected_source_dataset_digest: str | None = None,
        timeout_seconds: float = 10.0,
        profile_id: str = "uk_monitor_and_escalate",
    ) -> None:
        if (expected_offline_dataset_digest is None) ^ (expected_source_dataset_digest is None):
            raise ValueError("offline and source dataset digests must both be provided")
        model, _target, metadata = load_offline_checkpoint(
            checkpoint,
            expected_digest=expected_digest,
            expected_offline_dataset_digest=expected_offline_dataset_digest,
            expected_source_dataset_digest=expected_source_dataset_digest,
        )
        self.expected_digest = expected_digest
        self.expected_offline_dataset_digest = expected_offline_dataset_digest
        self.expected_source_dataset_digest = expected_source_dataset_digest
        self.timeout_seconds = timeout_seconds
        self.profile_id = profile_id
        self.context_length = int(metadata["context_length"])
        self.normalization = NormalizationStats.model_validate(metadata["normalization"])
        self._history: list[np.ndarray] = []
        self.last_diagnostics: dict[str, Any] = {}
        self._temporary = tempfile.TemporaryDirectory(prefix="talon-cql-policy-")
        root = Path(self._temporary.name)
        worker_source = Path(__file__).resolve().parents[1] / "talon_policy_runtime" / "offline_worker.py"
        shutil.copyfile(worker_source, root / "worker.py")
        torch.save({
            "format_version": "talon.public-offline-policy-bundle/1.0",
            "model_config": metadata["model_config"],
            "feature_dim": FEATURE_DIM,
            "actions": [item.value for item in ACTIONS],
            "context_length": self.context_length,
            "safety_threshold": metadata["safety_threshold"],
            "state_dict": model.state_dict(),
        }, root / "policy.pt")
        environment = {key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP", "CUDA_PATH"}}
        self._process = subprocess.Popen(
            [sys.executable, "-I", "worker.py"], cwd=root, env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1,
        )
        ready = self._read()
        if ready != {"type": "ready", "feature_dim": FEATURE_DIM}:
            self.close(force=True)
            raise PolicyIsolationError("isolated CQL policy failed its startup handshake")

    def _read(self) -> dict[str, Any]:
        if self._process.stdout is None:
            raise PolicyIsolationError("isolated CQL policy output is unavailable")
        try:
            value = json.loads(_readline_bounded(self._process.stdout, self.timeout_seconds))
        except Exception as exc:
            self.close(force=True)
            raise PolicyIsolationError("isolated CQL policy returned a malformed response") from exc
        if not isinstance(value, dict) or value.get("type") == "error":
            raise PolicyIsolationError("isolated CQL policy rejected the request")
        return value

    def _send(self, value: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 65_536 or self._process.stdin is None:
            raise PolicyIsolationError("isolated CQL policy request is invalid")
        self._process.stdin.write(encoded + "\n")
        self._process.stdin.flush()
        return self._read()

    def reset(self) -> None:
        self._history = []
        self.last_diagnostics = {}
        if self._send({"type": "reset"}).get("type") != "reset":
            raise PolicyIsolationError("isolated CQL policy reset failed")

    def recommend(self, observation: PublicObservation) -> DecisionRecommendation:
        self._history.append(apply_normalization(encode_observation(observation), self.normalization))
        selected = self._history[-self.context_length:]
        states = np.zeros((1, self.context_length, FEATURE_DIM), dtype=np.float32)
        sequence_mask = np.zeros((1, self.context_length), dtype=np.bool_)
        states[0, :len(selected)] = selected
        sequence_mask[0, :len(selected)] = True
        result = self._send({
            "type": "recommend",
            "states": states.tolist(),
            "sequence_mask": sequence_mask.tolist(),
            "action_mask": list(public_action_mask(observation, profile_id=self.profile_id)),
        })
        if result.get("type") != "recommendation":
            raise PolicyIsolationError("isolated CQL recommendation failed")
        self.last_diagnostics = {
            "abstained": bool(result["abstained"]),
            "top_action_scores": result["top_action_scores"],
        }
        return DecisionRecommendation(
            recommended_action=result["recommended_action"],
            target_track_id=observation.track_id,
            valid_until_ms=observation.timestamp_ms + 1_000,
            action_confidence=result["action_confidence"],
            threat_probability=0.5,
            uncertainty=max(0.0, min(1.0, 1.0 - float(result["action_confidence"]))),
            reason_codes=("isolated_conservative_offline_policy",),
        )

    def probe(self) -> dict[str, bool]:
        result = self._send({"type": "probe"})
        if result.get("type") != "probe":
            raise PolicyIsolationError("isolated CQL policy probe failed")
        return {key: bool(value) for key, value in result.items() if key != "type"}

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
                self._process.kill(); self._process.wait(timeout=5)
        if getattr(self, "_temporary", None) is not None:
            self._temporary.cleanup()

    def __enter__(self) -> "IsolatedCQLPolicyClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
