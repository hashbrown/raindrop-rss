# Development

This guide covers changing the Worker and its feed configuration. It assumes
the Cloudflare resources and deployment secrets already exist. For account,
DNS, deployment, monitoring, and recovery procedures, see
[Operations](OPERATIONS.md).

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Node.js with npm
- A Raindrop API token with read access for local real-data testing

Wrangler is a project-local npm dependency pinned in `package-lock.json`. The
Python Worker dependencies are pinned in `uv.lock` and `pylock.toml`.

Install from a clean checkout:

```bash
npm ci
uv sync --locked
```

## Configuration lifecycle

`config/feeds.json` is the authoritative feed configuration. It contains the
publisher metadata, cache policy, and feed definitions. The Worker cannot read
that file directly at runtime, so `scripts/generate_feed_config.py` embeds its
canonical JSON into `src/raindrop_rss/embedded_config.py` during the build.

Run the generator whenever `config/feeds.json` changes:

```bash
uv run python scripts/generate_feed_config.py
```

The generator is deterministic. It is deliberately a small script rather than
runtime logic so a deployment has one checked-in, reviewable configuration
artifact. Do not edit `embedded_config.py` by hand. The generated file should
be committed with the source configuration, and CI verifies that it is
up-to-date.

Adding a feed does not require a new Worker, KV namespace, R2 bucket, secret,
or DNS record. Add the feed definition, regenerate the embedded configuration,
run the checks, and deploy through the normal pull request workflow. A new or
changed configuration fingerprint causes the next scheduled evaluation to
sync that feed immediately. Production deployments also invoke an
authenticated, one-time sync after the Worker deploys.

## Local Worker

Copy the example variables file and provide a local token:

```bash
cp .dev.vars.example .dev.vars
```

Edit `.dev.vars` and replace the placeholder token. It is ignored by Git and
must never be committed.

Run the preview configuration locally. It uses Wrangler's local KV/R2
persistence by default; it does not access production storage unless a remote
flag is explicitly supplied:

```bash
npx wrangler dev --config wrangler.preview.jsonc --test-scheduled
```

Trigger the scheduled handler from another terminal:

```bash
curl "http://localhost:8787/cdn-cgi/handler/scheduled?format=json"
```

Then inspect the local routes, for example:

```bash
curl -i http://localhost:8787/raindrop-test.atom
curl -i http://localhost:8787/raindrop-test.rss
curl -i http://localhost:8787/health
```

The local scheduled run can call the real Raindrop API using `.dev.vars`. The
automated test suite uses fakes and does not require a token.

## Test and validation commands

Run the complete local checks before opening a pull request:

```bash
uv run python scripts/generate_feed_config.py
git diff -- src/raindrop_rss/embedded_config.py
uv run ruff check .
uv run pytest
uv run python scripts/smoke_test.py
uv run pywrangler deploy --dry-run
```

The generated-file diff is expected after changing feed configuration; review
it and commit it with `config/feeds.json`. CI regenerates the file from a clean
checkout and fails if the committed artifact is not current.

The tests cover configuration validation, any-tag matching, bounded
per-tag pagination, article filtering, deduplication, XML rendering, notes,
scheduling, R2-before-KV publication, conditional requests, cache headers,
and last-known-good failure behavior. The smoke test validates the cached
two-item Atom/RSS acceptance fixture without contacting Raindrop.

## Retrieval policy

`max_items` is both the feed size and the per-tag candidate bound. Raindrop
returns each tag search newest first, so each synchronization fetches at most
`max_items` article candidates for each configured tag. The Worker combines
those candidates, filters and deduplicates them, sorts them newest first, then
emits at most `max_items` items. This is intentional: the newest global
`max_items` results must be among the newest `max_items` results of at least
one matching tag, while the bound prevents a large collection from making a
scheduled Worker invocation unbounded.

## Source layout

- `config/feeds.json`: source configuration for all feeds.
- `scripts/generate_feed_config.py`: deterministic configuration bundler.
- `src/worker.py`: Cloudflare bindings and fetch/scheduled handlers.
- `src/raindrop_rss/`: framework-independent configuration, API, filtering,
  rendering, storage, and service logic.
- `tests/`: unit and smoke-support tests.
- `wrangler.jsonc`: production custom domain, bindings, Cron, and edge cache.
- `wrangler.preview.jsonc`: local/preview Worker settings.
- `.github/workflows/deploy.yml`: CI checks and production deployment on
  pushes to `main`.

## Release workflow

1. Change source code or `config/feeds.json`.
2. Regenerate `embedded_config.py` if configuration changed.
3. Run the complete validation commands.
4. Open and review a pull request.
5. Merge to `main` after CI passes.
6. GitHub Actions deploys with the production Wrangler configuration.
7. Verify `/health`, the changed feed XML, and cache behavior after rollout.

Keep operational changes separate from feed configuration changes when
possible. Never commit `.dev.vars`, API tokens, generated credentials, or
production storage data.
