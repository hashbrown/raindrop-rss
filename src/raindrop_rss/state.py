from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

STATE_VERSION = 1


@dataclass(frozen=True, slots=True)
class Representation:
    object_key: str
    content_hash: str
    content_type: str


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    atom_key: str
    rss_key: str
    published_at: str


@dataclass(frozen=True, slots=True)
class FeedState:
    version: int = STATE_VERSION
    config_fingerprint: str = ""
    atom: Representation | None = None
    rss: Representation | None = None
    last_successful_sync: str | None = None
    next_sync_at: str | None = None
    last_error: str | None = None
    last_error_at: str | None = None
    history: tuple[HistoryEntry, ...] = field(default_factory=tuple)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, source: str) -> FeedState:
        raw: dict[str, Any] = json.loads(source)
        if raw.get("version") != STATE_VERSION:
            raise ValueError("unsupported feed state version")

        def representation(name: str) -> Representation | None:
            value = raw.get(name)
            return Representation(**value) if isinstance(value, dict) else None

        history_raw = raw.get("history", [])
        history = tuple(
            HistoryEntry(**entry) for entry in history_raw if isinstance(entry, dict)
        )
        return cls(
            version=STATE_VERSION,
            config_fingerprint=str(raw.get("config_fingerprint", "")),
            atom=representation("atom"),
            rss=representation("rss"),
            last_successful_sync=raw.get("last_successful_sync"),
            next_sync_at=raw.get("next_sync_at"),
            last_error=raw.get("last_error"),
            last_error_at=raw.get("last_error_at"),
            history=history,
        )

    def is_due(self, now: datetime, fingerprint: str) -> bool:
        if self.config_fingerprint != fingerprint or not self.next_sync_at:
            return True
        try:
            return datetime.fromisoformat(self.next_sync_at.replace("Z", "+00:00")) <= now
        except ValueError:
            return True


def state_key(slug: str) -> str:
    return f"feed:{slug}:state"
