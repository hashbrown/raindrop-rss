from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from .config import AppConfig, FeedConfig
from .models import select_feed_items
from .raindrop import RaindropAPIError, RaindropClient
from .render import render_atom, render_rss
from .state import FeedState, HistoryEntry, Representation, state_key

ATOM_TYPE = "application/atom+xml; charset=utf-8"
RSS_TYPE = "application/rss+xml; charset=utf-8"
ROLLBACK_VERSIONS = 2


class KVStore(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def put(self, key: str, value: str) -> None: ...


class ObjectStore(Protocol):
    async def get(self, key: str) -> Any | None: ...

    async def put(
        self, key: str, value: bytes, *, content_type: str, cache_control: str
    ) -> None: ...

    async def delete(self, key: str) -> None: ...


@dataclass(frozen=True, slots=True)
class SyncResult:
    attempted: int
    succeeded: tuple[str, ...]
    failed: tuple[str, ...]


def utc_string(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class FeedService:
    def __init__(
        self,
        config: AppConfig,
        state_store: KVStore,
        object_store: ObjectStore,
        raindrop: RaindropClient,
    ) -> None:
        self.config = config
        self.state_store = state_store
        self.object_store = object_store
        self.raindrop = raindrop

    async def get_state(self, slug: str) -> FeedState:
        raw = await self.state_store.get(state_key(slug))
        if not raw:
            return FeedState()
        try:
            return FeedState.from_json(str(raw))
        except (ValueError, TypeError, json.JSONDecodeError):
            return FeedState()

    def _fingerprint(self, feed: FeedConfig) -> str:
        return feed.fingerprint(
            self.config.publisher_name, self.config.base_url, self.config.language
        )

    async def sync_due(self, now: datetime | None = None) -> SyncResult:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        due: list[tuple[FeedConfig, FeedState]] = []
        for feed in self.config.feeds:
            state = await self.get_state(feed.slug)
            if state.is_due(now, self._fingerprint(feed)):
                due.append((feed, state))
        if not due:
            return SyncResult(attempted=0, succeeded=(), failed=())

        succeeded: list[str] = []
        failed: list[str] = []
        for feed, state in due:
            try:
                raw_items = await self.raindrop.fetch_matching(feed.tags, feed.max_items)
                await self._sync_feed(feed, state, raw_items, now)
            except Exception as exc:
                message = (
                    str(exc) if isinstance(exc, RaindropAPIError) else type(exc).__name__
                )
                await self._record_failure(feed, state, now, message)
                failed.append(feed.slug)
            else:
                succeeded.append(feed.slug)
        return SyncResult(len(due), tuple(succeeded), tuple(failed))

    async def _sync_feed(
        self,
        feed: FeedConfig,
        old_state: FeedState,
        raw_items: list[dict[str, Any]],
        now: datetime,
    ) -> None:
        items = select_feed_items(
            raw_items,
            feed.normalized_tags,
            feed.max_items,
            feed.normalized_redacted_tags,
        )
        atom_content = render_atom(self.config, feed, items, now)
        rss_content = render_rss(self.config, feed, items, now)
        atom_hash = digest(atom_content)
        rss_hash = digest(rss_content)
        atom_key = f"feeds/{feed.slug}/atom/{atom_hash}.atom"
        rss_key = f"feeds/{feed.slug}/rss/{rss_hash}.rss"

        if old_state.atom is None or old_state.atom.content_hash != atom_hash:
            await self.object_store.put(
                atom_key,
                atom_content,
                content_type=ATOM_TYPE,
                cache_control=self.config.cache.cdn_header_value,
            )
        if old_state.rss is None or old_state.rss.content_hash != rss_hash:
            await self.object_store.put(
                rss_key,
                rss_content,
                content_type=RSS_TYPE,
                cache_control=self.config.cache.cdn_header_value,
            )

        history = list(old_state.history)
        if old_state.atom and old_state.rss and (
            old_state.atom.object_key != atom_key or old_state.rss.object_key != rss_key
        ):
            history.insert(
                0,
                HistoryEntry(
                    atom_key=old_state.atom.object_key,
                    rss_key=old_state.rss.object_key,
                    published_at=old_state.last_successful_sync or utc_string(now),
                ),
            )
        retained = tuple(history[:ROLLBACK_VERSIONS])
        stale = history[ROLLBACK_VERSIONS:]
        new_state = FeedState(
            config_fingerprint=self._fingerprint(feed),
            atom=Representation(atom_key, atom_hash, ATOM_TYPE),
            rss=Representation(rss_key, rss_hash, RSS_TYPE),
            last_successful_sync=utc_string(now),
            next_sync_at=utc_string(now + timedelta(hours=feed.sync_interval_hours)),
            history=retained,
        )
        await self.state_store.put(state_key(feed.slug), new_state.to_json())

        for entry in stale:
            for key in (entry.atom_key, entry.rss_key):
                try:
                    await self.object_store.delete(key)
                except Exception:
                    pass

    async def _record_failure(
        self, feed: FeedConfig, old_state: FeedState, now: datetime, message: str
    ) -> None:
        failed_state = replace(
            old_state,
            last_error=message[:200],
            last_error_at=utc_string(now),
        )
        await self.state_store.put(state_key(feed.slug), failed_state.to_json())
