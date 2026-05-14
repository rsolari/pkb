from pkb.storage import StateStore


def test_bookmark_skip_requires_complete_status_existing_file_and_no_refresh(tmp_path):
    state = StateStore(tmp_path / "state.sqlite")
    try:
        state.mark_bookmark_seen("123", "2026-01-01T00:00:00Z")
        assert not state.should_skip_bookmark("123", markdown_exists=True, refresh=False)

        state.mark_bookmark_archived("123", "2026-01-01T00:01:00Z", "complete")
        assert state.should_skip_bookmark("123", markdown_exists=True, refresh=False)
        assert not state.should_skip_bookmark("123", markdown_exists=False, refresh=False)
        assert not state.should_skip_bookmark("123", markdown_exists=True, refresh=True)
    finally:
        state.close()


def test_full_run_can_mark_unseen_bookmarks_missing(tmp_path):
    state = StateStore(tmp_path / "state.sqlite")
    try:
        state.mark_bookmark_archived("old", "2026-01-01T00:00:00Z", "complete")
        state.mark_bookmark_archived("current", "2026-01-01T00:00:00Z", "complete")

        missing = state.mark_bookmarks_missing({"current"}, "2026-01-02T00:00:00Z")

        assert missing == 1
        assert state.bookmark_status("old") == "missing"
        assert state.bookmark_status("current") == "complete"
    finally:
        state.close()


def test_link_skip_requires_complete_status_existing_metadata_and_no_refresh(tmp_path):
    state = StateStore(tmp_path / "state.sqlite")
    try:
        url = "https://example.com/post"
        state.mark_link_seen(url, "2026-01-01T00:00:00Z")
        assert not state.should_skip_link(url, metadata_exists=True, refresh=False)

        state.mark_link_fetched(url, "2026-01-01T00:01:00Z", "complete")
        assert state.should_skip_link(url, metadata_exists=True, refresh=False)
        assert not state.should_skip_link(url, metadata_exists=False, refresh=False)
        assert not state.should_skip_link(url, metadata_exists=True, refresh=True)
    finally:
        state.close()


def test_seen_rows_preserve_legacy_complete_status(tmp_path):
    state = StateStore(tmp_path / "state.sqlite")
    try:
        state.mark("legacy-post", "bookmark", "complete")
        state.mark_bookmark_seen("legacy-post", "2026-01-01T00:00:00Z")
        assert state.should_skip_bookmark("legacy-post", markdown_exists=True, refresh=False)

        url = "https://example.com/legacy"
        state.mark(url, "link", "complete")
        state.mark_link_seen(url, "2026-01-01T00:00:00Z")
        assert state.should_skip_link(url, metadata_exists=True, refresh=False)
    finally:
        state.close()
