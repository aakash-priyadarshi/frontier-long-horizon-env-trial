"""Construction of deterministic, surface-matched service fixtures."""

from __future__ import annotations

import difflib
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from .authority import RecoveryAuthority
from .canonical import canonical_json, digest, tree_root
from .store import SCHEMA_TABLES, StateStore


TICKET: Final[str] = (
    "After yesterday's mitigation reduced delivery retries, request alias `Q-41` "
    "still produced two settlement records. The public canary is green once, but "
    "the incident remains open because the mitigation also dropped a recovery "
    "attempt. Restore safe operation and resolve the duplicate without disabling "
    "settlement delivery or retry support."
)

VISIBLE_LOGS: Final[tuple[str, ...]] = (
    "t=041 intake accepted alias=Q-41",
    "t=042 delivery window opened alias=Q-41 attempt=1",
    "t=043 delivery boundary interrupted alias=Q-41",
    "t=044 delivery window opened alias=Q-41 attempt=1",
    "t=045 settlement observed alias=Q-41 count=2",
)

CODE_FILES: Final[tuple[Path, ...]] = (
    Path("service/contract.md"),
    Path("service/flow.py"),
    Path("service/store.py"),
    Path("service/runtime.py"),
)
CONFIG_FILE: Final[Path] = Path("service/settings.toml")

_EVENT_PRIMARY: Final[str] = "evt_74c31f146a5d4e198f83b2d7619a0c5e"
_EVENT_ADDITIONAL: Final[str] = "evt_c92580b73e124da59b641f037a6e82d4"
_EFFECT_PRIMARY: Final[str] = "efx_03f1ab9857434fcaaad46d5d1289ce70"
_EFFECT_REPLAY: Final[str] = "efx_aa2874f0c5314c54b136df95e4a8207c"
_EFFECT_ADDITIONAL: Final[str] = "efx_d5899ca5c24e48d39f6e873ab020154b"
_COMMAND_KEY: Final[str] = "cmd_8ef23dbbb32b4cb3aaeb2fb0e2a14ce1"
_OCCURRENCE: Final[str] = "occ_f42e1a985e8b45f3a6bc9757dd2c6409"


def _settings(attempt_budget: int) -> bytes:
    return (
        "[service]\n"
        "intake_enabled = true\n"
        "settlement_enabled = true\n"
        f"attempt_budget = {attempt_budget}\n"
        'transient_behavior = "retry"\n'
    ).encode("utf-8")


def _config_root(config_bytes: bytes) -> str:
    return digest("config-v1", config_bytes)


@dataclass
class ServiceFixture:
    root: Path
    workspace: Path
    store: StateStore
    source_root: str

    def close(self) -> None:
        self.store.close()

    def _revision_artifact(self, revision: str) -> tuple[str, str]:
        row = self.store.rows(
            "SELECT config_root, config_bytes FROM deployments WHERE revision = ?",
            (revision,),
        )
        if len(row) != 1:
            raise KeyError(revision)
        config_root, config_text = row[0]
        actual_root = _config_root(config_text.encode("utf-8"))
        if config_root != actual_root:
            raise RuntimeError("deployment configuration root does not match its artifact")
        return config_root, config_text

    def _active_revision(self) -> tuple[str, str, str]:
        active = self.store.rows(
            """
            SELECT revision, config_root, config_bytes
            FROM deployments WHERE status = 'active'
            """
        )
        if len(active) != 1:
            raise RuntimeError("exactly one revision must be active")
        revision, config_root, config_text = active[0]
        actual_root = _config_root(config_text.encode("utf-8"))
        if config_root != actual_root:
            raise RuntimeError("active configuration root does not match its artifact")
        return revision, config_root, config_text

    def roots(self) -> dict[str, str]:
        _, active_config_root, _ = self._active_revision()
        return {
            "source": self.source_root,
            "config": active_config_root,
            "service_state": self.store.state_root(),
            "deployment": self.store.deployment_root(),
            "runtime": self.store.runtime_root(),
            "telemetry": self.store.telemetry_root(),
            "audit": self.store.audit_root(),
            "snapshot": self.store.snapshot_root(),
        }

    def visible_logs(self) -> tuple[str, ...]:
        rows = self.store.rows(
            "SELECT message FROM telemetry WHERE channel = 'public' ORDER BY seq"
        )
        return tuple(row[0] for row in rows)

    def public_status(self) -> dict[str, Any]:
        active_revision, active_config_root, active_config_text = self._active_revision()
        parsed = tomllib.loads(active_config_text)
        attempt_budget = int(parsed["service"]["attempt_budget"])
        roots = self.roots()
        return {
            "ticket": TICKET,
            "alias": "Q-41",
            "fake_tick": self.store.tick(),
            "intake": self.store.runtime_value("intake_state"),
            "active_revision": active_revision,
            "active_config_root": active_config_root,
            "attempt_budget": attempt_budget,
            "public_canary": "green_once",
            "incident": "open",
            "visible_effect_count": self.store.count("effects"),
            "logs": list(self.visible_logs()),
            "shared_roots": {
                name: roots[name]
                for name in (
                    "source",
                    "config",
                    "deployment",
                    "runtime",
                    "telemetry",
                    "audit",
                    "snapshot",
                )
            },
        }

    def public_bytes(self) -> bytes:
        files = []
        for path in sorted((*CODE_FILES, CONFIG_FILE), key=lambda item: item.as_posix()):
            files.append((path.as_posix(), (self.workspace / path).read_bytes()))
        return canonical_json(
            {
                "files": [(path, data.decode("utf-8")) for path, data in files],
                "status": self.public_status(),
                "revision_diff": self.revision_diff(),
            }
        )

    def revision_diff(self) -> str:
        _, r0_text = self._revision_artifact("r0")
        _, r1_text = self._revision_artifact("r1")
        return "".join(
            difflib.unified_diff(
                r0_text.splitlines(keepends=True),
                r1_text.splitlines(keepends=True),
                fromfile="r0/settings.toml",
                tofile="r1/settings.toml",
            )
        )

    def pause_intake(self) -> int:
        return self.store.pause_intake()

    def restore(self, snapshot_id: str = "S0") -> str:
        return self.store.restore_snapshot(snapshot_id)


def _copy_workspace(destination: Path) -> None:
    template = Path(__file__).parent / "public_template"
    shutil.copytree(
        template,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    # Normalize text templates to LF so Windows checkouts with CRLF still match
    # the canonical deployment artifacts used by build_fixture.
    settings_path = destination / CONFIG_FILE
    if settings_path.is_file():
        settings_path.write_bytes(settings_path.read_bytes().replace(b"\r\n", b"\n"))


def _register_revisions(store: StateStore, source_root: str) -> None:
    r0_config = _settings(3)
    r1_config = _settings(1)
    candidate_config = b""
    store.connection.executemany(
        """
        INSERT INTO deployments(
            revision, code_root, config_root, config_bytes, activated_tick, status
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            (
                "r0",
                source_root,
                _config_root(r0_config),
                r0_config.decode("utf-8"),
                39,
                "available",
            ),
            (
                "r1",
                source_root,
                _config_root(r1_config),
                r1_config.decode("utf-8"),
                40,
                "active",
            ),
            (
                "candidate",
                "",
                _config_root(candidate_config),
                candidate_config.decode("utf-8"),
                0,
                "placeholder",
            ),
        ),
    )
    store.append_audit(
        "deployment_activate", _config_root(r1_config), "controller", 40
    )
    store.connection.commit()


def _seed_shared_telemetry(store: StateStore) -> None:
    for expected_tick, line in zip(range(41, 46), VISIBLE_LOGS, strict=True):
        tick = store.advance()
        if tick != expected_tick:
            raise RuntimeError("incident history did not follow the declared tick schedule")
        store.append_telemetry(tick, "public", line)


def _seed_history(store: StateStore, profile: int) -> None:
    payload_hash = digest("payload-v1", b"settlement:Q-41:100")
    if profile == 0:
        store.connection.execute(
            """
            INSERT INTO journal(
                seq, event_id, command_key, occurrence_id, payload_hash, accepted_tick
            ) VALUES (1, ?, ?, ?, ?, 41)
            """,
            (_EVENT_PRIMARY, _COMMAND_KEY, _OCCURRENCE, payload_hash),
        )
        store.connection.execute(
            """
            INSERT INTO command_keys(command_key, occurrence_id, event_id, state)
            VALUES (?, ?, ?, 'registered')
            """,
            (_COMMAND_KEY, _OCCURRENCE, _EVENT_PRIMARY),
        )
        store.connection.executemany(
            """
            INSERT INTO effects(
                effect_id, occurrence_id, amount, kind, source_event_id, committed_tick
            ) VALUES (?, ?, 100, 'settlement', ?, ?)
            """,
            (
                (_EFFECT_PRIMARY, _OCCURRENCE, _EVENT_PRIMARY, 42),
                (_EFFECT_REPLAY, _OCCURRENCE, _EVENT_PRIMARY, 44),
            ),
        )
        committed_seq = 1
    elif profile == 1:
        store.connection.executemany(
            """
            INSERT INTO journal(
                seq, event_id, command_key, occurrence_id, payload_hash, accepted_tick
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                (1, _EVENT_PRIMARY, _COMMAND_KEY, _OCCURRENCE, payload_hash, 41),
                (2, _EVENT_ADDITIONAL, _COMMAND_KEY, _OCCURRENCE, payload_hash, 43),
            ),
        )
        store.connection.execute(
            """
            INSERT INTO command_keys(command_key, occurrence_id, event_id, state)
            VALUES (?, ?, ?, 'registered')
            """,
            (_COMMAND_KEY, _OCCURRENCE, _EVENT_ADDITIONAL),
        )
        store.connection.executemany(
            """
            INSERT INTO effects(
                effect_id, occurrence_id, amount, kind, source_event_id, committed_tick
            ) VALUES (?, ?, 100, 'settlement', ?, ?)
            """,
            (
                (_EFFECT_PRIMARY, _OCCURRENCE, _EVENT_PRIMARY, 42),
                (_EFFECT_ADDITIONAL, _OCCURRENCE, _EVENT_ADDITIONAL, 44),
            ),
        )
        committed_seq = 2
    else:
        raise ValueError("unsupported fixture profile")
    store.connection.execute(
        "UPDATE cursor SET committed_seq = ? WHERE stream = 'settlement'",
        (committed_seq,),
    )
    _seed_shared_telemetry(store)
    store.connection.commit()


def build_fixture(
    root: Path,
    profile: int,
    authority: RecoveryAuthority,
) -> ServiceFixture:
    root.mkdir(parents=True, exist_ok=False)
    workspace = root / "workspace"
    _copy_workspace(workspace)
    source_root = tree_root(workspace, CODE_FILES)
    active_config = (workspace / CONFIG_FILE).read_bytes()
    if active_config != _settings(1):
        raise RuntimeError("public active configuration does not match r1 artifact")
    store = StateStore(root / "service.sqlite3", authority)
    store.initialize()
    _register_revisions(store, source_root)
    store.create_snapshot("S0")
    _seed_history(store, profile)
    return ServiceFixture(root, workspace, store, source_root)


__all__ = [
    "SCHEMA_TABLES",
    "ServiceFixture",
    "TICKET",
    "VISIBLE_LOGS",
    "build_fixture",
]
