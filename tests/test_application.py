from __future__ import annotations

import json

from conftest import NOW, FakeKV, FakeR2, FakeRaindrop, raindrop_item

from raindrop_rss.application import FeedApplication
from raindrop_rss.service import FeedService


async def synced_application(app_config):
    kv, r2, raindrop = FakeKV(), FakeR2(), FakeRaindrop([raindrop_item(1)])
    service = FeedService(app_config, kv, r2, raindrop)
    await service.sync_due(NOW)
    return FeedApplication(app_config, service), r2, raindrop


async def test_atom_and_rss_routes_serve_r2_without_raindrop_call(app_config) -> None:
    app, _, raindrop = await synced_application(app_config)
    initial_calls = raindrop.calls

    atom = await app.handle("GET", "/ai.atom")
    rss = await app.handle("GET", "/ai.rss")

    assert atom.status == rss.status == 200
    assert atom.headers["Content-Type"].startswith("application/atom+xml")
    assert rss.headers["Content-Type"].startswith("application/rss+xml")
    assert atom.headers["Cache-Control"] == "public, max-age=300"
    assert atom.headers["CDN-Cache-Control"] == (
        "public, max-age=3600, stale-while-revalidate=86400"
    )
    assert raindrop.calls == initial_calls


async def test_conditional_request_returns_304_without_r2_read(app_config) -> None:
    app, r2, _ = await synced_application(app_config)
    first = await app.handle("GET", "/ai.atom")

    async def forbidden_get(key: str):
        raise AssertionError("R2 should not be read for matching ETag")

    r2.get = forbidden_get
    result = await app.handle("GET", "/ai.atom", {"If-None-Match": first.headers["ETag"]})
    assert result.status == 304
    assert result.body is None


async def test_head_has_headers_without_body(app_config) -> None:
    app, _, _ = await synced_application(app_config)
    result = await app.handle("HEAD", "/ai.rss")
    assert result.status == 200
    assert result.body is None
    assert result.headers["ETag"].startswith('"')


async def test_unknown_unavailable_and_method_routes(app_config) -> None:
    service = FeedService(app_config, FakeKV(), FakeR2(), FakeRaindrop())
    app = FeedApplication(app_config, service)
    assert (await app.handle("GET", "/missing.atom")).status == 404
    assert (await app.handle("GET", "/ai.xml")).status == 404
    assert (await app.handle("GET", "/ai.atom")).status == 503
    assert (await app.handle("POST", "/ai.atom")).status == 405


async def test_health_contains_non_secret_sync_status(app_config) -> None:
    app, _, _ = await synced_application(app_config)
    result = await app.handle("GET", "/health")
    payload = json.loads(result.body)
    assert result.status == 200
    assert result.headers["Cache-Control"] == "no-store"
    assert payload["status"] == "ok"
    assert payload["feeds"][0]["available"] is True
    assert "object_key" not in payload["feeds"][0]


async def test_health_is_degraded_before_first_successful_sync(app_config) -> None:
    service = FeedService(app_config, FakeKV(), FakeR2(), FakeRaindrop())
    app = FeedApplication(app_config, service)

    result = await app.handle("GET", "/health")
    payload = json.loads(result.body)

    assert result.status == 503
    assert payload["status"] == "degraded"
    assert payload["feeds"][0]["available"] is False


async def test_health_is_degraded_after_failed_sync(app_config) -> None:
    kv, r2, raindrop = FakeKV(), FakeR2(), FakeRaindrop()
    raindrop.error = RuntimeError("simulated failure")
    service = FeedService(app_config, kv, r2, raindrop)
    await service.sync_due(NOW)
    app = FeedApplication(app_config, service)

    result = await app.handle("GET", "/health")
    payload = json.loads(result.body)

    assert result.status == 503
    assert payload["status"] == "degraded"
    assert payload["feeds"][0]["last_error"] == "RuntimeError"


async def test_degraded_health_head_has_status_without_body(app_config) -> None:
    service = FeedService(app_config, FakeKV(), FakeR2(), FakeRaindrop())
    app = FeedApplication(app_config, service)

    result = await app.handle("HEAD", "/health")

    assert result.status == 503
    assert result.body is None
