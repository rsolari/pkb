from pkb_x.pages import extract_main_text, extract_urls_from_post, is_external_url


def test_url_filtering_skips_x_and_tco():
    assert is_external_url("https://example.com/a")
    assert not is_external_url("https://x.com/user/status/1")
    assert not is_external_url("https://twitter.com/user/status/1")
    assert not is_external_url("https://t.co/abc")


def test_extract_urls_from_post_dedupes_external_links():
    post = {
        "entities": {
            "urls": [
                {"expanded_url": "https://example.com/a"},
                {"expanded_url": "https://example.com/a"},
                {"expanded_url": "https://x.com/user/status/1"},
            ]
        }
    }
    assert extract_urls_from_post(post) == ["https://example.com/a"]


def test_extract_main_text_prefers_article():
    html = """
    <html>
      <head><title>Example</title><link rel="canonical" href="https://example.com/post"></head>
      <body>
        <nav>ignore</nav>
        <article><h1>Hello</h1><p>First paragraph.</p><p>Second paragraph.</p></article>
      </body>
    </html>
    """
    title, canonical, text = extract_main_text(html)
    assert title == "Example"
    assert canonical == "https://example.com/post"
    assert "# Hello" in text
    assert "First paragraph." in text

