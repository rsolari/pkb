import hashlib
import json
import sqlite3

from pkb import cli
from pkb.config import Settings
from pkb.index import IndexStats, initialize, parse_markdown, reindex
from pkb.search import browse, search


def test_initialize_creates_schema_and_migrates_body_column(tmp_path):
    db_path = tmp_path / "search.sqlite"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            CREATE TABLE documents (
              id INTEGER PRIMARY KEY,
              kind TEXT NOT NULL,
              path TEXT NOT NULL UNIQUE,
              source_url TEXT,
              title TEXT,
              author TEXT,
              created_at TEXT,
              conversation_id TEXT,
              links_json TEXT,
              indexed_at TEXT NOT NULL,
              content_hash TEXT NOT NULL
            )
            """
        )

        initialize(conn)

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
        assert "body" in columns
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'documents_fts'").fetchone()
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'idx_documents_kind'").fetchone()
    finally:
        conn.close()


def test_parse_markdown_frontmatter_all_fields_missing_and_malformed():
    parsed = parse_markdown(
        """---
id: "123"
url: "https://x.com/alice/status/123"
author: "@alice"
created_at: "2025-01-02T03:04:05.000Z"
conversation_id: "100"
thread_error: null
links:
  - "https://example.com/a"
  - "https://example.com/b"
---

# Body

Only this body should be indexed.
"""
    )

    assert parsed.frontmatter["id"] == "123"
    assert parsed.frontmatter["thread_error"] is None
    assert parsed.frontmatter["links"] == ["https://example.com/a", "https://example.com/b"]
    assert parsed.body.startswith("# Body")

    no_frontmatter = parse_markdown("# Plain\n\nText")
    assert no_frontmatter.frontmatter == {}
    assert no_frontmatter.body == "# Plain\n\nText"

    malformed = parse_markdown("---\nauthor: \"@alice\"\n# no closing marker\n")
    assert malformed.frontmatter == {}
    assert malformed.body.startswith("---")


def test_reindex_indexes_bookmark_and_linked_page_rows(tmp_path):
    settings = _settings(tmp_path)
    bookmark = _write_bookmark(
        settings,
        "2025-01-02",
        "123",
        author="@alice",
        body="# X bookmark 123 by @alice\n\nLanding pages need searchable SEO tactics.\n",
    )
    linked_page = _write_linked_page(
        settings,
        "example.com",
        "article",
        url="https://example.com/article",
        title="Example Article",
        body="# Example Article\n\nPython sqlite indexing notes.\n",
    )

    stats = reindex(settings)

    assert stats.scanned == 2
    assert stats.indexed == 2
    assert stats.skipped == 0
    conn = sqlite3.connect(settings.search_index_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM documents ORDER BY kind").fetchall()
        bookmark_row = next(row for row in rows if row["kind"] == "bookmark")
        linked_row = next(row for row in rows if row["kind"] == "linked-page")
        assert bookmark_row["path"] == "bookmarks/2025-01-02/123.md"
        assert bookmark_row["source_url"] == "https://x.com/alice/status/123"
        assert bookmark_row["author"] == "@alice"
        assert bookmark_row["conversation_id"] == "100"
        assert json.loads(bookmark_row["links_json"]) == ["https://example.com/article"]
        assert bookmark_row["content_hash"] == hashlib.sha256(parse_markdown(bookmark.read_text()).body.encode()).hexdigest()
        assert linked_row["path"] == "linked-pages/example.com/article.md"
        assert linked_row["source_url"] == "https://example.com/article"
        assert linked_row["title"] == "Example Article"
        assert linked_row["author"] == "example.com"
        assert conn.execute("SELECT rowid FROM documents_fts WHERE documents_fts MATCH 'seo'").fetchone()
        assert conn.execute("SELECT rowid FROM documents_fts WHERE documents_fts MATCH 'conversation_id'").fetchone() is None
        assert conn.execute("SELECT rowid FROM documents_fts WHERE documents_fts MATCH 'sqlite'").fetchone()
    finally:
        conn.close()
    assert linked_page.exists()


def test_reindex_skips_unchanged_full_reindexes_and_removes_deleted_files(tmp_path):
    settings = _settings(tmp_path)
    bookmark = _write_bookmark(
        settings,
        "2025-01-02",
        "123",
        author="@alice",
        body="# X bookmark 123 by @alice\n\nIncremental search body.\n",
    )

    assert reindex(settings).indexed == 1
    skipped = reindex(settings)
    assert skipped.scanned == 1
    assert skipped.indexed == 0
    assert skipped.skipped == 1

    _write_bookmark(
        settings,
        "2025-01-02",
        "123",
        author="@bob",
        body="# X bookmark 123 by @alice\n\nIncremental search body.\n",
    )
    metadata_changed = reindex(settings)
    assert metadata_changed.scanned == 1
    assert metadata_changed.indexed == 1
    assert metadata_changed.skipped == 0
    assert [hit.path for hit in browse(settings, author="@bob")] == ["bookmarks/2025-01-02/123.md"]
    assert browse(settings, author="@alice") == []

    full = reindex(settings, full=True)
    assert full.indexed == 1
    assert full.skipped == 0

    bookmark.unlink()
    deleted = reindex(settings)
    assert deleted.scanned == 0
    assert deleted.deleted == 1
    assert search(settings, "incremental") == []


def test_search_returns_snippets_and_applies_filters(tmp_path):
    settings = _settings(tmp_path)
    _write_bookmark(
        settings,
        "2025-01-02",
        "123",
        author="@alice",
        body="# X bookmark 123 by @alice\n\nGrowth loops need durable landing page copy.\n",
    )
    _write_bookmark(
        settings,
        "2025-02-02",
        "456",
        author="@bob",
        body="# X bookmark 456 by @bob\n\nGrowth loops also need onboarding analytics.\n",
    )
    _write_linked_page(
        settings,
        "example.com",
        "python",
        url="https://example.com/python",
        title="Python Notes",
        body="# Python Notes\n\nSqlite search examples for linked pages.\n",
    )
    reindex(settings)

    hits = search(settings, "growth")
    assert {hit.path for hit in hits} == {"bookmarks/2025-01-02/123.md", "bookmarks/2025-02-02/456.md"}
    assert all(isinstance(hit.score, float) for hit in hits)
    assert "**Growth**" in hits[0].snippet

    assert [hit.author for hit in search(settings, "growth", author="@alice")] == ["@alice"]
    assert [hit.path for hit in search(settings, "growth", since="2025-02-01")] == ["bookmarks/2025-02-02/456.md"]
    assert [hit.path for hit in search(settings, "growth", until="2025-02-01")] == ["bookmarks/2025-01-02/123.md"]
    assert [hit.kind for hit in search(settings, "sqlite", kind="linked-page")] == ["linked-page"]
    assert search(settings, "sqlite", kind="bookmark") == []


def test_cli_search_json_output_has_stable_keys(monkeypatch, capsys, tmp_path):
    settings = _settings(tmp_path)
    _write_bookmark(
        settings,
        "2025-01-02",
        "123",
        author="@alice",
        body="# X bookmark 123 by @alice\n\nJson output should include growth.\n",
    )
    reindex(settings)
    monkeypatch.setenv("PKB_DATA_DIR", str(tmp_path))

    exit_code = cli.main(["search", "growth", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert list(payload[0]) == ["path", "kind", "score", "title", "author", "created_at", "source_url", "snippet"]
    assert payload[0]["path"] == "bookmarks/2025-01-02/123.md"
    assert payload[0]["author"] == "@alice"


def test_browse_orders_by_newest_and_random_returns_limited_results(tmp_path):
    settings = _settings(tmp_path)
    _write_bookmark(settings, "2025-01-02", "123", author="@alice", body="# Older\n\nDiscovery one.\n")
    _write_bookmark(settings, "2025-03-02", "456", author="@bob", body="# Newer\n\nDiscovery two.\n")
    _write_bookmark(settings, "2025-02-02", "789", author="@alice", body="# Middle\n\nDiscovery three.\n")
    reindex(settings)

    ordered = browse(settings, limit=3)
    assert [hit.path for hit in ordered] == [
        "bookmarks/2025-03-02/456.md",
        "bookmarks/2025-02-02/789.md",
        "bookmarks/2025-01-02/123.md",
    ]
    assert [hit.path for hit in browse(settings, author="@alice", limit=5)] == [
        "bookmarks/2025-02-02/789.md",
        "bookmarks/2025-01-02/123.md",
    ]
    random_hits = browse(settings, random=True, limit=2)
    assert len(random_hits) == 2
    assert {hit.path for hit in random_hits} <= {hit.path for hit in ordered}


def test_cli_browse_json_output(monkeypatch, capsys, tmp_path):
    settings = _settings(tmp_path)
    _write_bookmark(settings, "2025-01-02", "123", author="@alice", body="# Browse\n\nBrowse json body.\n")
    reindex(settings)
    monkeypatch.setenv("PKB_DATA_DIR", str(tmp_path))

    exit_code = cli.main(["browse", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert list(payload[0]) == ["path", "kind", "title", "author", "created_at", "source_url"]
    assert payload[0]["kind"] == "bookmark"


def test_extract_command_reindexes_after_extraction(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    calls = []

    class FakeExtractor:
        def __init__(self, loaded_settings):
            assert loaded_settings == settings

        def run(self, **kwargs):
            calls.append(("run", kwargs))
            return {
                "bookmark_pages": 0,
                "bookmarks": 0,
                "skipped_bookmarks": 0,
                "missing_bookmarks": 0,
                "threads": 0,
                "links": 0,
                "skipped_links": 0,
                "errors": 0,
            }

        def close(self):
            calls.append(("close", None))

    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "Extractor", FakeExtractor)
    monkeypatch.setattr(cli, "reindex", lambda loaded_settings: _fake_index_stats(calls, loaded_settings, settings))

    exit_code = cli.cmd_extract(
        cli.argparse.Namespace(max_pages=None, no_links=False, refresh=False, refresh_links=False)
    )

    assert exit_code == 0
    assert calls == [
        ("run", {"max_pages": None, "fetch_links": True, "refresh": False, "refresh_links": False}),
        ("close", None),
        ("reindex", False),
    ]


def _settings(tmp_path):
    return Settings(client_id="", client_secret=None, redirect_uri="", data_dir=tmp_path)


def _write_bookmark(settings, date, post_id, *, author, body):
    path = settings.markdown_dir / "bookmarks" / date / f"{post_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
id: "{post_id}"
url: "https://x.com/{author.lstrip('@')}/status/{post_id}"
author: "{author}"
created_at: "{date}T03:04:05.000Z"
conversation_id: "100"
links:
  - "https://example.com/article"
---

{body}""",
        encoding="utf-8",
    )
    return path


def _write_linked_page(settings, host, slug, *, url, title, body):
    path = settings.markdown_dir / "linked-pages" / host / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
url: "{url}"
final_url: "{url}"
canonical_url: null
title: "{title}"
content_type: "text/html"
status_code: "200"
error: null
---

{body}""",
        encoding="utf-8",
    )
    return path


def _fake_index_stats(calls, loaded_settings, expected_settings):
    assert loaded_settings == expected_settings
    calls.append(("reindex", False))
    return IndexStats()
