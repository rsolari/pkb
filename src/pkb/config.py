from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SCOPES = ("tweet.read", "users.read", "bookmark.read", "offline.access")


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    client_id: str
    client_secret: str | None
    redirect_uri: str
    data_dir: Path
    scopes: tuple[str, ...] = DEFAULT_SCOPES
    thread_search: str = "all"
    link_timeout_seconds: float = 20.0

    @property
    def token_path(self) -> Path:
        return self.data_dir / ".secrets" / "x-token.json"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def markdown_dir(self) -> Path:
        return self.data_dir / "markdown"

    @property
    def state_path(self) -> Path:
        return self.data_dir / ".state" / "extractor.sqlite"

    @property
    def search_index_path(self) -> Path:
        return self.data_dir / ".state" / "search.sqlite"


def load_settings() -> Settings:
    load_dotenv()
    client_id = os.environ.get("X_CLIENT_ID", "").strip()
    client_secret = os.environ.get("X_CLIENT_SECRET", "").strip() or None
    redirect_uri = os.environ.get("X_REDIRECT_URI", "http://127.0.0.1:8765/callback").strip()
    data_dir = Path(os.environ.get("PKB_DATA_DIR", "data")).expanduser()
    thread_search = os.environ.get("PKB_THREAD_SEARCH", "all").strip().lower()
    if thread_search not in {"all", "recent", "none"}:
        raise ValueError("PKB_THREAD_SEARCH must be one of: all, recent, none")
    return Settings(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        data_dir=data_dir,
        thread_search=thread_search,
    )
