---
name: pkb
description: Use when Codex needs to find, browse, refresh, or explain context from the local-first `pkb` personal knowledge base CLI; when a user asks an agent to use their saved bookmarks, X/Twitter archive, linked-page Markdown, or local knowledge-base search; or when diagnosing `pkb` setup, OAuth, data directory, extraction, indexing, search, or browse commands.
---

# pkb

Use `pkb` as an on-demand local context source. It does not require a background service for normal agent use.

## Quick Start

From the repository or any shell where the package is installed:

```bash
pkb search "query terms" --limit 10
pkb browse --kind bookmark --limit 20
pkb browse --kind linked-page --random --limit 10
```

If `pkb` is not on `PATH`, activate the project environment or run the module directly:

```bash
source .venv/bin/activate
python -m pkb.cli search "query terms" --limit 10
```

## Agent Workflow

1. Convert the user task into 1-3 focused search queries.
2. Run `pkb search` first for semantic or keyword-driven discovery.
3. Use `pkb browse` when the user wants recent, random, or filtered context without a specific query.
4. Open relevant Markdown files under `data/markdown/` after `pkb` returns paths.
5. Cite or summarize the local context in the answer, making clear when a conclusion comes from the archive.

`pkb search` uses SQLite FTS5 query syntax. Prefer simple quoted phrases or terms unless advanced matching is needed.

## Setup And Auth

Searching and browsing existing content only needs local filesystem access to `PKB_DATA_DIR`, which defaults to `data`.

Refreshing the archive requires X OAuth:

```bash
pkb init
pkb auth
pkb extract
```

`pkb auth` briefly starts a local callback listener at:

```text
http://127.0.0.1:8765/callback
```

After authorization, tokens are stored in:

```text
data/.secrets/x-token.json
```

No daemon needs to stay running after auth completes.

## Useful Commands

Install from the repo:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Smoke-test extraction without linked pages:

```bash
pkb extract --max-pages 1 --no-links
```

Refresh archived content:

```bash
pkb extract --refresh
pkb extract --refresh-links
```

Rebuild the search index:

```bash
pkb index
pkb index --full
```

Filter discovery:

```bash
pkb search "app dev" --author some_handle --since 2026-01-01
pkb browse --kind linked-page --limit 25
```

## Troubleshooting

- If imports fail in tests or `python -m pkb.cli`, install the package with `python -m pip install -e ".[dev]"` inside the active environment.
- If `pkb search` returns nothing for known Markdown files, run `pkb index`.
- If `pkb extract` fails on thread search permissions, set `PKB_THREAD_SEARCH=recent` or `PKB_THREAD_SEARCH=none`.
- If an agent should use a non-default archive, export `PKB_DATA_DIR=/path/to/data` before running commands.
