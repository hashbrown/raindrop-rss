from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ConfigurationError(ValueError):
    """Raised when feed configuration is invalid."""


@dataclass(frozen=True, slots=True)
class CacheConfig:
    browser_max_age_seconds: int = 300
    shared_max_age_seconds: int = 3600
    stale_while_revalidate_seconds: int = 86400

    @property
    def browser_header_value(self) -> str:
        return f"public, max-age={self.browser_max_age_seconds}"

    @property
    def cdn_header_value(self) -> str:
        return (
            f"public, max-age={self.shared_max_age_seconds}, "
            f"stale-while-revalidate={self.stale_while_revalidate_seconds}"
        )


@dataclass(frozen=True, slots=True)
class FeedConfig:
    slug: str
    title: str
    description: str
    tags: tuple[str, ...]
    normalized_tags: frozenset[str]
    sync_interval_hours: int
    max_items: int

    def fingerprint(self, publisher_name: str, base_url: str, language: str) -> str:
        payload = {
            "publisher_name": publisher_name,
            "base_url": base_url,
            "language": language,
            "slug": self.slug,
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "sync_interval_hours": self.sync_interval_hours,
            "max_items": self.max_items,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class AppConfig:
    publisher_name: str
    base_url: str
    language: str
    cache: CacheConfig
    feeds: tuple[FeedConfig, ...]

    def feed_by_slug(self, slug: str) -> FeedConfig | None:
        return next((feed for feed in self.feeds if feed.slug == slug), None)


def _required_string(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def _positive_int(value: Any, key: str, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigurationError(f"{context}.{key} must be a positive integer")
    return value


def load_config(source: str | bytes) -> AppConfig:
    try:
        raw = json.loads(source)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ConfigurationError("configuration must be valid JSON") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError("configuration root must be an object")

    publisher_name = _required_string(raw, "publisher_name", "config")
    base_url = _required_string(raw, "base_url", "config").rstrip("/")
    if not base_url.startswith("https://"):
        raise ConfigurationError("config.base_url must be an https URL")
    language = _required_string(raw, "language", "config")
    cache_raw = raw.get("cache", {})
    if not isinstance(cache_raw, dict):
        raise ConfigurationError("config.cache must be an object")
    cache = CacheConfig(
        browser_max_age_seconds=_positive_int(
            cache_raw.get("browser_max_age_seconds", 300),
            "browser_max_age_seconds",
            "config.cache",
        ),
        shared_max_age_seconds=_positive_int(
            cache_raw.get("shared_max_age_seconds", 3600),
            "shared_max_age_seconds",
            "config.cache",
        ),
        stale_while_revalidate_seconds=_positive_int(
            cache_raw.get("stale_while_revalidate_seconds", 86400),
            "stale_while_revalidate_seconds",
            "config.cache",
        ),
    )

    feeds_raw = raw.get("feeds")
    if not isinstance(feeds_raw, list) or not feeds_raw:
        raise ConfigurationError("config.feeds must be a non-empty array")

    feeds: list[FeedConfig] = []
    seen_slugs: set[str] = set()
    for index, item in enumerate(feeds_raw):
        context = f"config.feeds[{index}]"
        if not isinstance(item, dict):
            raise ConfigurationError(f"{context} must be an object")
        slug = _required_string(item, "slug", context)
        if not SLUG_PATTERN.fullmatch(slug):
            raise ConfigurationError(f"{context}.slug is invalid")
        if slug in seen_slugs:
            raise ConfigurationError(f"duplicate feed slug: {slug}")
        seen_slugs.add(slug)

        tags_raw = item.get("tags")
        if not isinstance(tags_raw, list) or not tags_raw:
            raise ConfigurationError(f"{context}.tags must be a non-empty array")
        tags: list[str] = []
        normalized_tags: set[str] = set()
        for tag in tags_raw:
            if not isinstance(tag, str) or not tag.strip():
                raise ConfigurationError(f"{context}.tags must contain non-empty strings")
            display_tag = tag.strip()
            normalized = display_tag.casefold()
            if normalized in normalized_tags:
                raise ConfigurationError(f"{context}.tags contains duplicate tag {display_tag!r}")
            tags.append(display_tag)
            normalized_tags.add(normalized)

        feeds.append(
            FeedConfig(
                slug=slug,
                title=_required_string(item, "title", context),
                description=_required_string(item, "description", context),
                tags=tuple(tags),
                normalized_tags=frozenset(normalized_tags),
                sync_interval_hours=_positive_int(
                    item.get("sync_interval_hours", 24),
                    "sync_interval_hours",
                    context,
                ),
                max_items=_positive_int(item.get("max_items", 100), "max_items", context),
            )
        )

    return AppConfig(
        publisher_name=publisher_name,
        base_url=base_url,
        language=language,
        cache=cache,
        feeds=tuple(feeds),
    )
