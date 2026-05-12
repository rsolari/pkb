from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx

from .config import Settings
from .models import JsonObject
from .oauth import get_valid_token


API_BASE = "https://api.x.com/2"

POST_FIELDS = ",".join(
    [
        "id",
        "text",
        "note_tweet",
        "author_id",
        "created_at",
        "conversation_id",
        "in_reply_to_user_id",
        "referenced_tweets",
        "entities",
        "attachments",
        "public_metrics",
        "lang",
        "possibly_sensitive",
        "edit_history_tweet_ids",
    ]
)
USER_FIELDS = "id,name,username,verified,profile_image_url,description,created_at"
MEDIA_FIELDS = "media_key,type,url,preview_image_url,alt_text,duration_ms,width,height"
EXPANSIONS = "author_id,attachments.media_keys,referenced_tweets.id,referenced_tweets.id.author_id"


class XApi:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        token = get_valid_token(settings)
        self.client = httpx.Client(
            base_url=API_BASE,
            timeout=30,
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )

    def close(self) -> None:
        self.client.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> JsonObject:
        response = self.client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def me(self) -> JsonObject:
        return self._get("/users/me", {"user.fields": USER_FIELDS})

    def iter_bookmark_pages(self, user_id: str, max_pages: int | None = None) -> Iterator[tuple[int, JsonObject]]:
        params: dict[str, Any] = {
            "max_results": 100,
            "tweet.fields": POST_FIELDS,
            "user.fields": USER_FIELDS,
            "media.fields": MEDIA_FIELDS,
            "expansions": EXPANSIONS,
        }
        page = 1
        while True:
            payload = self._get(f"/users/{user_id}/bookmarks", params)
            yield page, payload
            next_token = payload.get("meta", {}).get("next_token")
            if not next_token or (max_pages and page >= max_pages):
                break
            params["pagination_token"] = next_token
            page += 1

    def search_conversation(self, conversation_id: str, username: str | None = None) -> JsonObject:
        if self.settings.thread_search == "none":
            return {"data": [], "meta": {"result_count": 0}, "note": "thread search disabled"}
        path = "/tweets/search/all" if self.settings.thread_search == "all" else "/tweets/search/recent"
        query = f"conversation_id:{conversation_id}"
        if username:
            query = f"{query} from:{username}"
        params: dict[str, Any] = {
            "query": f"{query} -is:retweet",
            "max_results": 100,
            "tweet.fields": POST_FIELDS,
            "user.fields": USER_FIELDS,
            "media.fields": MEDIA_FIELDS,
            "expansions": EXPANSIONS,
        }
        pages: list[JsonObject] = []
        while True:
            payload = self._get(path, params)
            pages.append(payload)
            next_token = payload.get("meta", {}).get("next_token")
            if not next_token:
                break
            params["next_token"] = next_token
        return {"pages": pages}

    def lookup_posts(self, ids: list[str]) -> JsonObject:
        if not ids:
            return {"data": []}
        params = {
            "ids": ",".join(ids[:100]),
            "tweet.fields": POST_FIELDS,
            "user.fields": USER_FIELDS,
            "media.fields": MEDIA_FIELDS,
            "expansions": EXPANSIONS,
        }
        return self._get("/tweets", params)


def users_by_id(payload: JsonObject) -> dict[str, JsonObject]:
    return {user["id"]: user for user in payload.get("includes", {}).get("users", [])}


def author_for_post(post: JsonObject, payload: JsonObject) -> JsonObject | None:
    author_id = post.get("author_id")
    return users_by_id(payload).get(author_id) if author_id else None

