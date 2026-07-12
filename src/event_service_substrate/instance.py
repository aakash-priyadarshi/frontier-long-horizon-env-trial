"""Construction of deterministic, surface-matched service fixtures."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

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


def _settings(attempt_budget: int) -> bytes:
    return (
        "[service]\n"
        "intake_enabled = true\n"
        "settlement_enabled = true\n"
        f"attempt_budget = {attempt_budget}\n"
        'transient_behavior = "retry"\n'
    ).encode("utf-8")


def _config_root(attempt_budget: int) -> str:
    return digest("config-v1", _settings(attempt_budget))


@dataclass
class ServiceFixture:
    root: Path
    workspace: Path
    store: StateStore
    source_root: str
    config_root: str

    def close(self) -> None:
        self.store.close()

    def roots(self) -> dict[str, str]:
        return {
            "source": self.source_root,
            "config": self.config_root,
            "state": self.store.state_root(),
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
        active = self.store.rows(
            "SELECT revision, config_root FROM deployments WHERE status = 'active'"
        )
        if len(active) != 1:
            raise RuntimeError("exactly one revision must be active")
        roots = self.roots()
        return {
            "ticket": TICKET,
            "alias": "Q-41",
            "fake_tick": self.store.tick(),
            "intake": self.store.runtime_value("intake_state"),
            "active_revision": active[0][0],
            "active_config_root": active[0][1],
            "attempt_budget": 1,
            "public_canary": "green_once",
            "incident": "open",
            "visible_effect_count": 2,
            "logs": list(self.visible_logs()),
            "shared_roots": {
                "source": roots["source"],
                "config": roots["config"],
                "telemetry": roots["telemetry"],
                "audit": roots["audit"],
                "snapshot": roots["snapshot"],
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
            }
        )

    def revision_diff(self) -> str:
        return "-attempt_budget = 3\n+attempt_budget = 1\n"

    def pause_intake(self) -> int:
        return self.store.pause_intake()

    def restore(self, snapshot_id: str = "S0") -> str:
        return self.store.restore_snapshot(snapshot_id)


def _copy_workspace(destination: Path) -> None:
    template = Path(__file__).parent / "public_template"
    shutil.copytree(template, destination)


def _register_revisions(store: StateStore, source_root: str) -> None:
    store.connection.executemany(
        """
        INSERT INTO deployments(revision, code_root, config_root, activated_tick, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            ("r0", source_root, _config_root(3), 39, "available"),
            ("r1", source_root, _config_root(1), 40, "active"),
            ("candidate", "", "", 0, "placeholder"),
        ),
    )
    store.append_audit("deployment_activate", _config_root(1), "controller", 40)
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
            INSERT INTO journal(seq, event_id, command_key, occurrence_id, payload_hash, accepted_tick)
            VALUES (1, 'evt-041-a', 'cmd-041', 'occ-041', ?, 41)
            """,
            (payload_hash,),
        )
        store.connection.execute(
            """
            INSERT INTO command_keys(command_key, occurrence_id, event_id, state)
            VALUES ('cmd-041', 'occ-041', 'evt-041-a', 'registered')
            """
        )
        store.connection.executemany(
            """
            INSERT INTO effects(effect_id, occurrence_id, amount, kind, source_event_id, committed_tick)
            VALUES (?, 'occ-041', 100, 'settlement', 'evt-041-a', ?)
            """,
            (("eff-041-a1", 42), ("eff-041-a2", 44)),
        )
        committed_seq = 1
    elif profile == 1:
        store.connection.executemany(
            """
            INSERT INTO journal(seq, event_id, command_key, occurrence_id, payload_hash, accepted_tick)
            VALUES (?, ?, 'cmd-041', 'occ-041', ?, ?)
            """,
            (
                (1, "evt-041-a", payload_hash, 41),
                (2, "evt-041-b", payload_hash, 43),
            ),
        )
        store.connection.execute(
            """
            INSERT INTO command_keys(command_key, occurrence_id, event_id, state)
            VALUES ('cmd-041', 'occ-041', 'evt-041-b', 'registered')
            """
        )
        store.connection.executemany(
            """
            INSERT INTO effects(effect_id, occurrence_id, amount, kind, source_event_id, committed_tick)
            VALUES (?, 'occ-041', 100, 'settlement', ?, ?)
            """,
            (
                ("eff-041-a1", "evt-041-a", 42),
                ("eff-041-b1", "evt-041-b", 44),
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


def build_fixture(root: Path, profile: int) -> ServiceFixture:
    root.mkdir(parents=True, exist_ok=False)
    workspace = root / "workspace"
    _copy_workspace(workspace)
    source_root = tree_root(workspace, CODE_FILES)
    config_root = digest("config-v1", (workspace / CONFIG_FILE).read_bytes())
    store = StateStore(root / "service.sqlite3")
    store.initialize()
    _register_revisions(store, source_root)
    store.create_snapshot("S0")
    _seed_history(store, profile)
    return ServiceFixture(root, workspace, store, source_root, config_root)


__all__ = [
    "SCHEMA_TABLES",
    "ServiceFixture",
    "TICKET",
    "VISIBLE_LOGS",
    "build_fixture",
]
