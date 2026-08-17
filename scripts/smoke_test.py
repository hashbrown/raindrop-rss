"""Exercise a complete cached-feed sync and public read without external services."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from raindrop_rss.application import FeedApplication
from raindrop_rss.config import load_config
from raindrop_rss.service import FeedService


class MemoryKV:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def put(self, key: str, value: str) -> None:
        self.data[key] = value


@dataclass(slots=True)
class MemoryObject:
    body: bytes


class MemoryR2:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    async def get(self, key: str) -> MemoryObject | None:
        body = self.data.get(key)
        return None if body is None else MemoryObject(body)

    async def put(
        self, key: str, value: bytes, *, content_type: str, cache_control: str
    ) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


class FixtureRaindrop:
    async def fetch_matching(
        self, tags: tuple[str, ...], max_items: int
    ) -> list[dict[str, Any]]:
        return [
            {
                "_id": item_id,
                "type": "article",
                "title": f"RSS article {item_id}",
                "link": f"https://example.com/{item_id}",
                "tags": ["rss"] if item_id <= 2 else ["other"],
                "created": f"2026-08-{item_id + 10:02d}T12:00:00Z",
                "lastUpdate": f"2026-08-{item_id + 10:02d}T13:00:00Z",
                "note": f"Test note {item_id}",
                "excerpt": "",
            }
            for item_id in range(1, 4)
        ]


async def main() -> None:
    config = load_config(
        json.dumps(
            {
                "publisher_name": "Smoke Test",
                "base_url": "https://feeds.example.test",
                "language": "en-US",
                "feeds": [
                    {
                        "slug": "raindrop-test",
                        "title": "Raindrop Test",
                        "description": "Smoke test feed",
                        "tags": ["rss"],
                        "max_items": 100,
                        "sync_interval_hours": 24,
                    }
                ],
            }
        )
    )
    kv, r2 = MemoryKV(), MemoryR2()
    service = FeedService(config, kv, r2, FixtureRaindrop())
    result = await service.sync_due(datetime(2026, 8, 16, 12, tzinfo=UTC))
    assert result.succeeded == ("raindrop-test",)

    app = FeedApplication(config, service)
    atom = await app.handle("GET", "/raindrop-test.atom")
    rss = await app.handle("GET", "/raindrop-test.rss")
    assert atom.status == rss.status == 200
    assert len(ET.fromstring(atom.body).findall("{http://www.w3.org/2005/Atom}entry")) == 2
    assert len(ET.fromstring(rss.body).findall("channel/item")) == 2
    print("smoke test passed: cached Atom and RSS feeds each contain 2 items")


if __name__ == "__main__":
    asyncio.run(main())
