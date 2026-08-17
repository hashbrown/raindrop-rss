"""Generate the Python-embedded feed configuration from config/feeds.json."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "config" / "feeds.json"
TARGET = ROOT / "src" / "raindrop_rss" / "embedded_config.py"


def render(source_text: str) -> str:
    parsed = json.loads(source_text)
    canonical = json.dumps(parsed, ensure_ascii=False, indent=2) + "\n"
    return (
        '"""Generated from config/feeds.json; do not edit by hand."""\n\n'
        f"FEED_CONFIG_JSON = {canonical!r}\n"
    )


def main() -> None:
    TARGET.write_text(render(SOURCE.read_text(encoding="utf-8")), encoding="utf-8")


if __name__ == "__main__":
    main()
