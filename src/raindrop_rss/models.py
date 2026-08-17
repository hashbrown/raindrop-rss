from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


class RaindropDataError(ValueError):
    """Raised when a Raindrop item cannot be normalized."""


def parse_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise RaindropDataError(f"{field} must be a timestamp string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RaindropDataError(f"{field} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class FeedItem:
    raindrop_id: int
    title: str
    url: str
    summary: str
    published: datetime
    updated: datetime
    categories: tuple[str, ...]


def normalize_raindrop(
    raw: dict[str, Any],
    matching_tags: frozenset[str],
    redacted_tags: frozenset[str] = frozenset(),
) -> FeedItem:
    try:
        raindrop_id = int(raw["_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RaindropDataError("_id must be an integer") from exc

    title = raw.get("title")
    url = raw.get("link")
    if not isinstance(title, str) or not title.strip():
        raise RaindropDataError("title must be a non-empty string")
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        raise RaindropDataError("link must be an HTTP URL")

    tags_raw = raw.get("tags", [])
    if not isinstance(tags_raw, list):
        raise RaindropDataError("tags must be an array")
    categories = tuple(
        tag.strip()
        for tag in tags_raw
        if (
            isinstance(tag, str)
            and tag.strip()
            and tag.strip().casefold() in matching_tags
            and tag.strip().casefold() not in redacted_tags
        )
    )

    note = raw.get("note") if isinstance(raw.get("note"), str) else ""
    excerpt = raw.get("excerpt") if isinstance(raw.get("excerpt"), str) else ""
    summary = note.strip() or excerpt.strip()
    published = parse_datetime(raw.get("created"), "created")
    updated_value = raw.get("lastUpdate") or raw.get("created")
    updated = parse_datetime(updated_value, "lastUpdate")

    return FeedItem(
        raindrop_id=raindrop_id,
        title=title.strip(),
        url=url,
        summary=summary,
        published=published,
        updated=updated,
        categories=categories,
    )


def select_feed_items(
    raw_items: list[dict[str, Any]],
    matching_tags: frozenset[str],
    max_items: int,
    redacted_tags: frozenset[str] = frozenset(),
) -> list[FeedItem]:
    selected: list[FeedItem] = []
    seen_ids: set[int] = set()
    for raw in raw_items:
        if raw.get("type") != "article":
            continue
        raw_tags = raw.get("tags", [])
        if not isinstance(raw_tags, list):
            continue
        normalized = {
            tag.strip().casefold() for tag in raw_tags if isinstance(tag, str) and tag.strip()
        }
        if not normalized.intersection(matching_tags):
            continue
        try:
            item = normalize_raindrop(raw, matching_tags, redacted_tags)
        except RaindropDataError:
            continue
        if item.raindrop_id in seen_ids:
            continue
        seen_ids.add(item.raindrop_id)
        selected.append(item)

    selected.sort(key=lambda item: (item.published, item.raindrop_id), reverse=True)
    return selected[:max_items]
