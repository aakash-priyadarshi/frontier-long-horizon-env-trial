"""Integrity and provenance checks against the canonical fixture state."""

from __future__ import annotations

from typing import Any

from event_service_substrate.authority import RecoveryAuthority
from event_service_substrate.store import StateStore


def audit_chain_valid(store: StateStore) -> bool:
    return store.audit_chain_valid()


def snapshot_is_valid(store: StateStore, snapshot_id: str) -> bool:
    return store.snapshot_is_valid(snapshot_id)


def recovery_proof_for_snapshot(store: StateStore, snapshot_id: str, authority: RecoveryAuthority) -> bool:
    """Verify the auth_tag of the most recent snapshot_restore proof."""
    rows = store.rows(
        """
        SELECT proof_id, snapshot_id, pre_state_root, post_state_root, prior_audit_root,
               action_kind, action_tick, actor_scope, audit_seq, audit_entry_hash, auth_tag
        FROM recovery_proofs
        WHERE snapshot_id = ? AND action_kind = 'snapshot_restore'
        ORDER BY audit_seq DESC
        LIMIT 1
        """,
        (snapshot_id,),
    )
    if not rows:
        return False
    row = rows[0]
    fields: dict[str, Any] = {
        "proof_id": row[0],
        "snapshot_id": row[1],
        "pre_state_root": row[2],
        "post_state_root": row[3],
        "prior_audit_root": row[4],
        "action_kind": row[5],
        "action_tick": row[6],
        "actor_scope": row[7],
        "audit_seq": row[8],
        "audit_entry_hash": row[9],
    }
    return authority.recovery_tag_is_valid(fields, row[10])


def state_root_matches(store: StateStore, expected_root: str | None) -> bool:
    if expected_root is None:
        return False
    return store.state_root() == expected_root
