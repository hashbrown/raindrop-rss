#!/usr/bin/env python3
"""Check feed health and optionally query recent Cloudflare Worker errors."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

DEFAULT_HEALTH_URL = "https://feeds.alloneof.me/health"
DEFAULT_QUERY_ID = "mtjxpjd10furnciapv5y4g4n"

EXIT_OK = 0
EXIT_UNHEALTHY = 1
EXIT_CHECK_FAILED = 2


class MonitorError(RuntimeError):
    """The monitor could not complete a requested check."""


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _fetch_json(
    url: str,
    *,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    payload: Mapping[str, Any] | None = None,
    timeout: float = 15,
    accepted_statuses: frozenset[int] = frozenset({200}),
) -> tuple[int, dict[str, Any]]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MonitorError(f"unsupported URL: {url}")

    body = json.dumps(payload).encode() if payload is not None else None
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "raindrop-rss-monitor/0.1",
        **(headers or {}),
    }
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=request_headers, method=method)

    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            response_body = response.read()
    except HTTPError as exc:
        status = exc.code
        response_body = exc.read()
    except (TimeoutError, URLError) as exc:
        raise MonitorError(f"request failed for {url}: {exc}") from exc

    try:
        decoded = json.loads(response_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MonitorError(f"{url} returned invalid JSON (HTTP {status})") from exc
    if not isinstance(decoded, dict):
        raise MonitorError(f"{url} returned a non-object JSON response")

    if status not in accepted_statuses:
        api_errors = decoded.get("errors")
        detail = json.dumps(api_errors, separators=(",", ":")) if api_errors else ""
        suffix = f": {detail}" if detail else ""
        raise MonitorError(f"{url} returned HTTP {status}{suffix}")
    return status, decoded


def health_issues(payload: Mapping[str, Any]) -> list[str]:
    feeds = payload.get("feeds")
    if not isinstance(feeds, list) or not feeds:
        return ["health response contains no feeds"]

    issues: list[str] = []
    for index, feed in enumerate(feeds):
        if not isinstance(feed, dict):
            issues.append(f"feed entry {index} is invalid")
            continue
        slug = str(feed.get("slug") or f"feed-{index}")
        if not feed.get("available"):
            issues.append(f"{slug}: feed is unavailable")
        if feed.get("last_error"):
            occurred = feed.get("last_error_at") or "unknown time"
            issues.append(f"{slug}: {feed['last_error']} at {occurred}")

    if payload.get("status") != "ok" and not issues:
        issues.append(f"endpoint reported status {payload.get('status')!r}")
    return issues


def check_health(url: str, timeout: float) -> tuple[int, dict[str, Any], list[str]]:
    status, payload = _fetch_json(
        url,
        timeout=timeout,
        accepted_statuses=frozenset({200, 503}),
    )
    issues = health_issues(payload)
    if status == 503 and not issues:
        issues.append("health endpoint returned HTTP 503")
    return status, payload, issues


def query_cloudflare_errors(
    *,
    account_id: str,
    api_token: str,
    query_id: str,
    minutes: int,
    timeout: float,
    now_ms: int | None = None,
) -> tuple[int, list[dict[str, Any]], int, int]:
    end_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    start_ms = end_ms - minutes * 60 * 1000
    url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        f"{account_id}/workers/observability/telemetry/query"
    )
    _, payload = _fetch_json(
        url,
        method="POST",
        headers={"Authorization": f"Bearer {api_token}"},
        payload={
            "queryId": query_id,
            "timeframe": {"from": start_ms, "to": end_ms},
        },
        timeout=timeout,
    )
    if payload.get("success") is not True:
        raise MonitorError(f"Cloudflare query failed: {payload.get('errors')!r}")

    result = payload.get("result")
    event_block = result.get("events") if isinstance(result, dict) else None
    if not isinstance(event_block, dict):
        raise MonitorError("Cloudflare query did not return an events result")
    events = event_block.get("events", [])
    if not isinstance(events, list):
        raise MonitorError("Cloudflare query returned an invalid events list")
    count = event_block.get("count", len(events))
    if not isinstance(count, int):
        raise MonitorError("Cloudflare query returned an invalid event count")
    return count, [event for event in events if isinstance(event, dict)], start_ms, end_ms


def summarize_log_event(event: Mapping[str, Any]) -> str:
    metadata = event.get("$metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    workers = event.get("$workers")
    workers = workers if isinstance(workers, dict) else {}

    timestamp = event.get("timestamp")
    if isinstance(timestamp, int | float):
        occurred = datetime.fromtimestamp(timestamp / 1000, UTC).isoformat()
    else:
        occurred = "unknown time"
    message = metadata.get("error") or metadata.get("message") or event.get("source")
    if isinstance(message, dict):
        message = json.dumps(message, sort_keys=True, separators=(",", ":"))
    message = str(message or "Worker error")
    script = workers.get("scriptName") or metadata.get("service") or "unknown worker"
    outcome = workers.get("outcome")
    outcome_suffix = f" ({outcome})" if outcome else ""
    return f"{occurred} {script}{outcome_suffix}: {message[:500]}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--health-url",
        default=os.environ.get("RAINDROP_RSS_HEALTH_URL", DEFAULT_HEALTH_URL),
        help="health endpoint URL (default: %(default)s)",
    )
    parser.add_argument(
        "--logs-minutes",
        type=_positive_integer,
        help="also fail if the saved Cloudflare query finds errors in this recent window",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_integer,
        default=15,
        help="per-request timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit one machine-readable JSON result",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report: dict[str, Any] = {"health_url": args.health_url}

    try:
        health_status, health_payload, issues = check_health(args.health_url, args.timeout)
        report.update(
            {
                "health_http_status": health_status,
                "health": health_payload,
                "health_issues": issues,
            }
        )

        log_count = 0
        log_events: list[dict[str, Any]] = []
        if args.logs_minutes is not None:
            account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
            api_token = os.environ.get("CLOUDFLARE_API_TOKEN")
            query_id = os.environ.get("CLOUDFLARE_OBSERVABILITY_QUERY_ID", DEFAULT_QUERY_ID)
            missing = [
                name
                for name, value in (
                    ("CLOUDFLARE_ACCOUNT_ID", account_id),
                    ("CLOUDFLARE_API_TOKEN", api_token),
                )
                if not value
            ]
            if missing:
                raise MonitorError(
                    "--logs-minutes requires " + " and ".join(missing) + " in the environment"
                )
            log_count, log_events, start_ms, end_ms = query_cloudflare_errors(
                account_id=account_id,
                api_token=api_token,
                query_id=query_id,
                minutes=args.logs_minutes,
                timeout=args.timeout,
            )
            report["cloudflare_logs"] = {
                "query_id": query_id,
                "from": datetime.fromtimestamp(start_ms / 1000, UTC).isoformat(),
                "to": datetime.fromtimestamp(end_ms / 1000, UTC).isoformat(),
                "count": log_count,
                "events": log_events,
            }

        unhealthy = bool(issues) or log_count > 0
        report["status"] = "degraded" if unhealthy else "ok"
        if args.json:
            print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        else:
            if issues:
                print("DEGRADED: feed health check failed")
                for issue in issues:
                    print(f"- {issue}")
            else:
                feed_count = len(health_payload["feeds"])
                print(f"OK: {feed_count} feed(s) are available with no current sync error")
            if args.logs_minutes is not None:
                print(f"Cloudflare errors in the last {args.logs_minutes} minute(s): {log_count}")
                for event in log_events:
                    print(f"- {summarize_log_event(event)}")
        return EXIT_UNHEALTHY if unhealthy else EXIT_OK
    except MonitorError as exc:
        report.update({"status": "check_failed", "error": str(exc)})
        if args.json:
            print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        else:
            print(f"CHECK FAILED: {exc}", file=sys.stderr)
        return EXIT_CHECK_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
