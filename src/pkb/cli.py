from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import asdict

from .config import load_settings
from .extractor import Extractor
from .index import reindex
from .oauth import authenticate
from .search import browse, search
from .storage import ensure_dirs


def cmd_auth(args: argparse.Namespace) -> int:
    settings = load_settings()
    ensure_dirs(settings.data_dir)
    token = authenticate(settings, open_browser=not args.no_browser)
    print(f"Saved token to {settings.token_path}")
    print(f"Scopes: {token.get('scope', '(not returned)')}")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    settings = load_settings()
    extractor = Extractor(settings)
    try:
        stats = extractor.run(
            max_pages=args.max_pages,
            fetch_links=not args.no_links,
            refresh=args.refresh,
            refresh_links=args.refresh_links,
        )
    finally:
        extractor.close()
    index_stats = reindex(settings)
    print("Extraction complete")
    for key, value in stats.items():
        print(f"{key}: {value}")
    print(f"Raw data: {settings.raw_dir}")
    print(f"Markdown: {settings.markdown_dir}")
    print(f"Search index: {settings.search_index_path}")
    print(f"indexed: {index_stats.indexed}")
    print(f"index_skipped: {index_stats.skipped}")
    print(f"index_deleted: {index_stats.deleted}")
    return 0 if stats["errors"] == 0 else 1


def cmd_index(args: argparse.Namespace) -> int:
    settings = load_settings()
    stats = reindex(settings, full=args.full)
    print("Index complete")
    print(f"Search index: {settings.search_index_path}")
    print(f"scanned: {stats.scanned}")
    print(f"indexed: {stats.indexed}")
    print(f"skipped: {stats.skipped}")
    print(f"deleted: {stats.deleted}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    settings = load_settings()
    hits = search(
        settings,
        args.query,
        kind=args.kind,
        author=args.author,
        since=args.since,
        until=args.until,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps([asdict(hit) for hit in hits], ensure_ascii=False, indent=2))
    else:
        _print_search_hits(settings, hits)
    return 0


def cmd_browse(args: argparse.Namespace) -> int:
    settings = load_settings()
    hits = browse(
        settings,
        kind=args.kind,
        author=args.author,
        since=args.since,
        until=args.until,
        random=args.random,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps([asdict(hit) for hit in hits], ensure_ascii=False, indent=2))
    else:
        _print_browse_hits(settings, hits)
    return 0


def cmd_init(_: argparse.Namespace) -> int:
    settings = load_settings()
    ensure_dirs(settings.data_dir)
    print(f"Initialized {settings.data_dir}")
    if not settings.client_id:
        print("Next: copy .env.example to .env and set X_CLIENT_ID")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pkb", description="Manage a local personal knowledge-base archive.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create local data directories.")
    init_parser.set_defaults(func=cmd_init)

    auth_parser = subparsers.add_parser("auth", help="Authorize with X via OAuth 2.0 PKCE.")
    auth_parser.add_argument("--no-browser", action="store_true", help="Print the auth URL without opening a browser.")
    auth_parser.set_defaults(func=cmd_auth)

    extract_parser = subparsers.add_parser("extract", help="Fetch bookmarks, threads, linked pages, and Markdown files.")
    extract_parser.add_argument("--max-pages", type=int, default=None, help="Limit bookmark API pages for testing.")
    extract_parser.add_argument("--no-links", action="store_true", help="Skip outbound page fetching.")
    extract_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch and rewrite already archived bookmarks, threads, and linked pages.",
    )
    extract_parser.add_argument(
        "--refresh-links",
        action="store_true",
        help="Re-fetch linked pages even when their metadata is already archived.",
    )
    extract_parser.set_defaults(func=cmd_extract)

    index_parser = subparsers.add_parser("index", help="Build or refresh the local Markdown search index.")
    index_parser.add_argument("--full", action="store_true", help="Re-index all Markdown files even if body hashes match.")
    index_parser.set_defaults(func=cmd_index)

    search_parser = subparsers.add_parser("search", help="Search indexed Markdown with FTS5 query syntax.")
    search_parser.add_argument("query", help="FTS5 MATCH query.")
    _add_discovery_filters(search_parser)
    search_parser.add_argument("--json", action="store_true", help="Write results as JSON.")
    search_parser.set_defaults(func=cmd_search)

    browse_parser = subparsers.add_parser("browse", help="Browse indexed Markdown without a search query.")
    _add_discovery_filters(browse_parser)
    browse_parser.add_argument("--random", action="store_true", help="Return a random result order.")
    browse_parser.add_argument("--json", action="store_true", help="Write results as JSON.")
    browse_parser.set_defaults(func=cmd_browse)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _add_discovery_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--kind", choices=("bookmark", "linked-page"), default=None, help="Limit results by document kind.")
    parser.add_argument("--author", default=None, help="Limit results by author handle or linked-page host.")
    parser.add_argument("--since", type=_iso_date, default=None, help="Limit results to documents on or after YYYY-MM-DD.")
    parser.add_argument("--until", type=_iso_date, default=None, help="Limit results to documents before YYYY-MM-DD.")
    parser.add_argument("--limit", type=_positive_int, default=20, help="Maximum result count.")


def _iso_date(value: str) -> str:
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc
    return value


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


def _print_search_hits(settings, hits) -> None:
    for hit in hits:
        print(f"{settings.markdown_dir / hit.path}:1")
        meta = _metadata(hit.author, hit.created_at, f"score {hit.score:.4f}")
        if meta:
            print(f"  {meta}")
        if hit.title:
            print(f"  {hit.title}")
        if hit.source_url:
            print(f"  {hit.source_url}")
        if hit.snippet:
            print(f"  {hit.snippet}")


def _print_browse_hits(settings, hits) -> None:
    for hit in hits:
        print(f"{settings.markdown_dir / hit.path}:1")
        meta = _metadata(hit.author, hit.created_at, hit.kind)
        if meta:
            print(f"  {meta}")
        if hit.title:
            print(f"  {hit.title}")
        if hit.source_url:
            print(f"  {hit.source_url}")


def _metadata(*parts: str | None) -> str:
    return " | ".join(part for part in parts if part)


if __name__ == "__main__":
    raise SystemExit(main())
