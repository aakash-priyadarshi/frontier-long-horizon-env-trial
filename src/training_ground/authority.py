"""Builder-only fixture authority and privileged profile selection."""

from __future__ import annotations

import hashlib
import hmac

from event_service_substrate.authority import RecoveryAuthority

_BUILDER_KEYS = (
    bytes.fromhex("a740d62c0860d7f2d8c0b7261a622d9c8ab44298984e65ff8d53d365e486f731"),
    bytes.fromhex("29e8bc7f706cfe3c428b18b8e41cf03843d8dc4b6f1a3976bccb5e885c1a427e"),
)

_BUILDER_SCOPES = (
    "scope-71e5a88c9bdc47f0",
    "scope-c92f60ad3e7641bb",
)

# Privileged profile oracle key — never exposed in public manifests or observations.
_PROFILE_KEY = bytes.fromhex(
    "6f1c9e2a7b4d8f03c5e1a9d27b6e4f80a3c5d719e2b4f6089a1c3e5d7f92b4a6"
)

_TRANSCRIPT_KEY_CONTEXT = b"transcript-auth-v1"


def authority_for_profile(profile: int) -> RecoveryAuthority:
    if profile not in (0, 1):
        raise ValueError("profile must be 0 or 1")
    return RecoveryAuthority(_BUILDER_KEYS[profile], _BUILDER_SCOPES[profile])


def profile_for_seed(split: str, effective_seed: int) -> int:
    """Derive the privileged pair member from split+seed using a secret key."""
    material = f"{split}:{effective_seed}".encode("utf-8")
    digest = hmac.new(_PROFILE_KEY, material, hashlib.sha256).hexdigest()
    return int(digest, 16) % 2


def profile_binding(profile: int, authority: RecoveryAuthority) -> str:
    """Return a public-safe binding that does not reveal the raw profile value."""
    material = f"profile-binding:{profile}:{authority.scope}".encode("utf-8")
    return hmac.new(authority.key, material, hashlib.sha256).hexdigest()


def transcript_key_for_authority(authority: RecoveryAuthority) -> bytes:
    """Derive a transcript HMAC key from the recovery authority key."""
    return hmac.new(authority.key, _TRANSCRIPT_KEY_CONTEXT, hashlib.sha256).digest()
