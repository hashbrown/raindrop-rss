from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_feed_config import render

ROOT = Path(__file__).resolve().parents[1]


def test_embedded_config_is_current() -> None:
    expected = render((ROOT / "config" / "feeds.json").read_text(encoding="utf-8"))
    actual = (ROOT / "src" / "raindrop_rss" / "embedded_config.py").read_text(
        encoding="utf-8"
    )
    assert actual == expected


def test_production_acceptance_feed_is_not_truncated_to_expected_count() -> None:
    config = json.loads((ROOT / "config" / "feeds.json").read_text(encoding="utf-8"))
    acceptance = next(feed for feed in config["feeds"] if feed["slug"] == "eng")
    assert acceptance["tags"] == ["rss-eng"]
    assert acceptance["max_items"] == 100
