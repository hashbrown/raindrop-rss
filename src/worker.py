from __future__ import annotations

import hmac
import json
from typing import Any
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint, fetch

from raindrop_rss.application import FeedApplication
from raindrop_rss.config import load_config
from raindrop_rss.embedded_config import FEED_CONFIG_JSON
from raindrop_rss.raindrop import APIResponse, RaindropClient
from raindrop_rss.service import FeedService

CONFIG = load_config(FEED_CONFIG_JSON)


def _to_python(value: Any) -> Any:
    converter = getattr(value, "to_py", None)
    return converter() if callable(converter) else value


class WorkerKVStore:
    def __init__(self, binding: Any) -> None:
        self.binding = binding

    async def get(self, key: str) -> str | None:
        value = await self.binding.get(key)
        return None if value is None else str(value)

    async def put(self, key: str, value: str) -> None:
        await self.binding.put(key, value)


class WorkerObjectStore:
    def __init__(self, binding: Any) -> None:
        self.binding = binding

    async def get(self, key: str) -> Any | None:
        return await self.binding.get(key)

    async def put(
        self, key: str, value: bytes, *, content_type: str, cache_control: str
    ) -> None:
        await self.binding.put(
            key,
            value,
            httpMetadata={"contentType": content_type, "cacheControl": cache_control},
        )

    async def delete(self, key: str) -> None:
        await self.binding.delete(key)


async def raindrop_request(url: str, headers: dict[str, str]) -> APIResponse:
    response = await fetch(url, method="GET", headers=headers)
    payload = _to_python(await response.json())
    return APIResponse(status=int(response.status), payload=payload)


class Default(WorkerEntrypoint):
    def _service(self) -> FeedService:
        state_store = WorkerKVStore(self.env.FEED_STATE)
        object_store = WorkerObjectStore(self.env.FEED_XML)
        client = RaindropClient(str(self.env.RAINDROP_API_TOKEN), raindrop_request)
        return FeedService(CONFIG, state_store, object_store, client)

    async def fetch(self, request):
        service = self._service()
        parsed = urlparse(request.url)
        headers = {str(key).lower(): str(value) for key, value in request.headers.items()}
        method = getattr(request.method, "value", str(request.method))
        if parsed.path == "/_internal/sync":
            if method != "POST" or not self._is_authorized_sync(headers):
                return Response("Not found", status=404)
            result = await service.sync_all()
            status = 502 if result.failed else 200
            return Response(
                json.dumps(
                    {
                        "attempted": result.attempted,
                        "succeeded": result.succeeded,
                        "failed": result.failed,
                    }
                ),
                status=status,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        application = FeedApplication(CONFIG, service)
        result = await application.handle(method, parsed.path, headers)
        return Response(result.body, status=result.status, headers=result.headers)

    def _is_authorized_sync(self, headers: dict[str, str]) -> bool:
        token = headers.get("authorization", "")
        expected = f"Bearer {self.env.RAINDROP_API_TOKEN}"
        return hmac.compare_digest(token, expected)

    async def scheduled(self, controller, env, ctx):
        result = await self._service().sync_due()
        print(
            {
                "event": "scheduled_sync",
                "cron": str(controller.cron),
                "attempted": result.attempted,
                "succeeded": result.succeeded,
                "failed": result.failed,
            }
        )
        if result.failed:
            failed_feeds = ", ".join(result.failed)
            raise RuntimeError(f"Feed synchronization failed: {failed_feeds}")
