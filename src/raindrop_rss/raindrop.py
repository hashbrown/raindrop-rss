from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

RAINDROP_API_URL = "https://api.raindrop.io/rest/v1/raindrops/0"
PAGE_SIZE = 50


class RaindropAPIError(RuntimeError):
    """A safe, non-secret Raindrop API error."""


@dataclass(frozen=True, slots=True)
class APIResponse:
    status: int
    payload: Any


Requester = Callable[[str, dict[str, str]], Awaitable[APIResponse]]


class RaindropClient:
    def __init__(self, token: str, requester: Requester) -> None:
        if not token:
            raise ValueError("Raindrop API token is required")
        self._token = token
        self._requester = requester

    async def fetch_matching(
        self, tags: tuple[str, ...], max_items: int
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": "raindrop-rss/0.1",
        }
        for tag in tags:
            page = 0
            fetched = 0
            escaped_tag = tag.replace("\\", "\\\\").replace('"', '\\"')
            search = f'#"{escaped_tag}" type:article'
            while fetched < max_items:
                per_page = min(PAGE_SIZE, max_items - fetched)
                query = urlencode(
                    {
                        "sort": "-created",
                        "perpage": per_page,
                        "page": page,
                        "search": search,
                    }
                )
                response = await self._requester(f"{RAINDROP_API_URL}?{query}", headers)
                if response.status != 200:
                    raise RaindropAPIError(
                        f"Raindrop API returned HTTP {response.status}"
                    )
                payload = response.payload
                if not isinstance(payload, dict) or payload.get("result") is not True:
                    raise RaindropAPIError("Raindrop API returned an invalid response")
                page_items = payload.get("items")
                if not isinstance(page_items, list):
                    raise RaindropAPIError(
                        "Raindrop API response did not contain an items array"
                    )
                items.extend(item for item in page_items if isinstance(item, dict))
                fetched += len(page_items)
                if len(page_items) < per_page:
                    break
                page += 1
        return items
