"""Standalone weight-only discrete CQL worker executed with ``python -I``.

The host supplies only normalized public feature histories and public action
masks.  Simulator, verifier, dataset, reward and scenario metadata are absent.
"""

from __future__ import annotations

import builtins
import importlib
import io
import json
import os
import sys
from pathlib import Path

import torch
from torch import nn

sys.path[:] = [
    entry for entry in sys.path
    if not entry or not any((Path(entry) / package).exists() for package in (
        "drone_decision_ground", "drone_training", "drone_decision_verifier"
    ))
]

MAX_MESSAGE_BYTES = 65_536


class ConservativeQNetwork(nn.Module):
    def __init__(self, feature_dim, action_count, hidden_dim=256, layers=2, dropout=0.1):
        super().__init__()
        self.encoder = nn.GRU(feature_dim, hidden_dim, num_layers=layers, batch_first=True, dropout=dropout if layers > 1 else 0.0)
        self.reward_head = nn.Linear(hidden_dim, action_count)
        self.safety_head = nn.Linear(hidden_dim, action_count)

    def forward(self, states, mask):
        encoded, _ = self.encoder(states)
        indices = mask.sum(dim=1).clamp(min=1).long() - 1
        final = encoded[torch.arange(encoded.shape[0]), indices]
        return self.reward_head(final), torch.sigmoid(self.safety_head(final))


bundle = torch.load("policy.pt", map_location="cpu", weights_only=True)
actions = tuple(bundle.get("actions", ()))
feature_dim = int(bundle.get("feature_dim", 0))
context_length = int(bundle.get("context_length", 0))
if bundle.get("format_version") != "talon.public-offline-policy-bundle/1.0" or len(actions) < 2 or feature_dim < 1 or context_length < 1:
    raise SystemExit(2)
config = dict(bundle["model_config"])
model = ConservativeQNetwork(feature_dim, len(actions), **config)
model.load_state_dict(bundle["state_dict"], strict=True)
model.eval()
safety_threshold = float(bundle["safety_threshold"])
abstain_index = actions.index("ABSTAIN_INSUFFICIENT_EVIDENCE")


def deny_filesystem(*_args, **_kwargs):
    raise PermissionError("policy filesystem access denied")


builtins.open = deny_filesystem
io.open = deny_filesystem
os.listdir = deny_filesystem
os.scandir = deny_filesystem
os.walk = deny_filesystem


def emit(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_MESSAGE_BYTES:
        encoded = '{"type":"error","code":"response_too_large"}'
    sys.stdout.write(encoded + "\n")
    sys.stdout.flush()


emit({"type": "ready", "feature_dim": feature_dim})
for raw in sys.stdin:
    if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
        emit({"type": "error", "code": "request_too_large"})
        continue
    try:
        message = json.loads(raw)
        kind = message.get("type") if isinstance(message, dict) else None
        if kind == "close":
            emit({"type": "closed"})
            break
        if kind == "reset":
            emit({"type": "reset"})
            continue
        if kind == "probe":
            blocked = {}
            for name in ("drone_decision_ground", "drone_training", "drone_decision_verifier", "drone_decision_verifier.hidden_scenarios"):
                try:
                    importlib.import_module(name)
                    blocked[name] = False
                except (ImportError, ModuleNotFoundError, AttributeError, ValueError):
                    blocked[name] = True
            emit({
                "type": "probe",
                "python_isolated": sys.flags.isolated == 1,
                "simulator_import_blocked": blocked["drone_decision_ground"],
                "training_import_blocked": blocked["drone_training"],
                "verifier_import_blocked": blocked["drone_decision_verifier"],
                "hidden_scenario_import_blocked": blocked["drone_decision_verifier.hidden_scenarios"],
                "filesystem_blocked": True,
            })
            continue
        if kind != "recommend" or set(message) != {"type", "states", "sequence_mask", "action_mask"}:
            raise ValueError("invalid protocol message")
        states = torch.tensor(message["states"], dtype=torch.float32)
        sequence_mask = torch.tensor(message["sequence_mask"], dtype=torch.bool)
        action_mask = torch.tensor(message["action_mask"], dtype=torch.bool)
        if states.shape != (1, context_length, feature_dim) or sequence_mask.shape != (1, context_length) or action_mask.shape != (len(actions),):
            raise ValueError("invalid public policy tensor shape")
        with torch.inference_mode():
            reward_q, safety_q = model(states, sequence_mask)
        eligible = action_mask & (safety_q[0] <= safety_threshold)
        if eligible.any():
            ranked_q = reward_q[0].masked_fill(~eligible, -torch.inf)
            selected = int(ranked_q.argmax())
        else:
            selected = abstain_index
        ranking = sorted(
            (
                {
                    "action": actions[index],
                    "operational_q": float(reward_q[0, index]),
                    "safety_q": float(safety_q[0, index]),
                    "publicly_valid": bool(action_mask[index]),
                    "below_safety_threshold": bool(safety_q[0, index] <= safety_threshold),
                }
                for index in range(len(actions))
            ),
            key=lambda item: (-item["operational_q"], item["action"]),
        )[:5]
        emit({
            "type": "recommendation",
            "recommended_action": actions[selected],
            "action_confidence": float(torch.softmax(reward_q[0].masked_fill(~action_mask, -torch.inf), dim=0)[selected]),
            "abstained": not bool(eligible.any()) or selected == abstain_index,
            "top_action_scores": ranking,
        })
    except Exception:
        emit({"type": "error", "code": "invalid_policy_request"})
