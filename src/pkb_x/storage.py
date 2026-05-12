from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


def ensure_dirs(data_dir: Path) -> None:
    for relative in (
        ".secrets",
        ".state",
        "raw/bookmarks",
        "raw/threads",
        "raw/linked-pages",
        "markdown/bookmarks",
        "markdown/linked-pages",
    ):
        (data_dir / relative).mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_slug(value: str, suffix_len: int = 12) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:suffix_len]
    cleaned = []
    for char in value.lower():
        if char.isalnum():
            cleaned.append(char)
        elif char in {" ", "-", "_", "/", ".", ":"}:
            cleaned.append("-")
    slug = "-".join("".join(cleaned).split("-"))
    slug = slug[:72].strip("-")
    return f"{slug}-{digest}" if slug else digest


class StateStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
              key TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              status TEXT NOT NULL,
              detail TEXT,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def mark(self, key: str, kind: str, status: str, detail: str | None = None) -> None:
        self.conn.execute(
            """
            INSERT INTO items (key, kind, status, detail, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
              kind = excluded.kind,
              status = excluded.status,
              detail = excluded.detail,
              updated_at = CURRENT_TIMESTAMP
            """,
            (key, kind, status, detail),
        )
        self.conn.commit()

    def status(self, key: str) -> str | None:
        row = self.conn.execute("SELECT status FROM items WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

