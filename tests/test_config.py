from __future__ import annotations

import json

import pytest
from conftest import config_json

from raindrop_rss.config import ConfigurationError, load_config


def test_load_config_defaults_per_feed_max_items() -> None:
    raw = json.loads(config_json())
    del raw["feeds"][0]["max_items"]
    config = load_config(json.dumps(raw))
    assert config.feeds[0].max_items == 100
    assert config.cache.browser_header_value == "public, max-age=300"
    assert config.cache.cdn_header_value == (
        "public, max-age=3600, stale-while-revalidate=86400"
    )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw.update(publisher_name=""), "publisher_name"),
        (lambda raw: raw["feeds"][0].update(slug="Bad Slug"), "slug"),
        (lambda raw: raw["feeds"][0].update(tags=[]), "tags"),
        (lambda raw: raw["feeds"][0].update(tags=["AI", "ai"]), "duplicate tag"),
        (lambda raw: raw["feeds"][0].update(sync_interval_hours=0), "sync_interval_hours"),
        (lambda raw: raw["feeds"][0].update(max_items=0), "max_items"),
        (lambda raw: raw["feeds"].append(dict(raw["feeds"][0])), "duplicate feed slug"),
    ],
)
def test_rejects_invalid_configuration(mutate, message: str) -> None:
    raw = json.loads(config_json())
    mutate(raw)
    with pytest.raises(ConfigurationError, match=message):
        load_config(json.dumps(raw))


def test_config_fingerprint_changes_with_feed_limit() -> None:
    first = load_config(config_json(max_items=100))
    second = load_config(config_json(max_items=25))
    feed1 = first.feeds[0]
    feed2 = second.feeds[0]
    assert feed1.fingerprint(first.publisher_name, first.base_url, first.language) != (
        feed2.fingerprint(second.publisher_name, second.base_url, second.language)
    )
