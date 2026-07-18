"""Standalone public-only Talon policy worker.

This file is copied into an isolated temporary directory before execution with
``python -I``.  It intentionally has no imports from the simulator, verifier,
training package, application, or repository.
"""

from __future__ import annotations

import builtins
import importlib
import io
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch
from torch import nn

# Editable development installs can add the repository source root through a
# site ``.pth`` file even under ``-I``. Remove every entry that contains a
# privileged Talon package before accepting any policy request.
sys.path[:] = [
    entry
    for entry in sys.path
    if not entry
    or not (
        (Path(entry) / "drone_decision_verifier").exists()
        or (Path(entry) / "drone_training").exists()
        or (Path(entry) / "drone_decision_ground").exists()
    )
]


MAX_MESSAGE_BYTES = 65_536
ACTIONS = (
    "CONTINUE_OBSERVATION", "INCREASE_TRACK_PRIORITY", "REQUEST_SENSOR_CONFIRMATION",
    "REQUEST_COMMAND_LINK_VERIFICATION",
    "CHECK_AUTHORISED_FLIGHT_DATABASE", "REQUEST_REMOTE_ID_VERIFICATION",
    "ALERT_SECURITY_OPERATOR", "ESCALATE_TO_INCIDENT_COMMAND", "NOTIFY_RELEVANT_AUTHORITY",
    "REQUEST_RESPONSE_AUTHORISATION", "RECOMMEND_AUTHORISED_MITIGATION", "STAND_DOWN",
    "ABSTAIN_INSUFFICIENT_EVIDENCE",
)
ACTION_INDEX = {value: index for index, value in enumerate(ACTIONS)}
PADDING = len(ACTIONS)
OBJECTS = ("unknown_aerial_object", "multirotor_drone", "fixed_wing_drone", "helicopter", "crewed_aircraft", "bird", "environmental_return")
REMOTE = ("unknown", "valid", "missing", "inconsistent", "unavailable")
AIRSPACE = ("open", "controlled", "restricted", "temporarily_restricted")
VISIBILITY = ("good", "moderate", "poor", "extreme")
AUTHORITY = ("monitoring_only", "observe_and_alert", "observe_alert_and_escalate", "response_recommendation", "authorised_agency_control")
COMMAND_LINK = ("unknown", "healthy", "degraded", "lost", "not_applicable")
APPROVAL = ("none", "requested", "available", "consumed", "expired", "revoked")
EVIDENCE_KINDS = ("sensor_confirmation", "remote_id", "flight_authorisation", "track_reacquisition", "command_link")
EVIDENCE_STATES = ("pending", "available", "failed", "unavailable", "stale")
MISSING_CODES = ("additional_sensor_confirmation", "authorised_flight_match", "remote_id_match", "track_reacquisition", "operator_availability", "command_link_status")


def one_hot(value, vocabulary):
    if value not in vocabulary:
        raise ValueError("invalid categorical value")
    return [1.0 if value == item else 0.0 for item in vocabulary]


def nullable_boolean(value):
    if value not in (True, False, None):
        raise ValueError("invalid nullable boolean")
    return [float(value is True), float(value is False), float(value is not None)]


def encode(observation):
    if not isinstance(observation, dict) or observation.get("schema_version") != "talon.observation/2.0":
        raise ValueError("invalid observation")
    related = observation["related_tracks"]
    critical = observation["critical_asset_proximity_m"]
    nearest = min((item["distance_m"] for item in related), default=0.0)
    approach = max((item["approach_rate_mps"] for item in related), default=0.0)
    quality = min((item["track_quality"] for item in related), default=0.0)
    values = [
        observation["detection_confidence"], observation["classification_confidence"],
        min(observation["distance_m"] / 200000.0, 1.0),
        min(max(observation["altitude_m"] + 100.0, 0.0) / 30100.0, 1.0),
        min(observation["speed_mps"] / 500.0, 1.0), observation["heading_deg"] / 360.0,
        max(-1.0, min(1.0, observation["approach_rate_mps"] / 500.0)),
        min(observation["track_age_s"] / 86400.0, 1.0), min(observation["missed_frames"] / 10000.0, 1.0),
        observation["track_quality"], observation["sensor_agreement"],
        min((critical if critical is not None else 0.0) / 200000.0, 1.0), float(critical is not None),
        min(len(observation["sensor_sources"]) / 8.0, 1.0), min(observation["evidence_requests_remaining"] / 16.0, 1.0),
        min(len(related) / 7.0, 1.0), min(nearest / 200000.0, 1.0), max(-1.0, min(1.0, approach / 500.0)),
        quality, min(sum(1 for item in related if item["track_stale"]) / 7.0, 1.0),
        float(observation["track_stale"]), float(observation["identity_conflict"]), float(observation["possible_crewed_aircraft"]),
        float(observation["people_nearby"]), float(observation["operator_available"]), float(observation["abstract_response_available"]),
        *nullable_boolean(observation["authorised_flight_match"]), *nullable_boolean(observation["emergency_services_match"]),
        *one_hot(observation["object_class"], OBJECTS), *one_hot(observation["remote_id_status"], REMOTE),
        *one_hot(observation["airspace_status"], AIRSPACE), *one_hot(observation["weather_visibility"], VISIBILITY),
        *one_hot(observation["authority_level"], AUTHORITY), *one_hot(observation["command_link_status"], COMMAND_LINK),
        *one_hot(observation["approval_status"], APPROVAL),
    ]
    evidence = {item["kind"]: item for item in observation["evidence"]}
    for kind in EVIDENCE_KINDS:
        item = evidence.get(kind)
        values.append(float(item is not None))
        values.extend(one_hot(item["status"], EVIDENCE_STATES) if item else [0.0] * len(EVIDENCE_STATES))
        values.append(min(max(observation["timestamp_ms"] - item["requested_at_ms"], 0) / 60000.0, 1.0) if item else 0.0)
        values.append(min(item["request_count"] / 16.0, 1.0) if item else 0.0)
    previous = observation["previous_action"]
    values.append(float(previous is None))
    values.extend(float(previous == action) for action in ACTIONS)
    values.extend(min(sum(1 for item in related if item["object_class"] == object_class) / 7.0, 1.0) for object_class in OBJECTS)
    vector = np.asarray(values, dtype=np.float32)
    if not np.isfinite(vector).all():
        raise ValueError("non-finite feature")
    return vector


class GRU(nn.Module):
    def __init__(self, feature_dim, hidden_dim, layers, dropout):
        super().__init__()
        self.state_projection = nn.Linear(feature_dim, hidden_dim)
        self.action_embedding = nn.Embedding(len(ACTIONS) + 1, hidden_dim, padding_idx=PADDING)
        self.gru = nn.GRU(hidden_dim * 2, hidden_dim, num_layers=layers, batch_first=True, dropout=dropout if layers > 1 else 0.0)
        self.action_head = nn.Linear(hidden_dim, len(ACTIONS))
        self.threat_head = nn.Linear(hidden_dim, 1)
        self.uncertainty_head = nn.Linear(hidden_dim, 1)
        self.missing_evidence_head = nn.Linear(hidden_dim, len(MISSING_CODES))

    def forward(self, states, actions, mask):
        output, _ = self.gru(torch.cat((self.state_projection(states), self.action_embedding(actions)), dim=-1))
        index = mask.sum(dim=1).long().clamp(min=1) - 1
        final = output[torch.arange(output.shape[0]), index]
        return self._heads(final)

    def _heads(self, value):
        return {"action_logits": self.action_head(value), "threat_probability": torch.sigmoid(self.threat_head(value)).squeeze(-1), "uncertainty": torch.sigmoid(self.uncertainty_head(value)).squeeze(-1), "missing_evidence": self.missing_evidence_head(value)}


class Transformer(nn.Module):
    def __init__(self, feature_dim, hidden_dim, layers, heads, context_length, dropout):
        super().__init__()
        self.context_length = context_length
        self.state_embedding = nn.Linear(feature_dim, hidden_dim)
        self.action_embedding = nn.Embedding(len(ACTIONS) + 1, hidden_dim, padding_idx=PADDING)
        self.return_embedding = nn.Linear(1, hidden_dim)
        self.position_embedding = nn.Embedding(context_length, hidden_dim)
        layer = nn.TransformerEncoderLayer(d_model=hidden_dim, nhead=heads, dim_feedforward=hidden_dim * 4, dropout=dropout, activation="gelu", batch_first=True, norm_first=True)
        self.transformer = nn.TransformerEncoder(layer, num_layers=layers, enable_nested_tensor=False)
        self.final_norm = nn.LayerNorm(hidden_dim)
        self.action_head = nn.Linear(hidden_dim, len(ACTIONS))
        self.threat_head = nn.Linear(hidden_dim, 1)
        self.uncertainty_head = nn.Linear(hidden_dim, 1)
        self.missing_evidence_head = nn.Linear(hidden_dim, len(MISSING_CODES))

    def forward(self, states, actions, returns, mask):
        batch, sequence, _ = states.shape
        positions = torch.arange(sequence).unsqueeze(0).expand(batch, sequence)
        tokens = self.state_embedding(states) + self.action_embedding(actions) + self.return_embedding(returns.unsqueeze(-1)) + self.position_embedding(positions)
        causal = torch.triu(torch.ones(sequence, sequence, dtype=torch.bool), diagonal=1)
        encoded = self.transformer(tokens, mask=causal, src_key_padding_mask=~mask.bool())
        index = mask.sum(dim=1).long().clamp(min=1) - 1
        final = self.final_norm(encoded[torch.arange(batch), index])
        return {"action_logits": self.action_head(final), "threat_probability": torch.sigmoid(self.threat_head(final)).squeeze(-1), "uncertainty": torch.sigmoid(self.uncertainty_head(final)).squeeze(-1), "missing_evidence": self.missing_evidence_head(final)}


bundle = torch.load("policy.pt", map_location="cpu", weights_only=True)
if bundle.get("format_version") != "talon.public-policy-bundle/1.0" or bundle.get("actions") != list(ACTIONS):
    raise SystemExit(2)
config = bundle["model_config"]
model = GRU(**config) if bundle["architecture"] == "gru" else Transformer(**config)
model.load_state_dict(bundle["state_dict"], strict=True)
model.eval()
mean = np.asarray(bundle["normalization"]["mean"], dtype=np.float32)
scale = np.asarray(bundle["normalization"]["scale"], dtype=np.float32)
normalization_mask = np.asarray(bundle["normalization"]["normalization_mask"], dtype=np.bool_)
if mean.shape != scale.shape or mean.shape != normalization_mask.shape:
    raise SystemExit(2)
context_length = int(bundle["context_length"])
states_history = []
actions_history = []
returns_history = []
last_action = None


def _deny_filesystem(*_args, **_kwargs):
    raise PermissionError("policy filesystem access denied")


# The policy is weight-only and requires no filesystem after startup. Deny both
# normal file reads and directory discovery for the protocol lifetime.
builtins.open = _deny_filesystem
io.open = _deny_filesystem
os.listdir = _deny_filesystem
os.scandir = _deny_filesystem
os.walk = _deny_filesystem


def emit(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_MESSAGE_BYTES:
        encoded = '{"type":"error","code":"response_too_large"}'
    sys.stdout.write(encoded + "\n")
    sys.stdout.flush()


emit({"type": "ready", "feature_dim": int(mean.shape[0])})
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
            states_history.clear(); actions_history.clear(); returns_history.clear(); last_action = None
            emit({"type": "reset"})
            continue
        if kind == "probe":
            import_results = {}
            for name in (
                "drone_decision_ground",
                "drone_training",
                "drone_decision_verifier",
                "drone_decision_verifier.hidden_scenarios",
            ):
                try:
                    importlib.import_module(name)
                    import_results[name] = False
                except (ImportError, ModuleNotFoundError, AttributeError, ValueError):
                    import_results[name] = True
            source_visible = any(
                any(
                    (Path(entry) / package).exists()
                    for package in (
                        "drone_decision_ground",
                        "drone_training",
                        "drone_decision_verifier",
                    )
                )
                for entry in sys.path
                if entry
            )
            metadata_env = any(any(token in key.upper() for token in ("TALON", "SCENARIO", "VERIFIER", "SECRET")) for key in os.environ)
            filesystem_results = {}
            for name, path in (
                ("privileged_source_read_blocked", "src/drone_decision_ground/actions.py"),
                ("private_dataset_read_blocked", ".frontier/talon/private/dataset.json"),
                ("verifier_storage_read_blocked", "src/drone_decision_verifier/hidden_scenarios.py"),
            ):
                try:
                    builtins.open(path, "rb")
                    filesystem_results[name] = False
                except PermissionError:
                    filesystem_results[name] = True
            try:
                os.listdir(".")
                listing_blocked = False
            except PermissionError:
                listing_blocked = True
            arguments_safe = len(sys.argv) == 1 and not any(token in " ".join(sys.argv).lower() for token in ("scenario", "verifier", "family", "digest"))
            emit(
                {
                    "type": "probe",
                    "python_isolated": sys.flags.isolated == 1,
                    "simulator_import_blocked": import_results["drone_decision_ground"],
                    "training_import_blocked": import_results["drone_training"],
                    "verifier_import_blocked": import_results["drone_decision_verifier"],
                    "hidden_scenario_import_blocked": import_results[
                        "drone_decision_verifier.hidden_scenarios"
                    ],
                    "privileged_source_absent": not source_visible,
                    "metadata_environment_absent": not metadata_env,
                    **filesystem_results,
                    "package_listing_blocked": listing_blocked,
                    "process_arguments_safe": arguments_safe,
                }
            )
            continue
        if kind == "probe_oversized_output":
            emit({"type": "probe", "payload": "x" * (MAX_MESSAGE_BYTES + 1)})
            continue
        if kind == "probe_malformed_output":
            sys.stdout.write("{\n")
            sys.stdout.flush()
            continue
        if kind == "probe_timeout":
            while True:
                pass
        if kind != "recommend" or set(message) != {"type", "observation"}:
            raise ValueError("invalid protocol message")
        observation = message["observation"]
        state = np.where(normalization_mask, (encode(observation) - mean) / scale, 0.0)
        states_history.append(state.astype(np.float32))
        actions_history.append(PADDING if last_action is None else ACTION_INDEX[last_action])
        returns_history.append(float(bundle["return_conditioning_target"]))
        selected_states = states_history[-context_length:]
        selected_actions = actions_history[-context_length:]
        selected_returns = returns_history[-context_length:]
        length = len(selected_states)
        states = np.zeros((1, context_length, mean.shape[0]), dtype=np.float32)
        actions = np.full((1, context_length), PADDING, dtype=np.int64)
        mask = np.zeros((1, context_length), dtype=np.bool_)
        returns = np.zeros((1, context_length), dtype=np.float32)
        states[0, :length] = selected_states; actions[0, :length] = selected_actions; mask[0, :length] = True; returns[0, :length] = selected_returns
        with torch.inference_mode():
            output = model(torch.from_numpy(states), torch.from_numpy(actions), torch.from_numpy(mask)) if bundle["architecture"] == "gru" else model(torch.from_numpy(states), torch.from_numpy(actions), torch.from_numpy(returns), torch.from_numpy(mask))
        probabilities = torch.softmax(output["action_logits"], dim=-1)[0]
        index = int(probabilities.argmax())
        last_action = ACTIONS[index]
        missing = tuple(code for code, probability in zip(MISSING_CODES, torch.sigmoid(output["missing_evidence"])[0]) if float(probability) >= 0.5)
        emit({"type": "recommendation", "recommended_action": last_action, "action_confidence": float(probabilities[index]), "threat_probability": float(output["threat_probability"][0]), "uncertainty": float(output["uncertainty"][0]), "missing_evidence": missing})
    except Exception:
        emit({"type": "error", "code": "invalid_policy_request"})
