# raindrop-rss

Publish Atom 1.0 and RSS 2.0 feeds from tagged article bookmarks in Raindrop.io.
Each configured feed is available from the public custom domain
`https://feeds.alloneof.me`.

## Use the feeds

Add one of these URLs to an RSS reader, newsletter tool, or other feed consumer:

- `https://feeds.alloneof.me/<slug>.atom` — canonical Atom 1.0 output.
- `https://feeds.alloneof.me/<slug>.rss` — RSS 2.0 compatibility output.

The feed contains article bookmarks from Raindrop.io, not copied article
content. A bookmark's optional Notes field is emitted as the entry summary or
RSS description. Markdown is intentionally left as plain text for now; a future
web view can render it as Markdown.

`https://feeds.alloneof.me/health` is a non-secret status endpoint. It returns
`200` when every configured feed has a successful Atom/RSS publication and no
recorded synchronization error, and `503` when the service is degraded.

## Manage feeds

Feeds are managed in [`config/feeds.json`](config/feeds.json). There is no
runtime feed-administration endpoint. To add a feed, add an object to the
`feeds` array with:

- `slug`: the URL-safe feed name; it becomes `/<slug>.atom` and `/<slug>.rss`;
- `title` and `description`: feed metadata;
- `tags`: one or more Raindrop tags, matched case-insensitively with OR
  semantics;
- `sync_interval_hours`: optional, default `24`;
- `max_items`: optional, default `100`. For each configured tag, the sync
  fetches up to this many newest article candidates, combines the tag results,
  then filters, deduplicates, sorts, and applies the limit. This bounded
  retrieval deliberately avoids scanning an entire large Raindrop collection
  while still preserving the newest possible items for the feed.

For example:

```json
{
  "slug": "design",
  "title": "Design Bookmarks",
  "description": "Recent articles saved with design-related tags.",
  "tags": ["design", "ux"],
  "sync_interval_hours": 24,
  "max_items": 100
}
```

After editing the file, run the configuration generator and tests from the
repository root:

```bash
uv run python scripts/generate_feed_config.py
uv run pytest
```

The generator copies the canonical, version-controlled JSON into the Python
module bundled into the Worker; the application validates it when loaded. The
generated file is a deployment artifact; edit `config/feeds.json`, never
`src/raindrop_rss/embedded_config.py` directly.
Commit both files together through the normal review workflow. After the
deployment completes, the next hourly Cron evaluation synchronizes a new feed
immediately because its configuration has no current state. Verify the new
URL and `/health` before sharing it.

The acceptance feed is `raindrop-test`. It uses the `rss` tag and keeps
`max_items` at 100; it should contain exactly two articles because that is the
current number of matching source bookmarks, not because the feed is limited
to two.

## Project documentation

- [Development guide](docs/DEVELOPMENT.md): local setup, configuration
  generation, architecture, tests, and the release workflow.
- [Operations guide](docs/OPERATIONS.md): Cloudflare resources, secrets,
  deployment, monitoring, caching, recovery, and rollback.
