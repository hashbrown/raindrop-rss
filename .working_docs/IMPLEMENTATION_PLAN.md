# Raindrop Feed Implementation Plan

## Objective

Publish one or more public syndication feeds at `feeds.alloneof.me`, with each feed built from article bookmarks in a Raindrop.io account. Each feed has a slug, title, one or more tag strings, an optional synchronization interval defaulting to 24 hours, and an optional maximum item count defaulting to the latest 100 matching items. A bookmark belongs in a feed when its Raindrop tags contain at least one configured tag. Atom 1.0 is the canonical representation and RSS 2.0 is published for compatibility.

## Architecture

- **Runtime:** Cloudflare Python Worker deployed with the project-local Wrangler dependency.
- **Project management:** `uv`, with committed `pyproject.toml` and `uv.lock`.
- **Feed configuration:** Version-controlled `config/feeds.json`, containing a publisher name plus each feed's slug, title, description, tags, sync interval, and maximum item count.
- **Feed XML:** Cloudflare R2 is the durable origin for generated Atom and RSS documents. Each successful sync writes immutable, content-addressed objects for both representations, such as `feeds/<slug>/atom/<sha256>.atom` and `feeds/<slug>/rss/<sha256>.rss`.
- **Feed state:** Cloudflare KV stores only small per-feed state: the current R2 object key and content hash for each representation, last-successful-sync, next-due time, and most recent error metadata. It never stores feed XML.
- **Scheduling:** One Cloudflare Cron Trigger runs regularly; the Worker evaluates each feed's own `next_sync_at`.
- **Raindrop access:** Server-side API token stored as a Cloudflare Worker secret. Never commit or expose it.
- **Public delivery:** `/<feed-slug>.atom` serves the canonical Atom 1.0 representation and `/<feed-slug>.rss` serves RSS 2.0 compatibility output. Each route resolves its current immutable R2 object from KV and returns it with an ETag and explicit browser and edge-cache headers. Cloudflare Workers Caching is enabled for the production Worker; on a cache hit the Worker and R2 are bypassed. A feed request never calls Raindrop.
- **Deployment:** GitHub Actions runs tests and deploys with Wrangler on pushes to `main`, so merged PRs create deployments.
- **Domain:** Configure `feeds.alloneof.me` as the Worker custom domain.

## Feed behavior

1. Validate feed configuration at startup/deployment.
2. On each scheduled run, identify feeds whose `next_sync_at` is due.
3. Query Raindrop's all-bookmarks API with pagination as needed.
4. Include only items of type `article` whose tags contain at least one configured tag.
5. Fetch all Raindrop API pages needed to identify matches, sort matching items newest first, and apply that feed's `max_items` limit (default 100) after filtering and deduplication.
6. Normalize selected bookmarks once, then deterministically render two representations from that model:
   - **Atom 1.0 (canonical):** a permanent feed ID, `title`, `subtitle`, `updated`, feed-level author name, a `rel="self"` link to the `.atom` route, and entries with permanent Raindrop-based IDs, original-article links, `published`, `updated`, a text summary, and matching tags as categories.
   - **RSS 2.0 (compatibility):** channel title, link, description, language, last-build date, a self-reference, and items with stable non-permalink GUIDs based on Raindrop IDs, title, original URL, excerpt/note description, creation date as `pubDate`, and matching tags as categories.
   Use the bookmark modification timestamp for Atom `updated` when Raindrop supplies one; otherwise use its creation timestamp. Never claim that copied article content was authored by the feed publisher.
7. Upload each XML representation to R2 under a new immutable content-addressed key, using `application/atom+xml; charset=utf-8` or `application/rss+xml; charset=utf-8` metadata and a strong ETag based on that representation's content hash.
8. Only after both R2 uploads succeed, update the KV state pointers and successful-sync metadata. This publication order guarantees that a pointer never references an unavailable object; short-lived KV propagation delays can only serve the prior complete feed.
9. On failure, preserve the last successful R2 object and KV pointer, and record the failure without advancing successful-sync state.
10. Return the representation-specific content type, ETag, cache headers, 404 for unknown slugs, and a clear unavailable response for feeds that have never synced successfully.

### Storage and edge-cache policy

- R2 is the authoritative, durable XML store; it is appropriate for an object that can outgrow a KV value or is naturally treated as a file. R2 Standard storage is used because current feeds are read frequently.
- KV is intentionally limited to state/pointers. A KV value is currently limited to 25 MiB, and KV is eventually consistent, with cross-location visibility potentially taking 60 seconds or longer. A normal RSS feed will usually fit, but XML size should not define the design.
- Objects are immutable. The state records the active object key, which gives every public read a complete feed version and avoids a partially published overwrite. Retain the active object plus a small, documented number of earlier versions for rollback/debugging; remove superseded versions with an R2 lifecycle rule or controlled cleanup.
- Deliver browser freshness through `Cache-Control` and the longer edge TTL plus `stale-while-revalidate` through `CDN-Cache-Control`; send each representation's object hash as the ETag and honor conditional requests. Keeping `s-maxage` out of the response allows Cloudflare's edge `stale-while-revalidate` behavior to operate. The final TTL is a product decision: shorter values publish a newly synced feed sooner, while longer values reduce Worker/R2 reads.
- Enable Workers Caching in the production Wrangler configuration. A zone-level Cache Rule may remain as a defense-in-depth eligibility rule, but it is not sufficient by itself for Worker-generated responses. Do not treat the Workers Cache API as the primary global cache: it is data-center-local and evictable. The test/deployment checklist must prove a cache hit does not invoke the Worker or read R2.

## Configuration example

```json
{
  "publisher_name": "All One Of Me",
  "feeds": [
    {
      "slug": "ai",
      "title": "AI Bookmarks",
      "description": "Articles saved with AI-related tags.",
      "tags": ["ai", "machine-learning"],
      "sync_interval_hours": 24,
      "max_items": 100
    }
  ]
}
```

Reject a missing publisher name, duplicate slugs, empty tag lists, invalid slugs, non-positive intervals, non-positive maximum item counts, and duplicate tags after normalization. Configuration changes go through the normal pull-request workflow.

The production acceptance configuration includes a feed with slug `raindrop-test`, tag `rss`, and `max_items` set to 100, safely above the expected result count. Its deployed Atom and RSS representations must each contain exactly two articles because exactly two source articles currently carry the `rss` tag. This verifies that the expected count comes from complete Raindrop pagination and filtering, not truncation by `max_items`.

## Implementation phases

### 1. Scaffold

Add `pyproject.toml`, `uv.lock`, source/test layout, project scripts, Wrangler configuration, R2 and KV bindings, Cron Trigger, and an example configuration with no secrets.

### 2. Pure application logic

Implement configuration validation, Raindrop response normalization, article and any-tag filtering, a shared normalized feed model, and deterministic Atom 1.0 and RSS 2.0 XML generation. Keep these components independent of Cloudflare bindings for straightforward unit testing.

### 3. Worker handlers

Implement the `.atom` and `.rss` feed routes, a minimal non-secret health/status endpoint, scheduled synchronization, dual-representation R2 publication, KV state-pointer handling, pagination, idempotence, cache/conditional-response headers, and last-good-feed preservation.

### 4. Tests and local verification

Test configuration validation, article-only filtering, any-tag matching, pagination, duplicate handling, XML escaping, Atom and RSS required metadata, permanent Atom IDs and RSS GUIDs, UTC dates, `.atom`/`.rss` routing, due/not-due scheduling, R2-before-KV publication ordering, conditional requests, cache headers, and failed-sync preservation. Use mocked Raindrop responses plus in-memory KV and R2 test doubles. Run formatting/linting if configured, unit tests, feed validation, and a local Worker smoke test.

### 5. Deployment

Document KV namespace and R2 bucket creation, a narrowly scoped Cloudflare API token, GitHub Actions secrets, Raindrop token setup, the `feeds.alloneof.me` custom domain/DNS setup, Workers Caching, object retention, and first deployment. The workflow must run tests before Wrangler deployment and deploy only from `main`.

## Verification criteria

- A clean checkout installs and runs with `uv`.
- Tests pass with mocked Raindrop data.
- Local development serves valid Atom 1.0 and RSS 2.0 representations of a cached feed.
- Wrangler declares the R2 and KV bindings and scheduled handler.
- GitHub Actions deploys after successful pushes to `main`.
- No credentials are committed.
- Cloudflare, DNS, secret, and first-deployment instructions are documented.
- A deployed custom-domain feed is served from the edge cache on a cache hit, never invokes Raindrop on a feed request, and reads immutable Atom or RSS XML from R2 only on an edge-cache miss.
- The deployed `raindrop-test.atom` and `raindrop-test.rss` feeds each contain exactly the two source articles selected by the `rss` tag while `max_items` remains higher than two.

## Decisions to confirm during implementation

- Cron frequency: hourly is likely sufficient for a 24-hour default; 15 minutes gives finer custom intervals.
- Whether descriptions include notes, excerpts, or both.
- Whether a configuration change triggers an immediate sync or waits for the next due time.
- Shared-cache TTL and stale-while-revalidate window. Start with `s-maxage=3600` and `stale-while-revalidate=86400` unless faster publication is required.
- Number and retention period of superseded R2 feed objects. Start by retaining the active version plus the two most recent previous versions for 30 days.
- Whether to provide a legacy `/<slug>.xml` redirect to canonical `/<slug>.atom`. The initial implementation should publish only explicit `.atom` and `.rss` routes.
