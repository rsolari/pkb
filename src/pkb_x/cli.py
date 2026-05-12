from __future__ import annotations

import argparse
import sys

from .config import load_settings
from .extractor import Extractor
from .oauth import authenticate
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
        stats = extractor.run(max_pages=args.max_pages, fetch_links=not args.no_links)
    finally:
        extractor.close()
    print("Extraction complete")
    for key, value in stats.items():
        print(f"{key}: {value}")
    print(f"Raw data: {settings.raw_dir}")
    print(f"Markdown: {settings.markdown_dir}")
    return 0 if stats["errors"] == 0 else 1


def cmd_init(_: argparse.Namespace) -> int:
    settings = load_settings()
    ensure_dirs(settings.data_dir)
    print(f"Initialized {settings.data_dir}")
    if not settings.client_id:
        print("Next: copy .env.example to .env and set X_CLIENT_ID")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pkb-x", description="Extract X bookmarks into a local knowledge-base archive.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create local data directories.")
    init_parser.set_defaults(func=cmd_init)

    auth_parser = subparsers.add_parser("auth", help="Authorize with X via OAuth 2.0 PKCE.")
    auth_parser.add_argument("--no-browser", action="store_true", help="Print the auth URL without opening a browser.")
    auth_parser.set_defaults(func=cmd_auth)

    extract_parser = subparsers.add_parser("extract", help="Fetch bookmarks, threads, linked pages, and Markdown files.")
    extract_parser.add_argument("--max-pages", type=int, default=None, help="Limit bookmark API pages for testing.")
    extract_parser.add_argument("--no-links", action="store_true", help="Skip outbound page fetching.")
    extract_parser.set_defaults(func=cmd_extract)

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


if __name__ == "__main__":
    raise SystemExit(main())

