# Personal Knowledge Base: X Bookmark Extractor

This workspace contains a local-first extractor for X/Twitter bookmarks. It fetches your bookmarks through the official X API, attempts to reconstruct the author's thread, follows outbound links, and writes both raw JSON/HTML and readable Markdown files.

## What It Produces

```text
data/
  raw/
    me.json
    bookmarks/page-001.json
    threads/<bookmark-id>.json
    linked-pages/<url-slug>.json
    linked-pages/<url-slug>.html
  markdown/
    bookmarks/<post-date>/<bookmark-id>.md
    linked-pages/<host>/<url-slug>.md
  .state/extractor.sqlite
  .secrets/x-token.json
```

`data/` is gitignored because it contains personal archive data and OAuth tokens.

## Setup

1. Create an X developer app at `https://console.x.com`.
2. Enable OAuth 2.0 and set the callback URL to:

   ```text
   http://127.0.0.1:8765/callback
   ```

3. Request these scopes:

   ```text
   tweet.read users.read bookmark.read offline.access
   ```

4. Create local config:

   ```bash
   cp .env.example .env
   ```

5. Set `X_CLIENT_ID` in `.env`.

   If your X app is configured as a confidential client, also set `X_CLIENT_SECRET`.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Use

Initialize runtime directories:

```bash
pkb-x init
```

Authorize with X:

```bash
pkb-x auth
```

Run a small smoke extraction:

```bash
pkb-x extract --max-pages 1 --no-links
```

Run the full extraction:

```bash
pkb-x extract
```

If your shell cannot find `pkb-x`, run the same commands as `python -m pkb_x.cli ...` from the activated environment.

## Thread Extraction

By default the extractor uses X full-archive search:

```text
PKB_THREAD_SEARCH=all
```

If your API access rejects full-archive search, switch to recent search or disable thread search:

```text
PKB_THREAD_SEARCH=recent
```

or:

```text
PKB_THREAD_SEARCH=none
```

When thread search fails for a bookmark, the Markdown file is still written with the bookmarked post and any available referenced/quoted context, and the API error is recorded in frontmatter.

## Notes

- The official bookmarks endpoint is documented as returning up to the 800 most recent bookmarked posts.
- X does not expose a `bookmarked_at` timestamp in the bookmark response, so files are grouped by post creation date.
- Outbound link extraction is intentionally conservative. It saves readable text for normal HTML pages and records unsupported content types or fetch errors without failing the whole run.
