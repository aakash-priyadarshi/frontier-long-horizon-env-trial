"""Privileged keyed derivation for public identifiers with no readable labels."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import tempfile
import threading
from pathlib import Path


_LOCK = threading.Lock()
_KEYS: dict[Path, bytes] = {}


def _key_path() -> Path:
    configured = os.environ.get("TALON_DATA_DIR")
    root = Path(configured) if configured else Path(".frontier") / "talon"
    return root / ".instance-id-key"


def _load_key() -> bytes:
    path = _key_path().resolve()
    if path in _KEYS:
        return _KEYS[path]
    with _LOCK:
        if path in _KEYS:
            return _KEYS[path]
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            encoded = path.read_text(encoding="ascii").strip()
            key = bytes.fromhex(encoded)
        except FileNotFoundError:
            key = secrets.token_bytes(32)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".instance-id-key.",
                suffix=".tmp",
                dir=path.parent,
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as handle:
                    handle.write(key.hex() + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    # Another spawned worker atomically published first.
                    key = bytes.fromhex(path.read_text(encoding="ascii").strip())
            finally:
                temporary.unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            raise RuntimeError("opaque identifier key is unavailable") from exc
        if len(key) != 32:
            raise RuntimeError("opaque identifier key is invalid")
        _KEYS[path] = key
        return key


def opaque_hex(*, purpose: str, material: str, length: int) -> str:
    digest = hmac.new(_load_key(), f"{purpose}|{material}".encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:length]
