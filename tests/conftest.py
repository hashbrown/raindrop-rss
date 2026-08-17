from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from raindrop_rss.config import AppConfig, load_config
from raindrop_rss.raindrop import APIResponse, RaindropClient


def config_json(
    *,
    max_items: int = 100,
    tags: list[str] | None = None,
    feeds: list[dict[str, Any]] | None = None,
) -> str:
    default_feeds = [
        {
            "slug": "ai",
            "title": "AI Feed",
            "description": "AI links",
            "tags": tags or ["ai", "machine-learning"],
            "sync_interval_hours": 24,
            "max_items": max_items,
        }
    ]
    return json.dumps(
        {
            "publisher_name": "Test Publisher",
            "base_url": "https://feeds.example.com",
            "language": "en-US",
            "cache": {
                "browser_max_age_seconds": 300,
                "shared_max_age_seconds": 3600,
                "stale_while_revalidate_seconds": 86400,
            },
            "feeds": feeds or default_feeds,
        }
    )


@pytest.fixture
def app_config() -> AppConfig:
    return load_config(config_json())


def raindrop_item(
    item_id: int,
    *,
    item_type: str = "article",
    tags: list[str] | None = None,
    created: str = "2026-08-15T12:00:00Z",
    updated: str = "2026-08-15T13:00:00Z",
    note: str = "A note",
    excerpt: str = "An excerpt",
) -> dict[str, Any]:
    return {
        "_id": item_id,
        "type": item_type,
        "title": f"Article {item_id}",
        "link": f"https://example.com/{item_id}",
        "tags": tags or ["ai"],
        "created": created,
        "lastUpdate": updated,
        "note": note,
        "excerpt": excerpt,
    }


class FakeKV:
    def __init__(self, events: list[tuple[str, str]] | None = None) -> None:
        self.values: dict[str, str] = {}
        self.events = events if events is not None else []

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def put(self, key: str, value: str) -> None:
        self.events.append(("kv.put", key))
        self.values[key] = value


@dataclass(slots=True)
class FakeObject:
    body: bytes


class FakeR2:
    def __init__(self, events: list[tuple[str, str]] | None = None) -> None:
        self.values: dict[str, bytes] = {}
        self.metadata: dict[str, tuple[str, str]] = {}
        self.events = events if events is not None else []
        self.fail_on_put_number: int | None = None
        self.put_count = 0

    async def get(self, key: str) -> FakeObject | None:
        value = self.values.get(key)
        return FakeObject(value) if value is not None else None

    async def put(
        self, key: str, value: bytes, *, content_type: str, cache_control: str
    ) -> None:
        self.put_count += 1
        self.events.append(("r2.put", key))
        if self.fail_on_put_number == self.put_count:
            raise RuntimeError("simulated R2 failure")
        self.values[key] = value
        self.metadata[key] = (content_type, cache_control)

    async def delete(self, key: str) -> None:
        self.events.append(("r2.delete", key))
        self.values.pop(key, None)


class FakeRaindrop:
    def __init__(self, items: list[dict[str, Any]] | None = None) -> None:
        self.items = items or []
        self.calls = 0
        self.error: Exception | None = None

    async def fetch_matching(
        self, tags: tuple[str, ...], max_items: int
    ) -> list[dict[str, Any]]:
        self.calls += 1
        if self.error:
            raise self.error
        return self.items


def client_for_pages(pages: list[list[dict[str, Any]]]) -> tuple[RaindropClient, list[str]]:
    urls: list[str] = []

    async def requester(url: str, headers: dict[str, str]) -> APIResponse:
        urls.append(url)
        page = len(urls) - 1
        return APIResponse(200, {"result": True, "items": pages[page]})

    return RaindropClient("test-token", requester), urls


NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
