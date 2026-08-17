# Operations

This guide covers operating an already-developed deployment: Cloudflare
resources, secrets, DNS/custom domains, releases, health checks, monitoring,
cache verification, recovery, and rollback. To add feeds or change the Worker,
see [Development](DEVELOPMENT.md) and the feed-management section in the
[README](../README.md).

## Cloudflare resources

Authenticate Wrangler first. R2 must also be enabled for the account through
**Storage & databases → R2 → Overview** in the Cloudflare dashboard. Enabling R2
is a subscription checkout: included monthly usage can make the amount due $0,
but usage above those allowances is billable. Review and accept that subscription
before creating the production stores once:

```bash
npx wrangler login
npx wrangler kv namespace create FEED_STATE
npx wrangler r2 bucket create raindrop-rss-feeds
```

Replace the all-zero KV namespace ID in `wrangler.jsonc` with the ID returned by the first command. The bucket uses R2 Standard storage. Keep the binding names `FEED_STATE` and `FEED_XML`; the Worker source depends on them.

The deployment API token should be restricted to the target Cloudflare account and the `alloneof.me` zone. It needs Worker script, Workers KV, R2, route/custom-domain, and cache-rule permissions required by the setup. Do not use a Global API Key.

## Secrets

Create a Raindrop test token with read access and store it as a Worker secret:

```bash
npx wrangler secret put RAINDROP_API_TOKEN
```

For GitHub Actions, create the Cloudflare API token from **My Profile → API
Tokens → Create Token** using the Workers edit permissions, scoped to this
Cloudflare account and the `alloneof.me` zone. Store the token value as the
`CLOUDFLARE_API_TOKEN` secret in the GitHub `production` environment. Do not
put the token in `.dev.vars`, the repository, or a command-line argument. The
Cloudflare token used for this deployment is named
`AllOneOfMe-Feeds_Workers-Edit`.

For GitHub Actions, configure these production-environment values:

- `CLOUDFLARE_API_TOKEN`
- `RAINDROP_API_TOKEN`

Configure `CLOUDFLARE_ACCOUNT_ID` as a GitHub Actions **variable**, not a
secret, under **Repository Settings → Environments → production → Variables**.
The workflow reads it from `${{ vars.CLOUDFLARE_ACCOUNT_ID }}`. Find the value
in the Cloudflare dashboard account URL or the account details panel; it is a
32-character account identifier, not the zone ID.

The Raindrop token must never appear in `wrangler.jsonc`, `config/feeds.json`, logs, fixtures, or committed `.dev.vars` files.

## Custom domain and edge cache

The `routes` entry in `wrangler.jsonc` attaches the Worker custom domain `feeds.alloneof.me`. The zone must already be active in the same Cloudflare account. Verify the custom-domain status in **Workers & Pages → raindrop-rss → Settings → Domains & Routes** after the first deployment.

Production `wrangler.jsonc` enables Workers Caching so Cloudflare checks the
edge cache before invoking the Worker. Feed responses use `Cache-Control` for
the five-minute browser TTL and `CDN-Cache-Control` for the one-hour edge TTL
plus the 24-hour stale-while-revalidate window. `/health` returns `no-store`.

The existing zone Cache Rule may remain as a secondary eligibility rule. It
matches:

```text
http.host eq "feeds.alloneof.me" and
(ends_with(http.request.uri.path, ".atom") or ends_with(http.request.uri.path, ".rss"))
```

Set cache eligibility to eligible/cache everything and respect the origin
cache-control TTLs. Do not cache `/health`. Workers Caching, rather than the
zone rule alone, is what lets a cache hit bypass Worker execution and R2.

## Deployment

Before deploying:

```bash
npm ci
uv sync --locked
uv run python scripts/generate_feed_config.py
uv run ruff check .
uv run pytest
uv run python scripts/smoke_test.py
uv run pywrangler deploy --dry-run
```

Deploy manually with `uv run pywrangler deploy`, or merge to `main` after configuring the GitHub secrets. The workflow tests before deployment and updates `RAINDROP_API_TOKEN` as a Worker secret without committing it. `pywrangler` synchronizes the Python Worker package bundle before invoking Wrangler.

Feed additions and configuration changes should follow the development
workflow. Do not edit KV state or R2 feed objects by hand as part of a normal
release; the next scheduled synchronization publishes the new immutable
objects and updates the KV pointers.

Cron runs hourly. A feed synchronizes immediately when it has no state or its configuration fingerprint changes; otherwise its own `sync_interval_hours` controls when it is due. A failed sync retains the previous object pointers and remains due for the next hourly retry. Each sync deliberately bounds Raindrop retrieval to the newest `max_items` candidates per configured tag before combining, deduplicating, and limiting the feed; see the [retrieval policy](DEVELOPMENT.md#retrieval-policy) for why this retains the newest possible feed items without unbounded collection scans.

## First-deployment verification

After the first scheduled event completes:

```bash
curl -fsS https://feeds.alloneof.me/health
curl -fsS https://feeds.alloneof.me/raindrop-test.atom -o /tmp/raindrop-test.atom
curl -fsS https://feeds.alloneof.me/raindrop-test.rss -o /tmp/raindrop-test.rss
```

Validate both XML documents and confirm exactly two Atom `entry` elements and two RSS `channel/item` elements. Their links must be the two Raindrop articles carrying the `rss` tag. The configured `max_items` is 100, so this expected count must come from source filtering rather than truncation.

Check caching twice from the same location:

```bash
curl -sSI https://feeds.alloneof.me/raindrop-test.atom
curl -sSI https://feeds.alloneof.me/raindrop-test.atom
```

The second response should report `CF-Cache-Status: HIT`, the expected `ETag`, and cache-control policy. A matching `If-None-Match` request should return `304`. Use Worker observability while testing to confirm a cache hit does not execute the Worker; public feed requests must never make Raindrop API calls.

## Local monitoring

`GET /health` is the authoritative current-state check. It returns `200` with
`"status": "ok"` only when every configured feed has published Atom and RSS
representations and has no unresolved synchronization error. It returns `503`
with `"status": "degraded"` otherwise. A successful later synchronization clears
the stored error.

Run the local monitor without Cloudflare credentials:

```bash
uv run python scripts/check_monitor.py
```

Exit codes are intended for cron, launchd, or another scheduler:

- `0`: every feed is currently healthy and no requested historical errors were found;
- `1`: current feed health is degraded or the requested log window contains errors;
- `2`: the monitor could not complete because of configuration, network, or API failure.

For additional diagnostics, the script can run the saved **raindrop-rss invocation
failures** Workers Observability query. Create a restricted API token with the
`Workers Observability Write` permission currently required by Cloudflare's query
endpoint, then provide the token and account ID through the environment. Do not
put the token in the repository or pass it as a command-line argument:

```bash
export CLOUDFLARE_ACCOUNT_ID=your-account-id
read -rs CLOUDFLARE_API_TOKEN
export CLOUDFLARE_API_TOKEN
uv run python scripts/check_monitor.py --logs-minutes 70
unset CLOUDFLARE_API_TOKEN
```

The project saved-query ID defaults to `mtjxpjd10furnciapv5y4g4n`. Override it
with `CLOUDFLARE_OBSERVABILITY_QUERY_ID` if the query is recreated. Add `--json`
for machine-readable output. The historical query is optional: `/health` catches
handled application-level synchronization failures without any authenticated API
access, while Observability adds uncaught Worker/platform errors from the selected
window. `wrangler tail` is useful for interactive live debugging but cannot poll
historical logs.

The scheduled handler deliberately raises after it has safely recorded any feed
failure in KV. This marks the Cron invocation as failed in Workers Observability;
the last-known-good R2 feed remains available and the next Cron run retries the
sync.

## Retention, recovery, and rollback

Each feed state retains pointers to the active representation pair and two prior pairs. Older immutable objects are deleted only after the new Atom and RSS objects have both been uploaded and the KV state pointer has been updated. A failed upload cannot replace the last-known-good pointer.

For a feed-data rollback, read `feed:<slug>:state` from KV, select one history entry, and update the active Atom/RSS object keys and hashes only after confirming both objects exist in R2. Save the original state JSON before writing the replacement. For a code rollback, use `npx wrangler versions list` followed by `npx wrangler rollback <VERSION_ID>`.

If an R2 object referenced by KV is missing, the route returns `503`; restore a valid pair from state history. If KV state is lost, wait for or trigger the next scheduled synchronization to republish it from Raindrop.
