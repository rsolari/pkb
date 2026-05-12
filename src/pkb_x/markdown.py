from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any

from .pages import ExtractedPage
from .storage import stable_slug
from .x_api import users_by_id


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _frontmatter(values: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in values.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {_yaml_scalar(item)}")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def post_text(post: dict[str, Any]) -> str:
    note = post.get("note_tweet") or {}
    if isinstance(note, dict):
        note_text = note.get("text")
        if note_text:
            return str(note_text)
    return str(post.get("text") or "")


def post_url(post: dict[str, Any], user: dict[str, Any] | None) -> str:
    username = user.get("username") if user else "i"
    return f"https://x.com/{username}/status/{post['id']}"


def created_date(post: dict[str, Any]) -> str:
    raw = post.get("created_at")
    if not raw:
        return "unknown-date"
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return raw[:10]


def _post_block(post: dict[str, Any], users: dict[str, dict[str, Any]]) -> str:
    user = users.get(post.get("author_id", ""))
    username = f"@{user['username']}" if user and user.get("username") else "@unknown"
    created = post.get("created_at") or "unknown time"
    text = post_text(post).strip()
    metrics = post.get("public_metrics") or {}
    metric_parts = []
    for key in ("reply_count", "retweet_count", "like_count", "quote_count", "bookmark_count"):
        if key in metrics:
            metric_parts.append(f"{key.replace('_count', '')}: {metrics[key]}")
    metrics_line = f"\n\nMetrics: {', '.join(metric_parts)}" if metric_parts else ""
    return f"### {username} - {created}\n\n{text}{metrics_line}\n\nSource: {post_url(post, user)}"


def flatten_thread_payload(thread_payload: dict[str, Any], fallback_post: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    pages = thread_payload.get("pages") if isinstance(thread_payload, dict) else None
    if not pages:
        return [fallback_post], {}
    posts: dict[str, dict[str, Any]] = {}
    users: dict[str, dict[str, Any]] = {}
    for page in pages:
        for post in page.get("data", []) or []:
            posts[post["id"]] = post
        users.update(users_by_id(page))
    sorted_posts = sorted(posts.values(), key=lambda item: item.get("created_at", ""))
    if not sorted_posts:
        sorted_posts = [fallback_post]
    return sorted_posts, users


def render_bookmark_markdown(
    bookmark_post: dict[str, Any],
    bookmark_payload: dict[str, Any],
    thread_payload: dict[str, Any],
    linked_pages: list[ExtractedPage],
    thread_error: str | None = None,
) -> str:
    bookmark_users = users_by_id(bookmark_payload)
    author = bookmark_users.get(bookmark_post.get("author_id", ""))
    thread_posts, thread_users = flatten_thread_payload(thread_payload, bookmark_post)
    all_users = {**thread_users, **bookmark_users}
    external_links = [page.url for page in linked_pages]
    frontmatter = _frontmatter(
        {
            "id": bookmark_post["id"],
            "url": post_url(bookmark_post, author),
            "author": f"@{author['username']}" if author and author.get("username") else None,
            "created_at": bookmark_post.get("created_at"),
            "conversation_id": bookmark_post.get("conversation_id"),
            "extraction_status": "partial" if thread_error else "complete",
            "thread_error": thread_error,
            "links": external_links,
        }
    )
    title_author = f"@{author['username']}" if author and author.get("username") else "unknown"
    title = f"# X bookmark {bookmark_post['id']} by {title_author}"
    sections = [frontmatter, title, "## Bookmarked post", _post_block(bookmark_post, all_users), "## Thread"]
    sections.extend(_post_block(post, all_users) for post in thread_posts)
    if linked_pages:
        sections.append("## Linked content")
        for page in linked_pages:
            status = f"status {page.status_code}" if page.status_code else "not fetched"
            link_title = page.title or page.final_url
            sections.append(f"### {link_title}\n\nURL: {page.final_url}\n\nExtraction: {status}\n")
    return "\n\n".join(sections).strip() + "\n"


def bookmark_output_path(base_dir: Path, post: dict[str, Any]) -> Path:
    date = created_date(post)
    return base_dir / "bookmarks" / date / f"{post['id']}.md"


def render_page_markdown(page: ExtractedPage) -> str:
    frontmatter = _frontmatter(
        {
            "url": page.url,
            "final_url": page.final_url,
            "canonical_url": page.canonical_url,
            "title": page.title,
            "content_type": page.content_type,
            "status_code": page.status_code,
            "error": page.error,
        }
    )
    title = page.title or page.final_url
    text = page.text or "_No readable text extracted._"
    return f"{frontmatter}\n\n# {title}\n\n{text}\n"


def page_output_path(base_dir: Path, page: ExtractedPage) -> Path:
    host = re.sub(r"[^a-zA-Z0-9.-]+", "-", page.final_url.split("/")[2]) if "://" in page.final_url else "unknown-host"
    return base_dir / "linked-pages" / host / f"{stable_slug(page.final_url)}.md"

