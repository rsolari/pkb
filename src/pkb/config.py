from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
    env_token: dict[str, Any] | None = None
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
        env_token=_load_env_token(),
        thread_search=thread_search,
    )


def _load_env_token() -> dict[str, Any] | None:
    token_json = os.environ.get("X_TOKEN_JSON", "").strip()
    if token_json:
        token = json.loads(token_json)
        if not isinstance(token, dict):
            raise ValueError("X_TOKEN_JSON must be a JSON object")
        return token

    access_token = os.environ.get("X_ACCESS_TOKEN", "").strip() or os.environ.get("X_BEARER_TOKEN", "").strip()
    if not access_token:
        return None

    token: dict[str, Any] = {
        "access_token": access_token,
        "token_type": os.environ.get("X_TOKEN_TYPE", "bearer").strip() or "bearer",
    }
    refresh_token = os.environ.get("X_REFRESH_TOKEN", "").strip()
    if refresh_token:
        token["refresh_token"] = refresh_token
    scope = os.environ.get("X_TOKEN_SCOPE", "").strip()
    if scope:
        token["scope"] = scope
    expires_in = os.environ.get("X_EXPIRES_IN", "").strip()
    if expires_in:
        token["expires_in"] = int(expires_in)
    obtained_at = os.environ.get("X_TOKEN_OBTAINED_AT", "").strip()
    if obtained_at:
        token["obtained_at"] = int(obtained_at)
    return token
