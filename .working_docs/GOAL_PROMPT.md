# Goal: Deliver the Raindrop Feed Worker

Implement the production-ready `raindrop-rss` application in `/Users/barmstrong/dev/my_projects/raindrop-rss`.

`IMPLEMENTATION_PLAN.md` is the authoritative product and technical specification. Read it before making changes, implement every stated requirement, and do not duplicate or weaken it. Where the plan explicitly leaves a decision open, use its proposed default when it is safe and reversible; ask the user only when a choice materially changes public behavior, cost, or an external resource.

## Required outcome

Deliver a maintainable Python Cloudflare Worker, managed with `uv`, that produces the configured Raindrop article feeds and serves the planned Atom and RSS representations from the custom domain. Follow the plan's R2-first publication model, KV state-pointer model, scheduled synchronization, cache behavior, and last-known-good-feed guarantee. The project must be usable by another developer from a clean checkout and safe to deploy without exposing credentials.

## Execution rules

- Work through the plan's phases in order: scaffold, pure logic, Worker integration, tests/local verification, and deployment automation/documentation.
- Keep generated feed documents and synchronization state separate exactly as specified. Public feed requests must not contact Raindrop.
- Use current official Cloudflare and Raindrop documentation when an API, limit, configuration field, or deployment behavior needs verification.
- Keep secrets out of the repository, examples, logs, and test fixtures. Use safe placeholders in committed configuration and document the required secret names.
- Preserve unrelated user changes. Do not replace the plan with implementation assumptions.
- Make no irreversible external changes beyond the scope of deployment without confirmation. If deployment prerequisites are unavailable, finish all locally verifiable work and report the exact missing prerequisite; never claim a deployment or edge-cache verification that did not occur.
- Maintain a log of actions and decisions you've made in .working_docs/implementation_log.md

## Evidence required before completion

Provide concise, command-backed evidence that:

- a clean checkout can install and run using the documented `uv` workflow;
- automated tests cover the plan's filtering, normalization, Atom/RSS rendering, state/publication ordering, routing, cache headers, and failure-preservation cases, and pass;
- a local smoke test serves valid Atom 1.0 and RSS 2.0 output without calling Raindrop on a feed request;
- Wrangler configuration declares the required Worker, R2, KV, cron, and custom-domain settings, while secrets remain external;
- GitHub Actions tests before deploying from `main`;
- setup and operations documentation covers Cloudflare resources, secrets, DNS/custom domain, cache rule, object retention, first deployment, and rollback/recovery behavior;
- if Cloudflare credentials and resources are available, the deployed feed and edge-cache behavior are verified. Otherwise, list the exact commands or account actions still required.
- the configured `raindrop-test` feed has `max_items` set above the expected result count, selects all Raindrop articles tagged `rss` through complete API pagination, and its deployed Atom and RSS representations each contain exactly two articles because exactly two source articles currently carry that tag.

Do not mark this goal complete until the required outcome and all locally verifiable evidence are satisfied. State any remaining external blocker explicitly and honestly.
