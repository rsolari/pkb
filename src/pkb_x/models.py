from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


JsonObject = dict[str, Any]


@dataclass(frozen=True)
class User:
    id: str
    username: str
    name: str | None = None


@dataclass(frozen=True)
class Post:
    id: str
    text: str
    author_id: str | None = None
    created_at: str | None = None
    conversation_id: str | None = None
    in_reply_to_user_id: str | None = None
    referenced_tweets: list[JsonObject] = field(default_factory=list)
    entities: JsonObject = field(default_factory=dict)
    note_tweet: JsonObject | None = None
    raw: JsonObject = field(default_factory=dict)

