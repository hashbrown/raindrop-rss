from __future__ import annotations

from datetime import UTC, datetime
from email.utils import format_datetime
from xml.etree import ElementTree as ET

from .config import AppConfig, FeedConfig
from .models import FeedItem

ATOM_NS = "http://www.w3.org/2005/Atom"
ET.register_namespace("", ATOM_NS)
ET.register_namespace("atom", ATOM_NS)


def _atom(name: str) -> str:
    return f"{{{ATOM_NS}}}{name}"


def _isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _feed_updated(items: list[FeedItem], generated_at: datetime) -> datetime:
    return max((item.updated for item in items), default=generated_at).astimezone(UTC)


def render_atom(
    app: AppConfig,
    feed: FeedConfig,
    items: list[FeedItem],
    generated_at: datetime,
) -> bytes:
    feed_url = f"{app.base_url}/{feed.slug}.atom"
    root = ET.Element(_atom("feed"), {"xml:lang": app.language})
    ET.SubElement(root, _atom("id")).text = f"{app.base_url}/{feed.slug}"
    ET.SubElement(root, _atom("title"), {"type": "text"}).text = feed.title
    ET.SubElement(root, _atom("subtitle"), {"type": "text"}).text = feed.description
    ET.SubElement(root, _atom("updated")).text = _isoformat(_feed_updated(items, generated_at))
    author = ET.SubElement(root, _atom("author"))
    ET.SubElement(author, _atom("name")).text = app.publisher_name
    ET.SubElement(
        root,
        _atom("link"),
        {"rel": "self", "type": "application/atom+xml", "href": feed_url},
    )

    for item in items:
        entry = ET.SubElement(root, _atom("entry"))
        ET.SubElement(entry, _atom("id")).text = (
            f"tag:raindrop.io,{item.published.year}:bookmark/{item.raindrop_id}"
        )
        ET.SubElement(entry, _atom("title"), {"type": "text"}).text = item.title
        ET.SubElement(
            entry,
            _atom("link"),
            {"rel": "alternate", "type": "text/html", "href": item.url},
        )
        ET.SubElement(entry, _atom("published")).text = _isoformat(item.published)
        ET.SubElement(entry, _atom("updated")).text = _isoformat(item.updated)
        ET.SubElement(entry, _atom("summary"), {"type": "text"}).text = item.summary
        for category in item.categories:
            ET.SubElement(entry, _atom("category"), {"term": category})

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def render_rss(
    app: AppConfig,
    feed: FeedConfig,
    items: list[FeedItem],
    generated_at: datetime,
) -> bytes:
    feed_url = f"{app.base_url}/{feed.slug}.rss"
    root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = feed.title
    ET.SubElement(channel, "link").text = app.base_url
    ET.SubElement(channel, "description").text = feed.description
    ET.SubElement(channel, "language").text = app.language
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(
        _feed_updated(items, generated_at), usegmt=True
    )
    ET.SubElement(channel, "generator").text = "raindrop-rss"
    ET.SubElement(
        channel,
        _atom("link"),
        {"rel": "self", "type": "application/rss+xml", "href": feed_url},
    )

    for feed_item in items:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = feed_item.title
        ET.SubElement(item, "link").text = feed_item.url
        guid = ET.SubElement(item, "guid", {"isPermaLink": "false"})
        guid.text = f"raindrop:{feed_item.raindrop_id}"
        ET.SubElement(item, "pubDate").text = format_datetime(feed_item.published, usegmt=True)
        ET.SubElement(item, "description").text = feed_item.summary
        for category in feed_item.categories:
            ET.SubElement(item, "category").text = category

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
