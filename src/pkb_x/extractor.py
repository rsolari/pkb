from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import httpx

from .config import Settings
from .markdown import bookmark_output_path, page_output_path, render_bookmark_markdown, render_page_markdown
from .pages import ExtractedPage, extract_urls_from_post, fetch_page
from .storage import StateStore, ensure_dirs, read_json, stable_slug, utc_now, write_json
from .x_api import XApi, author_for_post


class Extractor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        ensure_dirs(settings.data_dir)
        self.state = StateStore(settings.state_path)

    def close(self) -> None:
        self.state.close()

    def run(
        self,
        *,
        max_pages: int | None = None,
        fetch_links: bool = True,
        refresh: bool = False,
        refresh_links: bool = False,
    ) -> dict[str, int]:
        stats = {
            "bookmark_pages": 0,
            "bookmarks": 0,
            "skipped_bookmarks": 0,
            "missing_bookmarks": 0,
            "threads": 0,
            "links": 0,
            "skipped_links": 0,
            "errors": 0,
        }
        run_started_at = utc_now()
        seen_post_ids: set[str] = set()
        api = XApi(self.settings)
        try:
            me = api.me()
            user_id = me["data"]["id"]
            write_json(self.settings.raw_dir / "me.json", me)
            for page_number, payload in api.iter_bookmark_pages(user_id, max_pages=max_pages):
                stats["bookmark_pages"] += 1
                write_json(self.settings.raw_dir / "bookmarks" / f"page-{page_number:03d}.json", payload)
                for post in payload.get("data", []) or []:
                    stats["bookmarks"] += 1
                    post_id = post["id"]
                    seen_post_ids.add(post_id)
                    self.state.mark_bookmark_seen(post_id, run_started_at)
                    try:
                        bookmark_path = bookmark_output_path(self.settings.markdown_dir, post)
                        if self.state.should_skip_bookmark(post_id, bookmark_path.exists(), refresh or refresh_links):
                            stats["skipped_bookmarks"] += 1
                            self.state.mark(post_id, "bookmark", "skipped", "already archived")
                            continue
                        thread_payload, thread_error = self._fetch_thread(api, post, payload)
                        if not thread_error:
                            stats["threads"] += 1
                        linked_pages = self._fetch_links(
                            post,
                            fetch_links_enabled=fetch_links,
                            refresh=refresh or refresh_links,
                            seen_at=run_started_at,
                            stats=stats,
                        )
                        stats["links"] += len(linked_pages)
                        self._write_bookmark(post, payload, thread_payload, linked_pages, thread_error)
                        status = "partial" if thread_error else "complete"
                        self.state.mark_bookmark_archived(post_id, run_started_at, status, thread_error)
                    except Exception as exc:  # noqa: BLE001
                        stats["errors"] += 1
                        self.state.mark_bookmark_archived(post.get("id", "unknown"), run_started_at, "error", str(exc))
            if max_pages is None:
                stats["missing_bookmarks"] = self.state.mark_bookmarks_missing(seen_post_ids, run_started_at)
            return stats
        finally:
            api.close()

    def _fetch_thread(self, api: XApi, post: dict, payload: dict) -> tuple[dict, str | None]:
        conversation_id = post.get("conversation_id") or post["id"]
        author = author_for_post(post, payload)
        username = author.get("username") if author else None
        raw_path = self.settings.raw_dir / "threads" / f"{post['id']}.json"
        try:
            thread_payload = api.search_conversation(conversation_id, username=username)
            write_json(raw_path, thread_payload)
            return thread_payload, None
        except httpx.HTTPStatusError as exc:
            detail = f"{exc.response.status_code}: {exc.response.text[:500]}"
            fallback = {"pages": [{"data": [post], "includes": payload.get("includes", {}), "meta": {"result_count": 1}}]}
            write_json(raw_path, {"error": detail, "fallback": fallback})
            return fallback, detail

    def _fetch_links(
        self,
        post: dict,
        fetch_links_enabled: bool,
        refresh: bool,
        seen_at: str,
        stats: dict[str, int],
    ) -> list[ExtractedPage]:
        urls = extract_urls_from_post(post)
        if not fetch_links_enabled:
            return [
                ExtractedPage(
                    url=url,
                    final_url=url,
                    title=None,
                    canonical_url=None,
                    content_type=None,
                    text="",
                    status_code=0,
                    error="link fetching disabled",
                )
                for url in urls
            ]
        pages: list[ExtractedPage] = []
        for url in urls:
            self.state.mark_link_seen(url, seen_at)
            raw_base = self.settings.raw_dir / "linked-pages" / stable_slug(url)
            metadata_path = raw_base.with_suffix(".json")
            if self.state.should_skip_link(url, metadata_path.exists(), refresh):
                cached = self._cached_page(url, metadata_path)
                if cached:
                    pages.append(cached)
                    stats["skipped_links"] += 1
                    self.state.mark(url, "link", "skipped", "already archived")
                    continue
            page = fetch_page(url, timeout=self.settings.link_timeout_seconds)
            pages.append(page)
            page_json = asdict(page)
            page_json.pop("raw_html", None)
            page_json["raw_html_path"] = str(raw_base.with_suffix(".html")) if page.raw_html else None
            write_json(raw_base.with_suffix(".json"), page_json)
            if page.raw_html:
                raw_base.with_suffix(".html").write_text(page.raw_html, encoding="utf-8")
            markdown = render_page_markdown(page)
            out_path = page_output_path(self.settings.markdown_dir, page)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(markdown, encoding="utf-8")
            self.state.mark_link_fetched(url, seen_at, "complete" if not page.error else "partial", page.error)
        return pages

    def _cached_page(self, url: str, metadata_path: Path) -> ExtractedPage | None:
        try:
            payload = read_json(metadata_path)
            return ExtractedPage(
                url=str(payload.get("url") or url),
                final_url=str(payload.get("final_url") or url),
                title=payload.get("title"),
                canonical_url=payload.get("canonical_url"),
                content_type=payload.get("content_type"),
                text="",
                status_code=int(payload.get("status_code") or 0),
                error=payload.get("error"),
            )
        except Exception:  # noqa: BLE001
            return None

    def _write_bookmark(
        self,
        post: dict,
        payload: dict,
        thread_payload: dict,
        linked_pages: list[ExtractedPage],
        thread_error: str | None,
    ) -> Path:
        markdown = render_bookmark_markdown(post, payload, thread_payload, linked_pages, thread_error)
        out_path = bookmark_output_path(self.settings.markdown_dir, post)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown, encoding="utf-8")
        return out_path
