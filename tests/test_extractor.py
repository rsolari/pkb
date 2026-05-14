import httpx

from pkb import extractor as extractor_module
from pkb.config import Settings
from pkb.extractor import Extractor
from pkb.markdown import bookmark_output_path
from pkb.pages import ExtractedPage
from pkb.storage import StateStore, ensure_dirs


def test_thread_network_failure_uses_fallback_and_writes_raw_error(tmp_path):
    settings = Settings(client_id="", client_secret=None, redirect_uri="", data_dir=tmp_path)
    extractor = Extractor(settings)

    class FailingApi:
        def search_conversation(self, conversation_id, username=None):
            request = httpx.Request("GET", "https://api.x.com/2/tweets/search/all")
            raise httpx.ConnectError("network unavailable", request=request)

    post = {
        "id": "123",
        "text": "bookmark",
        "author_id": "u1",
        "created_at": "2025-01-02T03:04:05.000Z",
        "conversation_id": "100",
    }
    payload = {"includes": {"users": [{"id": "u1", "username": "alice"}]}}

    try:
        thread, error = extractor._fetch_thread(FailingApi(), post, payload)
    finally:
        extractor.close()

    assert "ConnectError" in error
    assert thread["pages"][0]["data"] == [post]
    raw = (tmp_path / "raw" / "threads" / "123.json").read_text(encoding="utf-8")
    assert "network unavailable" in raw


def test_refresh_links_preserves_complete_bookmark_thread_state(monkeypatch, tmp_path):
    settings = Settings(client_id="", client_secret=None, redirect_uri="", data_dir=tmp_path)
    ensure_dirs(settings.data_dir)
    post = {
        "id": "123",
        "text": "read this https://example.com/a",
        "author_id": "u1",
        "created_at": "2025-01-02T03:04:05.000Z",
        "conversation_id": "100",
        "entities": {"urls": [{"expanded_url": "https://example.com/a"}]},
    }
    payload = {
        "data": [post],
        "includes": {"users": [{"id": "u1", "username": "alice"}]},
        "meta": {"result_count": 1},
    }
    bookmark_path = bookmark_output_path(settings.markdown_dir, post)
    bookmark_path.parent.mkdir(parents=True, exist_ok=True)
    bookmark_path.write_text("existing complete bookmark\n", encoding="utf-8")
    state = StateStore(settings.state_path)
    try:
        state.mark_bookmark_archived("123", "2026-01-01T00:00:00Z", "complete")
    finally:
        state.close()

    class FakeApi:
        def __init__(self, settings):
            pass

        def me(self):
            return {"data": {"id": "me"}}

        def iter_bookmark_pages(self, user_id, max_pages=None):
            yield 1, payload

        def search_conversation(self, conversation_id, username=None):
            raise AssertionError("--refresh-links should not re-fetch thread state for complete bookmarks")

        def close(self):
            pass

    def fake_fetch_page(url, timeout=20.0):
        return ExtractedPage(
            url=url,
            final_url=url,
            title="Example",
            canonical_url=None,
            content_type="text/html",
            text="linked page",
            status_code=200,
        )

    monkeypatch.setattr(extractor_module, "XApi", FakeApi)
    monkeypatch.setattr(extractor_module, "fetch_page", fake_fetch_page)

    extractor = Extractor(settings)
    try:
        stats = extractor.run(max_pages=1, refresh_links=True)
    finally:
        extractor.close()

    assert stats["skipped_bookmarks"] == 1
    assert stats["threads"] == 0
    assert stats["links"] == 1
    assert bookmark_path.read_text(encoding="utf-8") == "existing complete bookmark\n"
