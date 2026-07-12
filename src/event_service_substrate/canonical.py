"""Canonical serialization and hashing helpers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def digest(domain: str, payload: bytes) -> str:
    framed = domain.encode("utf-8") + b"\x00" + payload
    return hashlib.sha256(framed).hexdigest()


def tree_root(root: Path, relative_paths: Iterable[Path]) -> str:
    entries = []
    for relative_path in sorted(relative_paths, key=lambda item: item.as_posix()):
        data = (root / relative_path).read_bytes()
        entries.append(
            {
                "path": relative_path.as_posix(),
                "size": len(data),
                "digest": digest("file-v1", data),
            }
        )
    return digest("tree-v1", canonical_json(entries))


def table_document(
    connection: sqlite3.Connection,
    table_names: Sequence[str],
) -> list[dict[str, Any]]:
    document: list[dict[str, Any]] = []
    for table_name in table_names:
        columns = [
            row[1]
            for row in connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        ]
        order = ", ".join(f'"{column}"' for column in columns)
        rows = connection.execute(
            f'SELECT {order} FROM "{table_name}" ORDER BY {order}'
        ).fetchall()
        document.append(
            {
                "table": table_name,
                "columns": columns,
                "rows": [list(row) for row in rows],
            }
        )
    return document


def table_root(
    connection: sqlite3.Connection,
    table_names: Sequence[str],
    domain: str,
) -> str:
    return digest(domain, canonical_json(table_document(connection, table_names)))

