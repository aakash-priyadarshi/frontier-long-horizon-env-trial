"""Append-only authenticated transcript recording."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def canonical_arguments_digest(arguments: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(arguments).encode("utf-8")).hexdigest()[:32]


def bounded_result_digest(result: Any) -> str:
    return hashlib.sha256(_canonical(result).encode("utf-8")).hexdigest()[:32]


@dataclass
class Transcript:
    """Authenticated append-only transcript for one episode."""

    version: str
    instance_id: str
    split: str
    seed: int
    session_id: str
    profile_binding: str
    hmac_key: bytes
    entries: list[dict[str, Any]] = field(default_factory=list)
    _prev_digest: str = field(default="genesis", repr=False)

    def _mac(self, payload: dict[str, Any]) -> str:
        return hmac.new(
            self.hmac_key,
            _canonical(payload).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def add_step(
        self,
        *,
        sequence: int,
        tick: int,
        tool: str,
        arguments_digest: str,
        success_code: str,
        result_digest: str,
        reward_delta: float,
        terminated: bool,
        truncated: bool,
        cumulative_action_count: int,
        request_bytes: int,
        response_bytes: int,
    ) -> None:
        body = {
            "kind": "step",
            "sequence": sequence,
            "fake_tick": tick,
            "tool": tool,
            "canonical_arguments_digest": arguments_digest,
            "success_error_code": success_code,
            "bounded_public_result_digest": result_digest,
            "reward_delta": reward_delta,
            "terminated": terminated,
            "truncated": truncated,
            "cumulative_action_count": cumulative_action_count,
            "request_bytes": request_bytes,
            "response_bytes": response_bytes,
            "session_id": self.session_id,
            "instance_id": self.instance_id,
            "split": self.split,
            "seed": self.seed,
            "profile_binding": self.profile_binding,
            "previous_step_digest": self._prev_digest,
        }
        auth_tag = self._mac(body)
        step_digest = hashlib.sha256(
            _canonical({**body, "auth_tag": auth_tag}).encode("utf-8")
        ).hexdigest()
        entry = {**body, "auth_tag": auth_tag, "step_digest": step_digest}
        self.entries.append(entry)
        self._prev_digest = step_digest

    def add_meta(self, key: str, value: Any) -> None:
        self.entries.append({"kind": "meta", "key": key, "value": value})

    def digest(self) -> str:
        payload = _canonical([e for e in self.entries if e.get("kind") == "step"])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def chain_mac(self) -> str:
        return self._mac(
            {
                "session_id": self.session_id,
                "instance_id": self.instance_id,
                "split": self.split,
                "seed": self.seed,
                "profile_binding": self.profile_binding,
                "transcript_digest": self.digest(),
                "final_prev": self._prev_digest,
            }
        )

    def to_list(self) -> list[dict[str, Any]]:
        header = {
            "kind": "meta",
            "environment_version": self.version,
            "instance_id": self.instance_id,
            "split": self.split,
            "seed": self.seed,
            "session_id": self.session_id,
            "profile_binding": self.profile_binding,
            "transcript_digest": self.digest(),
            "chain_mac": self.chain_mac(),
        }
        return [header, *self.entries]


def verify_transcript(
    transcript: list[dict[str, Any]],
    *,
    session_id: str,
    instance_id: str,
    split: str,
    seed: int,
    profile_binding: str,
    key: bytes,
) -> bool:
    """Return True iff the transcript chain authenticates under the given key."""
    if not transcript:
        return False
    header = transcript[0]
    if header.get("kind") != "meta":
        return False
    if header.get("session_id") != session_id:
        return False
    if header.get("instance_id") != instance_id:
        return False
    if header.get("split") != split:
        return False
    if header.get("seed") != seed:
        return False
    if header.get("profile_binding") != profile_binding:
        return False

    prev = "genesis"
    step_entries: list[dict[str, Any]] = []
    for entry in transcript[1:]:
        if entry.get("kind") != "step":
            continue
        body = {
            k: entry.get(k)
            for k in (
                "kind",
                "sequence",
                "fake_tick",
                "tool",
                "canonical_arguments_digest",
                "success_error_code",
                "bounded_public_result_digest",
                "reward_delta",
                "terminated",
                "truncated",
                "cumulative_action_count",
                "request_bytes",
                "response_bytes",
                "session_id",
                "instance_id",
                "split",
                "seed",
                "profile_binding",
                "previous_step_digest",
            )
        }
        expected_tag = hmac.new(
            key, _canonical(body).encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_tag, str(entry.get("auth_tag", ""))):
            return False
        if body.get("previous_step_digest") != prev:
            return False
        if body.get("session_id") != session_id:
            return False
        if body.get("instance_id") != instance_id:
            return False
        if body.get("split") != split:
            return False
        if body.get("seed") != seed:
            return False
        if body.get("profile_binding") != profile_binding:
            return False
        step_digest = hashlib.sha256(
            _canonical({**body, "auth_tag": expected_tag}).encode("utf-8")
        ).hexdigest()
        if entry.get("step_digest") != step_digest:
            return False
        prev = step_digest
        step_entries.append(entry)

    digest = hashlib.sha256(
        _canonical(step_entries).encode("utf-8")
    ).hexdigest()[:32]
    if header.get("transcript_digest") != digest:
        return False
    expected_chain = hmac.new(
        key,
        _canonical(
            {
                "session_id": session_id,
                "instance_id": instance_id,
                "split": split,
                "seed": seed,
                "profile_binding": profile_binding,
                "transcript_digest": digest,
                "final_prev": prev,
            }
        ).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_chain, str(header.get("chain_mac", "")))
