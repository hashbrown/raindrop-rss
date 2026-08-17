from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from conftest import client_for_pages, raindrop_item

from raindrop_rss.raindrop import PAGE_SIZE, APIResponse, RaindropAPIError, RaindropClient


async def test_fetch_matching_paginates_until_short_page() -> None:
    first = [raindrop_item(item_id) for item_id in range(PAGE_SIZE)]
    second = [raindrop_item(100)]
    client, urls = client_for_pages([first, second])

    items = await client.fetch_matching(("rss",), 100)

    assert len(items) == PAGE_SIZE + 1
    assert [parse_qs(urlparse(url).query)["page"] for url in urls] == [["0"], ["1"]]
    assert all(parse_qs(urlparse(url).query)["perpage"] == ["50"] for url in urls)
    assert all(
        parse_qs(urlparse(url).query)["search"] == ['#"rss" type:article']
        for url in urls
    )


async def test_fetch_matching_stops_at_configured_max_without_extra_page() -> None:
    client, urls = client_for_pages([[raindrop_item(i) for i in range(PAGE_SIZE)]])
    assert len(await client.fetch_matching(("rss",), PAGE_SIZE)) == PAGE_SIZE
    assert len(urls) == 1


async def test_fetch_matching_queries_each_tag_for_or_semantics() -> None:
    client, urls = client_for_pages([[raindrop_item(1)], [raindrop_item(2)]])

    items = await client.fetch_matching(("ai", "machine-learning"), 100)

    assert len(items) == 2
    assert [parse_qs(urlparse(url).query)["search"] for url in urls] == [
        ['#"ai" type:article'],
        ['#"machine-learning" type:article'],
    ]


async def test_fetch_matching_raises_safe_error_for_http_failure() -> None:
    async def requester(url: str, headers: dict[str, str]) -> APIResponse:
        return APIResponse(429, {"error": "contains potentially sensitive details"})

    client = RaindropClient("secret-token", requester)
    with pytest.raises(RaindropAPIError, match="HTTP 429") as error:
        await client.fetch_matching(("rss",), 100)
    assert "secret-token" not in str(error.value)


async def test_fetch_matching_rejects_invalid_payload() -> None:
    async def requester(url: str, headers: dict[str, str]) -> APIResponse:
        return APIResponse(200, {"result": False})

    with pytest.raises(RaindropAPIError, match="invalid response"):
        await RaindropClient("token", requester).fetch_matching(("rss",), 100)
