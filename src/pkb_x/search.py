from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

from .config import Settings
from .index import connect, initialize


DocumentKind = Literal["bookmark", "linked-page"]


@dataclass(frozen=True)
class SearchHit:
    path: str
    kind: str
    score: float
    title: str | None
    author: str | None
    created_at: str | None
    source_url: str | None
    snippet: str


@dataclass(frozen=True)
class BrowseHit:
    path: str
    kind: str
    title: str | None
    author: str | None
    created_at: str | None
    source_url: str | None


def search(
    settings: Settings,
    query: str,
    *,
    kind: DocumentKind | None = None,
    author: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 20,
) -> list[SearchHit]:
    if limit <= 0:
        return []
    conn = connect(settings)
    try:
        initialize(conn)
        rows = conn.execute(
            """
            SELECT
              d.path,
              d.kind,
              d.title,
              d.author,
              d.created_at,
              d.source_url,
              bm25(documents_fts, 5.0, 1.0) AS score,
              snippet(documents_fts, 1, '**', '**', ' ... ', 16) AS snippet
            FROM documents_fts
            JOIN documents d ON d.id = documents_fts.rowid
            WHERE documents_fts MATCH :query
              AND (:kind IS NULL OR d.kind = :kind)
              AND (:author IS NULL OR d.author = :author)
              AND (:since IS NULL OR d.created_at >= :since)
              AND (:until IS NULL OR d.created_at < :until)
            ORDER BY score
            LIMIT :limit
            """,
            {
                "query": query,
                "kind": kind,
                "author": author,
                "since": since,
                "until": until,
                "limit": limit,
            },
        ).fetchall()
        return [_search_hit(row) for row in rows]
    finally:
        conn.close()


def browse(
    settings: Settings,
    *,
    kind: DocumentKind | None = None,
    author: str | None = None,
    since: str | None = None,
    until: str | None = None,
    random: bool = False,
    limit: int = 20,
) -> list[BrowseHit]:
    if limit <= 0:
        return []
    conn = connect(settings)
    try:
        initialize(conn)
        order_by = "RANDOM()" if random else "d.created_at IS NULL, d.created_at DESC, d.indexed_at DESC, d.path ASC"
        rows = conn.execute(
            f"""
            SELECT
              d.path,
              d.kind,
              d.title,
              d.author,
              d.created_at,
              d.source_url
            FROM documents d
            WHERE (:kind IS NULL OR d.kind = :kind)
              AND (:author IS NULL OR d.author = :author)
              AND (:since IS NULL OR d.created_at >= :since)
              AND (:until IS NULL OR d.created_at < :until)
            ORDER BY {order_by}
            LIMIT :limit
            """,
            {
                "kind": kind,
                "author": author,
                "since": since,
                "until": until,
                "limit": limit,
            },
        ).fetchall()
        return [_browse_hit(row) for row in rows]
    finally:
        conn.close()


def _search_hit(row: sqlite3.Row) -> SearchHit:
    return SearchHit(
        path=str(row["path"]),
        kind=str(row["kind"]),
        score=float(row["score"]),
        title=row["title"],
        author=row["author"],
        created_at=row["created_at"],
        source_url=row["source_url"],
        snippet=str(row["snippet"] or ""),
    )


def _browse_hit(row: sqlite3.Row) -> BrowseHit:
    return BrowseHit(
        path=str(row["path"]),
        kind=str(row["kind"]),
        title=row["title"],
        author=row["author"],
        created_at=row["created_at"],
        source_url=row["source_url"],
    )
