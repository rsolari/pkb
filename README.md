# Personal Knowledge Base

This workspace contains a local-first personal knowledge base called `pkb`. `pkb` ingests data like text, pdfs blogs posts. Then it serves that data to LLMs.

`pkb` is designed to turn good ideas from your social feeds into context for your agents. For example, if you like/bookmark posts about app dev, `pkb` can import them. Then, your agent will be able to see all those ideas. You can ask your agent to review the backlog for suggestions about how to improve your app dev process.

The first source extractor archives X/Twitter bookmarks: it fetches bookmarks through the official X API, attempts to reconstruct the author's thread, follows outbound links, and writes both raw JSON/HTML and readable Markdown files.

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
pkb init
```

Authorize with X:

```bash
pkb auth
```

Run a small smoke extraction:

```bash
pkb extract --max-pages 1 --no-links
```

Run the full extraction:

```bash
pkb extract
```

If your shell cannot find `pkb`, run the same commands as `python -m pkb.cli ...` from the activated environment.

## Using `pkb` With an Agent

`pkb` does not run as a background service. It is a local CLI that an agent can call when it needs context.

There are two separate workflows:

1. Owner setup and refresh:

   ```bash
   pkb init
   pkb auth
   pkb extract
   ```

   `pkb auth` briefly starts a local OAuth callback listener at `http://127.0.0.1:8765/callback`. After the browser-based authorization finishes, the token is saved at `data/.secrets/x-token.json`; no daemon needs to keep running.

2. Agent discovery:

   ```bash
   pkb search "swiftui performance" --limit 10
   pkb browse --kind bookmark --limit 20
   pkb browse --kind linked-page --random --limit 10
   ```

   Search and browse only need local filesystem access to the configured `PKB_DATA_DIR` and its search index at `data/.state/search.sqlite`. They do not need X API access unless the agent is also expected to run `pkb extract`.

If you want an agent to use `pkb` reliably, make sure its environment can find the CLI and the same data directory:

```bash
source .venv/bin/activate
export PKB_DATA_DIR=data
pkb search "your query"
```

The agent-readable Markdown files live under `data/markdown/`, so an agent can also read those files directly after using `pkb search` or `pkb browse` to find relevant paths.

## Incremental Runs

Extraction is incremental by default. Each run still asks X for the current bookmark pages so it can discover new bookmarks, but bookmark IDs already archived as `complete` are skipped when their Markdown file still exists. Linked pages already archived as `complete` are also skipped when their metadata file still exists.

Use `--refresh` to re-fetch and rewrite already archived bookmarks, threads, and linked pages:

```bash
pkb extract --refresh
```

Use `--refresh-links` when you only want to re-fetch outbound linked pages without forcing every linked bookmark page to refresh all link-independent state. Bookmark Markdown may still be rewritten because it includes linked-page metadata:

```bash
pkb extract --refresh-links
```

During a full run, bookmarks that were previously seen but are no longer returned by X are marked `missing` in `data/.state/extractor.sqlite`; their existing files are left in place. `--max-pages` runs do not mark missing bookmarks because they only inspect a subset of the archive.

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
