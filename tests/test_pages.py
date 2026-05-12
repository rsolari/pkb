import httpx

from pkb_x.pages import extract_main_text, extract_urls_from_post, fetch_page, is_external_url


def test_url_filtering_skips_x_and_tco():
    assert is_external_url("https://example.com/a")
    assert is_external_url("https://max.com/a")
    assert is_external_url("https://box.com/a")
    assert is_external_url("https://linux.com/a")
    assert not is_external_url("https://x.com/user/status/1")
    assert not is_external_url("https://mobile.x.com/user/status/1")
    assert not is_external_url("https://twitter.com/user/status/1")
    assert not is_external_url("https://mobile.twitter.com/user/status/1")
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


def test_fetch_page_preserves_html_error_but_marks_error(monkeypatch):
    def handler(request):
        html = "<html><head><title>Missing</title></head><body><main><p>Not found.</p></main></body></html>"
        return httpx.Response(404, headers={"content-type": "text/html"}, text=html, request=request)

    transport = httpx.MockTransport(handler)
    original_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)

    page = fetch_page("https://example.com/missing")

    assert page.status_code == 404
    assert page.error == "HTTP 404"
    assert page.title == "Missing"
    assert "Not found." in page.text
