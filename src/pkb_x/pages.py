from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup, Tag

from .storage import stable_slug


MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5


@dataclass(frozen=True)
class ExtractedPage:
    url: str
    final_url: str
    title: str | None
    canonical_url: str | None
    content_type: str | None
    text: str
    status_code: int
    raw_html: str | None = None
    error: str | None = None

    @property
    def slug(self) -> str:
        return stable_slug(self.canonical_url or self.final_url or self.url)


def is_external_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    x_hosts = ("x.com", "twitter.com", "t.co")
    return not any(host == domain or host.endswith(f".{domain}") for domain in x_hosts)


def is_public_destination(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.hostname
    if not host:
        return False
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except socket.gaierror:
            return False
        addresses = []
        for info in infos:
            address = info[4][0]
            try:
                addresses.append(ipaddress.ip_address(address))
            except ValueError:
                return False
    return bool(addresses) and all(_is_public_address(address) for address in addresses)


def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def extract_urls_from_post(post: dict) -> list[str]:
    urls: list[str] = []
    containers = [post.get("entities") or {}]
    note = post.get("note_tweet") or {}
    if isinstance(note, dict):
        containers.append(note.get("entities") or {})
    for container in containers:
        for item in container.get("urls", []) or []:
            expanded = item.get("expanded_url") or item.get("unwound_url") or item.get("url")
            if expanded and is_external_url(expanded):
                urls.append(expanded)
    return list(dict.fromkeys(urls))


def _clean_soup(soup: BeautifulSoup) -> None:
    for selector in ("script", "style", "noscript", "svg", "canvas", "iframe", "form", "nav", "header", "footer", "aside"):
        for tag in soup.select(selector):
            tag.decompose()


def _tag_text(tag: Tag) -> str:
    pieces: list[str] = []
    for element in tag.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre", "blockquote"], recursive=True):
        text = element.get_text(" ", strip=True)
        if not text:
            continue
        if element.name in {"h1", "h2", "h3", "h4"}:
            level = {"h1": "#", "h2": "##", "h3": "###", "h4": "####"}[element.name]
            pieces.append(f"{level} {text}")
        elif element.name == "li":
            pieces.append(f"- {text}")
        elif element.name == "blockquote":
            pieces.append(f"> {text}")
        else:
            pieces.append(text)
    text = "\n\n".join(dict.fromkeys(pieces))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_main_text(html: str) -> tuple[str | None, str | None, str]:
    soup = BeautifulSoup(html, "html.parser")
    _clean_soup(soup)
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in value)
    canonical = canonical_tag.get("href") if isinstance(canonical_tag, Tag) else None
    candidates = [tag for tag in (soup.find("article"), soup.find("main"), soup.body) if isinstance(tag, Tag)]
    best = ""
    for candidate in candidates:
        text = _tag_text(candidate)
        if len(text) > len(best):
            best = text
    if not best and soup.body:
        best = soup.body.get_text("\n", strip=True)
    return title, canonical, best.strip()


def _decode_response_body(response: httpx.Response, body: bytes) -> str:
    encoding = response.encoding or "utf-8"
    return body.decode(encoding, errors="replace")


def _read_limited_response(response: httpx.Response, max_bytes: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    truncated = False
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > max_bytes:
            remaining = max_bytes - (total - len(chunk))
            if remaining > 0:
                chunks.append(chunk[:remaining])
            truncated = True
            response.close()
            break
        chunks.append(chunk)
    return b"".join(chunks), truncated


def fetch_page(url: str, timeout: float = 20.0, max_bytes: int = MAX_RESPONSE_BYTES) -> ExtractedPage:
    headers = {
        "User-Agent": "pkb-x/0.1 (+local personal archive)",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
    }
    current_url = url
    status_code = 0
    content_type = None
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, headers=headers) as client:
            for _ in range(MAX_REDIRECTS + 1):
                if not is_public_destination(current_url):
                    return ExtractedPage(
                        url=url,
                        final_url=current_url,
                        title=None,
                        canonical_url=None,
                        content_type=content_type,
                        text="",
                        status_code=status_code,
                        error="Blocked non-public destination",
                    )
                with client.stream("GET", current_url) as response:
                    status_code = response.status_code
                    content_type = response.headers.get("content-type")
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            return ExtractedPage(
                                url=url,
                                final_url=str(response.url),
                                title=None,
                                canonical_url=None,
                                content_type=content_type,
                                text="",
                                status_code=response.status_code,
                                error="Redirect response missing Location header",
                            )
                        current_url = str(response.url.join(location))
                        continue
                    if content_type and "html" not in content_type and "text/plain" not in content_type:
                        return ExtractedPage(
                            url=url,
                            final_url=str(response.url),
                            title=None,
                            canonical_url=None,
                            content_type=content_type,
                            text="",
                            status_code=response.status_code,
                            error=f"Unsupported content type: {content_type}",
                        )
                    body_bytes, truncated = _read_limited_response(response, max_bytes)
                    body = _decode_response_body(response, body_bytes)
                    title, canonical, text = extract_main_text(body)
                    errors = []
                    if response.is_error:
                        errors.append(f"HTTP {response.status_code}")
                    if truncated:
                        errors.append(f"Response exceeded {max_bytes} bytes")
                    return ExtractedPage(
                        url=url,
                        final_url=str(response.url),
                        title=title,
                        canonical_url=canonical,
                        content_type=content_type,
                        text=text,
                        status_code=response.status_code,
                        raw_html=body,
                        error="; ".join(errors) or None,
                    )
            return ExtractedPage(
                url=url,
                final_url=current_url,
                title=None,
                canonical_url=None,
                content_type=content_type,
                text="",
                status_code=status_code,
                error=f"Too many redirects; max is {MAX_REDIRECTS}",
            )
    except Exception as exc:  # noqa: BLE001
        return ExtractedPage(
            url=url,
            final_url=current_url,
            title=None,
            canonical_url=None,
            content_type=None,
            text="",
            status_code=0,
            error=str(exc),
        )
