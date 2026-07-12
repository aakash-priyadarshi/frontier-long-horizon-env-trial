"""Builder-only fixture authority for training environment instances."""

from __future__ import annotations

from event_service_substrate.authority import RecoveryAuthority

_BUILDER_KEYS = (
    bytes.fromhex("a740d62c0860d7f2d8c0b7261a622d9c8ab44298984e65ff8d53d365e486f731"),
    bytes.fromhex("29e8bc7f706cfe3c428b18b8e41cf03843d8dc4b6f1a3976bccb5e885c1a427e"),
)

_BUILDER_SCOPES = (
    "scope-71e5a88c9bdc47f0",
    "scope-c92f60ad3e7641bb",
)


def authority_for_profile(profile: int) -> RecoveryAuthority:
    if profile not in (0, 1):
        raise ValueError("profile must be 0 or 1")
    return RecoveryAuthority(_BUILDER_KEYS[profile], _BUILDER_SCOPES[profile])
