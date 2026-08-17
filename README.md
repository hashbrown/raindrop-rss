# raindrop-rss

Publish Atom 1.0 and RSS 2.0 feeds from tagged article bookmarks in Raindrop.io.

The Cloudflare Python Worker synchronizes on an hourly cron, queries Raindrop by each feed's configured tags and article type, and keeps the latest configured number of matches (100 by default). It paginates only as far as needed to satisfy that limit, merges multi-tag results with OR semantics, and deduplicates them. Generated XML is stored as immutable R2 objects; KV stores only the active object pointers and synchronization status. Public feed requests never call Raindrop.

## Routes

- `/<slug>.atom` — canonical Atom 1.0 feed
- `/<slug>.rss` — RSS 2.0 compatibility feed
- `/health` — non-secret synchronization status; returns `200` when healthy and `503`
  when any feed is unavailable or its latest synchronization failed

The acceptance feed is configured at `/raindrop-test.atom` and `/raindrop-test.rss`. Its limit is 100, but it should contain exactly two articles because that is the current number of source articles tagged `rss`.

## Local development

Requirements: Python 3.13, [uv](https://docs.astral.sh/uv/), and a supported Node.js release. C3-generated Workers projects install Wrangler locally; this repository likewise pins Wrangler in `package-lock.json`, while `uv.lock` and `pylock.toml` pin the Python development and Worker runtimes.

```bash
npm ci
uv sync --locked
uv run ruff check .
uv run pytest
uv run python scripts/smoke_test.py
npx wrangler deploy --dry-run
```

When `config/feeds.json` changes, regenerate and verify its bundled Python representation:

```bash
uv run python scripts/generate_feed_config.py
uv run pytest tests/test_generated_config.py
```

To run the Worker locally, copy `.dev.vars.example` to `.dev.vars`, provide a Raindrop test token, and run:

```bash
npx wrangler dev --test-scheduled
```

Local KV and R2 bindings use Wrangler's local persistence and do not access production resources. Trigger the cron handler with:

```bash
curl "http://localhost:8787/cdn-cgi/handler/scheduled?format=json"
```

See [docs/OPERATIONS.md](docs/OPERATIONS.md) for Cloudflare setup, deployment, cache configuration, verification, and rollback.

## Local monitoring

The dependency-free monitor exits `0` when all feeds are healthy, `1` when the
service is degraded, and `2` when the check itself cannot be completed:

```bash
uv run python scripts/check_monitor.py
```

It can also query the saved Cloudflare Workers Observability error query over a
recent time window. See [docs/OPERATIONS.md](docs/OPERATIONS.md#local-monitoring)
for credentials, options, and automation examples.

## Configuration

`config/feeds.json` is authoritative. Each feed supports:

- `slug`, `title`, `description`, and one or more `tags`;
- `sync_interval_hours`, defaulting to 24;
- `max_items`, defaulting to the latest 100 matching articles.

Tag matching is case-insensitive and uses any configured tag. Filtering and deduplication happen before the per-feed item limit is applied.
