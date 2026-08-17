from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .config import AppConfig
from .service import FeedService


@dataclass(frozen=True, slots=True)
class AppResponse:
    body: Any | None
    status: int
    headers: dict[str, str]


def _text_response(message: str, status: int, headers: dict[str, str] | None = None) -> AppResponse:
    response_headers = {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}
    response_headers.update(headers or {})
    return AppResponse(message.encode(), status, response_headers)


def _etag_matches(value: str | None, etag: str) -> bool:
    if not value:
        return False
    candidates = {candidate.strip().removeprefix("W/") for candidate in value.split(",")}
    return "*" in candidates or etag in candidates


class FeedApplication:
    def __init__(self, config: AppConfig, service: FeedService) -> None:
        self.config = config
        self.service = service

    async def handle(
        self, method: str, path: str, headers: Mapping[str, str] | None = None
    ) -> AppResponse:
        method = method.upper()
        request_headers = {key.lower(): value for key, value in (headers or {}).items()}
        if method not in {"GET", "HEAD"}:
            return _text_response("Method not allowed", 405, {"Allow": "GET, HEAD"})
        if path == "/health":
            return await self._health(method)

        representation_name: str | None = None
        slug = ""
        for suffix, name in ((".atom", "atom"), (".rss", "rss")):
            if path.startswith("/") and path.endswith(suffix):
                slug = path[1 : -len(suffix)]
                representation_name = name
                break
        feed = self.config.feed_by_slug(slug)
        if representation_name is None or feed is None:
            return _text_response("Feed not found", 404)

        state = await self.service.get_state(slug)
        representation = getattr(state, representation_name)
        if representation is None:
            return _text_response(
                "Feed has not completed its first successful synchronization",
                503,
                {"Retry-After": "300"},
            )

        etag = f'"{representation.content_hash}"'
        common_headers = {
            "Content-Type": representation.content_type,
            "Cache-Control": self.config.cache.browser_header_value,
            "CDN-Cache-Control": self.config.cache.cdn_header_value,
            "ETag": etag,
            "X-Content-Type-Options": "nosniff",
        }
        if _etag_matches(request_headers.get("if-none-match"), etag):
            return AppResponse(None, 304, common_headers)

        obj = await self.service.object_store.get(representation.object_key)
        if obj is None:
            return _text_response(
                "Feed object is temporarily unavailable", 503, {"Retry-After": "60"}
            )
        body = getattr(obj, "body", obj)
        if method == "HEAD":
            body = None
        return AppResponse(body, 200, common_headers)

    async def _health(self, method: str) -> AppResponse:
        feeds: list[dict[str, Any]] = []
        healthy = True
        for feed in self.config.feeds:
            state = await self.service.get_state(feed.slug)
            available = bool(state.atom and state.rss)
            healthy = healthy and available and state.last_error is None
            feeds.append(
                {
                    "slug": feed.slug,
                    "available": available,
                    "last_successful_sync": state.last_successful_sync,
                    "next_sync_at": state.next_sync_at,
                    "last_error": state.last_error,
                    "last_error_at": state.last_error_at,
                }
            )
        status = "ok" if healthy else "degraded"
        body = json.dumps({"status": status, "feeds": feeds}, sort_keys=True).encode()
        return AppResponse(
            None if method == "HEAD" else body,
            200 if healthy else 503,
            {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"},
        )
