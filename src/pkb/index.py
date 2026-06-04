from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .storage import utc_now


KIND_BOOKMARK = "bookmark"
KIND_LINKED_PAGE = "linked-page"
INDEXED_KINDS = (KIND_BOOKMARK, KIND_LINKED_PAGE)


@dataclass
class IndexStats:
    scanned: int = 0
    indexed: int = 0
    skipped: int = 0
    deleted: int = 0


@dataclass(frozen=True)
class ParsedMarkdown:
    frontmatter: dict[str, Any]
    body: str


@dataclass(frozen=True)
class MarkdownDocument:
    kind: str
    path: str
    source_url: str | None
    title: str | None
    author: str | None
    created_at: str | None
    conversation_id: str | None
    links_json: str | None
    body: str
    content_hash: str


def connect(settings: Settings) -> sqlite3.Connection:
    settings.search_index_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.search_index_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def initialize(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
          id              INTEGER PRIMARY KEY,
          kind            TEXT NOT NULL,
          path            TEXT NOT NULL UNIQUE,
          source_url      TEXT,
          title           TEXT,
          author          TEXT,
          created_at      TEXT,
          conversation_id TEXT,
          links_json      TEXT,
          indexed_at      TEXT NOT NULL,
          content_hash    TEXT NOT NULL,
          body            TEXT NOT NULL DEFAULT ''
        )
        """
    )
    _ensure_documents_body_column(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_kind ON documents(kind)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_author ON documents(author)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at)")
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
          title,
          body,
          content='documents',
          content_rowid='id',
          tokenize='porter unicode61 remove_diacritics 2'
        )
        """
    )
    conn.commit()


def reindex(settings: Settings, *, full: bool = False) -> IndexStats:
    stats = IndexStats()
    markdown_dir = settings.markdown_dir
    conn = connect(settings)
    try:
        initialize(conn)
        documents = list(_iter_markdown_documents(markdown_dir))
        seen_paths = {document.path for document in documents}
        now = utc_now()
        with conn:
            for document in documents:
                stats.scanned += 1
                existing = conn.execute(
                    """
                    SELECT
                      id,
                      kind,
                      path,
                      source_url,
                      title,
                      author,
                      created_at,
                      conversation_id,
                      links_json,
                      content_hash,
                      body
                    FROM documents
                    WHERE path = ?
                    """,
                    (document.path,),
                ).fetchone()
                if existing and _document_matches_row(document, existing) and not full:
                    stats.skipped += 1
                    continue
                row_id = _upsert_document(conn, document, indexed_at=now, existing_id=existing["id"] if existing else None)
                _replace_fts_row(conn, row_id, document.title, document.body)
                stats.indexed += 1
            deleted_rows = conn.execute("SELECT id, path FROM documents").fetchall()
            for row in deleted_rows:
                if str(row["path"]) in seen_paths:
                    continue
                conn.execute("DELETE FROM documents_fts WHERE rowid = ?", (row["id"],))
                conn.execute("DELETE FROM documents WHERE id = ?", (row["id"],))
                stats.deleted += 1
        return stats
    finally:
        conn.close()


def parse_markdown(text: str) -> ParsedMarkdown:
    if not text.startswith("---\n"):
        return ParsedMarkdown({}, text)
    lines = text.splitlines(keepends=True)
    end_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        return ParsedMarkdown({}, text)
    frontmatter_lines = [line.rstrip("\n") for line in lines[1:end_index]]
    body = "".join(lines[end_index + 1 :]).lstrip("\n")
    return ParsedMarkdown(_parse_frontmatter_lines(frontmatter_lines), body)


def _ensure_documents_body_column(conn: sqlite3.Connection) -> None:
    columns = set()
    for row in conn.execute("PRAGMA table_info(documents)").fetchall():
        columns.add(str(row["name"] if isinstance(row, sqlite3.Row) else row[1]))
    if "body" not in columns:
        conn.execute("ALTER TABLE documents ADD COLUMN body TEXT NOT NULL DEFAULT ''")


def _iter_markdown_documents(markdown_dir: Path) -> list[MarkdownDocument]:
    documents: list[MarkdownDocument] = []
    for kind, relative_root in (
        (KIND_BOOKMARK, Path("bookmarks")),
        (KIND_LINKED_PAGE, Path("linked-pages")),
    ):
        root = markdown_dir / relative_root
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            if not path.is_file():
                continue
            documents.append(_load_markdown_document(markdown_dir, path, kind))
    return documents


def _load_markdown_document(markdown_dir: Path, path: Path, kind: str) -> MarkdownDocument:
    parsed = parse_markdown(path.read_text(encoding="utf-8"))
    frontmatter = parsed.frontmatter
    relative_path = path.relative_to(markdown_dir).as_posix()
    body = parsed.body
    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    source_url = _optional_str(frontmatter.get("url"))
    if kind == KIND_LINKED_PAGE:
        author = _linked_page_author(frontmatter)
    else:
        author = _optional_str(frontmatter.get("author"))
    links = frontmatter.get("links")
    links_json = json.dumps(links, ensure_ascii=False, sort_keys=True) if isinstance(links, list) else None
    return MarkdownDocument(
        kind=kind,
        path=relative_path,
        source_url=source_url,
        title=_optional_str(frontmatter.get("title")) or _first_heading(body),
        author=author,
        created_at=_optional_str(frontmatter.get("created_at")),
        conversation_id=_optional_str(frontmatter.get("conversation_id")),
        links_json=links_json,
        body=body,
        content_hash=content_hash,
    )


def _upsert_document(
    conn: sqlite3.Connection,
    document: MarkdownDocument,
    *,
    indexed_at: str,
    existing_id: int | None,
) -> int:
    values = (
        document.kind,
        document.path,
        document.source_url,
        document.title,
        document.author,
        document.created_at,
        document.conversation_id,
        document.links_json,
        indexed_at,
        document.content_hash,
        document.body,
    )
    if existing_id is not None:
        conn.execute("DELETE FROM documents_fts WHERE rowid = ?", (existing_id,))
        conn.execute(
            """
            UPDATE documents
            SET kind = ?,
                path = ?,
                source_url = ?,
                title = ?,
                author = ?,
                created_at = ?,
                conversation_id = ?,
                links_json = ?,
                indexed_at = ?,
                content_hash = ?,
                body = ?
            WHERE id = ?
            """,
            (*values, existing_id),
        )
        return int(existing_id)
    cursor = conn.execute(
        """
        INSERT INTO documents (
          kind,
          path,
          source_url,
          title,
          author,
          created_at,
          conversation_id,
          links_json,
          indexed_at,
          content_hash,
          body
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    return int(cursor.lastrowid)


def _document_matches_row(document: MarkdownDocument, row: sqlite3.Row) -> bool:
    return (
        row["kind"] == document.kind
        and row["path"] == document.path
        and row["source_url"] == document.source_url
        and row["title"] == document.title
        and row["author"] == document.author
        and row["created_at"] == document.created_at
        and row["conversation_id"] == document.conversation_id
        and row["links_json"] == document.links_json
        and row["content_hash"] == document.content_hash
        and row["body"] == document.body
    )


def _replace_fts_row(conn: sqlite3.Connection, row_id: int, title: str | None, body: str) -> None:
    conn.execute(
        "INSERT INTO documents_fts(rowid, title, body) VALUES (?, ?, ?)",
        (row_id, title or "", body),
    )


def _parse_frontmatter_lines(lines: list[str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    current_list_key: str | None = None
    for line in lines:
        if not line.strip():
            continue
        stripped = line.strip()
        if current_list_key and stripped.startswith("- "):
            current = values.setdefault(current_list_key, [])
            if isinstance(current, list):
                current.append(_parse_scalar(stripped[2:].strip()))
            continue
        current_list_key = None
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        if not key:
            continue
        raw_value = raw_value.strip()
        if raw_value:
            values[key] = _parse_scalar(raw_value)
        else:
            values[key] = []
            current_list_key = key
    return values


def _parse_scalar(raw_value: str) -> Any:
    if raw_value == "null":
        return None
    if len(raw_value) >= 2 and raw_value[0] == '"' and raw_value[-1] == '"':
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError:
            return raw_value[1:-1]
    if len(raw_value) >= 2 and raw_value[0] == "'" and raw_value[-1] == "'":
        return raw_value[1:-1]
    return raw_value


def _first_heading(body: str) -> str | None:
    for line in body.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            return title or None
    return None


def _linked_page_author(frontmatter: dict[str, Any]) -> str | None:
    url = _optional_str(frontmatter.get("final_url")) or _optional_str(frontmatter.get("url"))
    if not url or "://" not in url:
        return None
    host = url.split("://", 1)[1].split("/", 1)[0].lower()
    return host or None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
