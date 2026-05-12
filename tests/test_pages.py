import socket

import httpx

from pkb_x.pages import extract_main_text, extract_urls_from_post, fetch_page, is_external_url, is_public_destination


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


def test_private_destinations_are_not_public(monkeypatch):
    def fake_getaddrinfo(host, port, type=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    assert not is_public_destination("http://127.0.0.1/admin")
    assert not is_public_destination("http://169.254.169.254/latest/meta-data")
    assert not is_public_destination("https://example.com/private-after-dns")


def test_fetch_page_blocks_redirect_to_private_destination(monkeypatch):
    def fake_getaddrinfo(host, port, type=0):
        if host == "example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
        if host == "127.0.0.1":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]
        raise socket.gaierror

    def handler(request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1:8000/secrets"}, request=request)

    transport = httpx.MockTransport(handler)
    original_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(httpx, "Client", client_factory)

    page = fetch_page("https://example.com/redirect")

    assert page.final_url == "http://127.0.0.1:8000/secrets"
    assert page.error == "Blocked non-public destination"


def test_fetch_page_caps_response_size(monkeypatch):
    def fake_getaddrinfo(host, port, type=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    def handler(request):
        html = "<html><body><main><p>" + ("a" * 200) + "</p></main></body></html>"
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html, request=request)

    transport = httpx.MockTransport(handler)
    original_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(httpx, "Client", client_factory)

    page = fetch_page("https://example.com/large", max_bytes=64)

    assert page.error == "Response exceeded 64 bytes"
    assert page.raw_html is not None
    assert len(page.raw_html.encode("utf-8")) <= 64
