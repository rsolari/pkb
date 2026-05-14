from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
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


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class StateStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
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
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bookmarks (
              post_id TEXT PRIMARY KEY,
              first_seen_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL,
              last_archived_at TEXT,
              missing_since TEXT,
              status TEXT NOT NULL,
              detail TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS links (
              url TEXT PRIMARY KEY,
              first_seen_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL,
              last_fetched_at TEXT,
              status TEXT NOT NULL,
              detail TEXT
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

    def mark_bookmark_seen(self, post_id: str, seen_at: str) -> None:
        status = self.status(post_id) or "seen"
        self.conn.execute(
            """
            INSERT INTO bookmarks (post_id, first_seen_at, last_seen_at, status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(post_id) DO UPDATE SET
              last_seen_at = excluded.last_seen_at,
              missing_since = NULL
            """,
            (post_id, seen_at, seen_at, status),
        )
        self.conn.commit()

    def bookmark_status(self, post_id: str) -> str | None:
        row = self.conn.execute("SELECT status FROM bookmarks WHERE post_id = ?", (post_id,)).fetchone()
        if row:
            return str(row["status"])
        return self.status(post_id)

    def should_skip_bookmark(self, post_id: str, markdown_exists: bool, refresh: bool) -> bool:
        if refresh or not markdown_exists:
            return False
        return self.bookmark_status(post_id) == "complete"

    def mark_bookmark_archived(self, post_id: str, archived_at: str, status: str, detail: str | None = None) -> None:
        self.conn.execute(
            """
            INSERT INTO bookmarks (post_id, first_seen_at, last_seen_at, last_archived_at, status, detail)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(post_id) DO UPDATE SET
              last_seen_at = excluded.last_seen_at,
              last_archived_at = excluded.last_archived_at,
              missing_since = NULL,
              status = excluded.status,
              detail = excluded.detail
            """,
            (post_id, archived_at, archived_at, archived_at, status, detail),
        )
        self.mark(post_id, "bookmark", status, detail)

    def mark_bookmarks_missing(self, seen_post_ids: set[str], missing_at: str) -> int:
        rows = self.conn.execute("SELECT post_id FROM bookmarks WHERE missing_since IS NULL").fetchall()
        missing = [str(row["post_id"]) for row in rows if str(row["post_id"]) not in seen_post_ids]
        self.conn.executemany(
            """
            UPDATE bookmarks
            SET missing_since = ?, status = 'missing'
            WHERE post_id = ? AND missing_since IS NULL
            """,
            [(missing_at, post_id) for post_id in missing],
        )
        self.conn.commit()
        return len(missing)

    def mark_link_seen(self, url: str, seen_at: str) -> None:
        status = self.status(url) or "seen"
        self.conn.execute(
            """
            INSERT INTO links (url, first_seen_at, last_seen_at, status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
              last_seen_at = excluded.last_seen_at
            """,
            (url, seen_at, seen_at, status),
        )
        self.conn.commit()

    def link_status(self, url: str) -> str | None:
        row = self.conn.execute("SELECT status FROM links WHERE url = ?", (url,)).fetchone()
        if row:
            return str(row["status"])
        return self.status(url)

    def should_skip_link(self, url: str, metadata_exists: bool, refresh: bool) -> bool:
        if refresh or not metadata_exists:
            return False
        return self.link_status(url) == "complete"

    def mark_link_fetched(self, url: str, fetched_at: str, status: str, detail: str | None = None) -> None:
        self.conn.execute(
            """
            INSERT INTO links (url, first_seen_at, last_seen_at, last_fetched_at, status, detail)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
              last_seen_at = excluded.last_seen_at,
              last_fetched_at = excluded.last_fetched_at,
              status = excluded.status,
              detail = excluded.detail
            """,
            (url, fetched_at, fetched_at, fetched_at, status, detail),
        )
        self.mark(url, "link", status, detail)
