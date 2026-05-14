from pkb.markdown import render_bookmark_markdown


def test_render_bookmark_markdown_uses_note_tweet_and_frontmatter():
    post = {
        "id": "123",
        "text": "truncated",
        "note_tweet": {"text": "full note text"},
        "author_id": "u1",
        "created_at": "2025-01-02T03:04:05.000Z",
        "conversation_id": "100",
    }
    payload = {"includes": {"users": [{"id": "u1", "username": "alice", "name": "Alice"}]}}
    thread = {"pages": [{"data": [post], "includes": payload["includes"], "meta": {"result_count": 1}}]}

    rendered = render_bookmark_markdown(post, payload, thread, [])

    assert 'id: "123"' in rendered
    assert 'author: "@alice"' in rendered
    assert "full note text" in rendered
    assert "https://x.com/alice/status/123" in rendered


def test_fallback_markdown_includes_referenced_tweets_from_expansions():
    post = {
        "id": "123",
        "text": "replying to this",
        "author_id": "u1",
        "created_at": "2025-01-02T03:04:05.000Z",
        "conversation_id": "100",
        "referenced_tweets": [{"type": "replied_to", "id": "99"}],
    }
    referenced = {
        "id": "99",
        "text": "context from referenced post",
        "author_id": "u2",
        "created_at": "2025-01-02T02:00:00.000Z",
        "conversation_id": "100",
    }
    includes = {
        "tweets": [referenced],
        "users": [
            {"id": "u1", "username": "alice", "name": "Alice"},
            {"id": "u2", "username": "bob", "name": "Bob"},
        ],
    }
    payload = {"includes": includes}
    thread = {"pages": [{"data": [post], "includes": includes, "meta": {"result_count": 1}}]}

    rendered = render_bookmark_markdown(post, payload, thread, [], thread_error="timeout")

    assert 'extraction_status: "partial"' in rendered
    assert "context from referenced post" in rendered
    assert "https://x.com/bob/status/99" in rendered
