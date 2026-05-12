from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup, Tag

from .storage import stable_slug


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


def fetch_page(url: str, timeout: float = 20.0) -> ExtractedPage:
    headers = {
        "User-Agent": "pkb-x/0.1 (+local personal archive)",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = client.get(url)
        content_type = response.headers.get("content-type")
        body = response.text
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
        title, canonical, text = extract_main_text(body)
        error = f"HTTP {response.status_code}" if response.is_error else None
        return ExtractedPage(
            url=url,
            final_url=str(response.url),
            title=title,
            canonical_url=canonical,
            content_type=content_type,
            text=text,
            status_code=response.status_code,
            raw_html=body,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        return ExtractedPage(
            url=url,
            final_url=url,
            title=None,
            canonical_url=None,
            content_type=None,
            text="",
            status_code=0,
            error=str(exc),
        )
