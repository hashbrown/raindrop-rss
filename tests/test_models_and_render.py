from __future__ import annotations

from xml.etree import ElementTree as ET

from conftest import NOW, raindrop_item

from raindrop_rss.models import normalize_raindrop, select_feed_items
from raindrop_rss.render import ATOM_NS, render_atom, render_rss


def test_selects_articles_by_any_tag_deduplicates_sorts_and_limits() -> None:
    items = [
        raindrop_item(1, tags=["other"]),
        raindrop_item(2, item_type="video", tags=["ai"]),
        raindrop_item(3, tags=["AI"], created="2026-08-14T00:00:00Z"),
        raindrop_item(4, tags=["machine-learning"], created="2026-08-16T00:00:00Z"),
        raindrop_item(4, tags=["ai"], created="2026-08-16T00:00:00Z"),
        raindrop_item(5, tags=["ai"], created="2026-08-15T00:00:00Z"),
    ]
    selected = select_feed_items(items, frozenset({"ai", "machine-learning"}), 2)
    assert [item.raindrop_id for item in selected] == [4, 5]
    assert selected[0].categories == ("machine-learning",)


def test_note_is_preferred_and_excerpt_is_fallback() -> None:
    tags = frozenset({"ai"})
    assert normalize_raindrop(raindrop_item(1), tags).summary == "A note"
    assert normalize_raindrop(raindrop_item(2, note=""), tags).summary == "An excerpt"


def test_redacted_tags_are_not_emitted_as_categories() -> None:
    items = select_feed_items(
        [raindrop_item(1, tags=["AI", "Automation"])],
        frozenset({"ai", "automation"}),
        100,
        frozenset({"automation"}),
    )

    assert items[0].categories == ("AI",)


def test_atom_contains_required_metadata_and_escapes_text(app_config) -> None:
    feed = app_config.feeds[0]
    raw = raindrop_item(7, tags=["ai"], note="A <note> & detail")
    items = select_feed_items([raw], feed.normalized_tags, feed.max_items)
    content = render_atom(app_config, feed, items, NOW)
    root = ET.fromstring(content)
    ns = {"a": ATOM_NS}

    assert root.tag == f"{{{ATOM_NS}}}feed"
    assert root.findtext("a:id", namespaces=ns) == "https://feeds.example.com/ai"
    assert root.findtext("a:author/a:name", namespaces=ns) == "Test Publisher"
    assert root.find("a:link[@rel='self']", ns).attrib["href"].endswith("/ai.atom")
    entry = root.find("a:entry", ns)
    assert entry is not None
    assert entry.findtext("a:id", namespaces=ns) == "tag:raindrop.io,2026:bookmark/7"
    assert entry.findtext("a:summary", namespaces=ns) == "A <note> & detail"
    assert entry.find("a:category", ns).attrib["term"] == "ai"
    assert b"A &lt;note&gt; &amp; detail" in content


def test_rss_contains_required_metadata_and_stable_guid(app_config) -> None:
    feed = app_config.feeds[0]
    items = select_feed_items([raindrop_item(9)], feed.normalized_tags, feed.max_items)
    content = render_rss(app_config, feed, items, NOW)
    root = ET.fromstring(content)
    channel = root.find("channel")

    assert root.attrib["version"] == "2.0"
    assert channel is not None
    assert channel.findtext("title") == "AI Feed"
    assert channel.findtext("language") == "en-US"
    assert channel.findtext("item/guid") == "raindrop:9"
    assert channel.find("item/guid").attrib["isPermaLink"] == "false"
    self_link = channel.find(f"{{{ATOM_NS}}}link")
    assert self_link is not None and self_link.attrib["href"].endswith("/ai.rss")


def test_rendering_is_deterministic(app_config) -> None:
    feed = app_config.feeds[0]
    items = select_feed_items([raindrop_item(1)], feed.normalized_tags, feed.max_items)
    assert render_atom(app_config, feed, items, NOW) == render_atom(
        app_config, feed, items, NOW
    )
    assert render_rss(app_config, feed, items, NOW) == render_rss(
        app_config, feed, items, NOW
    )
