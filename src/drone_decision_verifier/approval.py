"""Privileged, integrity-protected simulated human approval authority."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import re
from dataclasses import dataclass, replace

from drone_decision_ground.actions import DecisionAction
from drone_decision_ground.approval_protocol import ApprovalCheck
from drone_decision_ground.observation import ApprovalPublicStatus


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    nonce: str
    issued_at_ms: int
    expires_at_ms: int
    episode_id: str
    track_id: str
    requested_action: DecisionAction
    authority_profile: str
    authority_profile_version: str
    approver_scope: str
    state_revision: int
    status: str
    consumed_at_ms: int | None
    integrity_tag: str


def _canonical(record: ApprovalRecord) -> bytes:
    value = {
        "approval_id": record.approval_id,
        "nonce": record.nonce,
        "issued_at_ms": record.issued_at_ms,
        "expires_at_ms": record.expires_at_ms,
        "episode_id": record.episode_id,
        "track_id": record.track_id,
        "requested_action": record.requested_action.value,
        "authority_profile": record.authority_profile,
        "authority_profile_version": record.authority_profile_version,
        "approver_scope": record.approver_scope,
        "state_revision": record.state_revision,
        "status": record.status,
        "consumed_at_ms": record.consumed_at_ms,
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


class SimulatedApprovalAuthority:
    """Issues and atomically consumes one-time simulated approvals."""

    def __init__(self, secret: bytes | None = None) -> None:
        self._secret = secret or secrets.token_bytes(32)
        self._records: dict[str, ApprovalRecord] = {}
        self._lock = threading.RLock()

    def _tag(self, record: ApprovalRecord) -> str:
        return hmac.new(self._secret, _canonical(record), hashlib.sha256).hexdigest()

    def issue(
        self,
        *,
        now_ms: int,
        ttl_ms: int,
        episode_id: str,
        track_id: str,
        requested_action: DecisionAction,
        authority_profile: str,
        authority_profile_version: str,
        approver_scope: str,
        state_revision: int,
    ) -> ApprovalRecord:
        if ttl_ms < 1 or ttl_ms > 60_000:
            raise ValueError("approval lifetime is outside the permitted range")
        if not re.fullmatch(r"ep_[a-f0-9]{24}", episode_id):
            raise ValueError("approval episode binding is invalid")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", track_id):
            raise ValueError("approval track binding is invalid")
        if requested_action is not DecisionAction.RECOMMEND_AUTHORISED_MITIGATION:
            raise ValueError("approval may bind only the highest abstract recommendation")
        if approver_scope != "simulated_incident_commander":
            raise ValueError("approval scope is not authorised")
        if state_revision < 0:
            raise ValueError("approval state revision is invalid")
        draft = ApprovalRecord(
            approval_id="apr_" + secrets.token_hex(12),
            nonce=secrets.token_urlsafe(32),
            issued_at_ms=now_ms,
            expires_at_ms=now_ms + ttl_ms,
            episode_id=episode_id,
            track_id=track_id,
            requested_action=requested_action,
            authority_profile=authority_profile,
            authority_profile_version=authority_profile_version,
            approver_scope=approver_scope,
            state_revision=state_revision,
            status="active",
            consumed_at_ms=None,
            integrity_tag="",
        )
        record = replace(draft, integrity_tag=self._tag(draft))
        with self._lock:
            self._records[record.approval_id] = record
        return record

    def public_summary(self, approval_id: str | None, *, now_ms: int) -> dict[str, object]:
        with self._lock:
            record = self._records.get(approval_id or "")
            if record is None:
                return {
                    "approval_status": ApprovalPublicStatus.NONE,
                    "approval_id": None,
                    "approval_expires_at_ms": None,
                    "approval_scope_digest": None,
                }
            status = ApprovalPublicStatus.AVAILABLE
            if record.status == "consumed":
                status = ApprovalPublicStatus.CONSUMED
            elif record.status == "revoked":
                status = ApprovalPublicStatus.REVOKED
            elif now_ms >= record.expires_at_ms:
                status = ApprovalPublicStatus.EXPIRED
            scope_digest = "sha256:" + hashlib.sha256(_canonical(record)).hexdigest()
            return {
                "approval_status": status,
                "approval_id": record.approval_id,
                "approval_expires_at_ms": record.expires_at_ms,
                "approval_scope_digest": scope_digest,
            }

    def consume(
        self,
        *,
        approval_id: str | None,
        episode_id: str,
        track_id: str,
        requested_action: DecisionAction,
        authority_profile: str,
        authority_profile_version: str,
        state_revision: int,
        now_ms: int,
    ) -> ApprovalCheck:
        with self._lock:
            record = self._records.get(approval_id or "")
            if record is None:
                return ApprovalCheck(accepted=False, reason_code="valid_approval_required")
            if not hmac.compare_digest(record.integrity_tag, self._tag(record)):
                return ApprovalCheck(accepted=False, reason_code="approval_integrity_invalid")
            if record.status == "consumed":
                return ApprovalCheck(accepted=False, reason_code="approval_already_consumed")
            if record.status == "revoked":
                return ApprovalCheck(accepted=False, reason_code="approval_revoked")
            if now_ms >= record.expires_at_ms:
                return ApprovalCheck(accepted=False, reason_code="approval_expired")
            if record.episode_id != episode_id:
                return ApprovalCheck(accepted=False, reason_code="approval_episode_mismatch")
            if record.track_id != track_id:
                return ApprovalCheck(accepted=False, reason_code="approval_track_mismatch")
            if record.requested_action is not requested_action:
                return ApprovalCheck(accepted=False, reason_code="approval_action_mismatch")
            if record.authority_profile != authority_profile:
                return ApprovalCheck(accepted=False, reason_code="approval_profile_mismatch")
            if record.authority_profile_version != authority_profile_version:
                return ApprovalCheck(accepted=False, reason_code="approval_profile_version_mismatch")
            if record.state_revision != state_revision:
                return ApprovalCheck(accepted=False, reason_code="approval_state_changed")
            consumed = replace(
                record,
                status="consumed",
                consumed_at_ms=now_ms,
                integrity_tag="",
            )
            self._records[record.approval_id] = replace(
                consumed,
                integrity_tag=self._tag(consumed),
            )
            return ApprovalCheck(accepted=True, reason_code="approval_consumed", consumed=True)

    def revoke_episode(self, episode_id: str) -> None:
        with self._lock:
            for approval_id, record in tuple(self._records.items()):
                if record.episode_id == episode_id and record.status == "active":
                    revoked = replace(record, status="revoked", integrity_tag="")
                    self._records[approval_id] = replace(
                        revoked,
                        integrity_tag=self._tag(revoked),
                    )

    def record(self, approval_id: str) -> ApprovalRecord | None:
        with self._lock:
            return self._records.get(approval_id)
