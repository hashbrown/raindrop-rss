from __future__ import annotations

from scripts.check_monitor import health_issues, query_cloudflare_errors, summarize_log_event


def test_health_issues_accepts_available_error_free_feeds() -> None:
    payload = {
        "status": "ok",
        "feeds": [{"slug": "rss", "available": True, "last_error": None}],
    }

    assert health_issues(payload) == []


def test_health_issues_describes_unavailable_and_failed_feeds() -> None:
    payload = {
        "status": "degraded",
        "feeds": [
            {
                "slug": "rss",
                "available": False,
                "last_error": "Raindrop API returned HTTP 503",
                "last_error_at": "2026-08-16T12:00:00Z",
            }
        ],
    }

    assert health_issues(payload) == [
        "rss: feed is unavailable",
        "rss: Raindrop API returned HTTP 503 at 2026-08-16T12:00:00Z",
    ]


def test_query_cloudflare_errors_uses_saved_query_and_time_window(monkeypatch) -> None:
    captured = {}

    def fake_fetch_json(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return 200, {
            "success": True,
            "result": {
                "events": {
                    "count": 1,
                    "events": [
                        {
                            "timestamp": 1_723_811_200_000,
                            "$metadata": {"error": "scheduled failure"},
                            "$workers": {
                                "scriptName": "raindrop-rss",
                                "outcome": "exception",
                            },
                        }
                    ],
                }
            },
        }

    monkeypatch.setattr("scripts.check_monitor._fetch_json", fake_fetch_json)

    count, events, start_ms, end_ms = query_cloudflare_errors(
        account_id="account-id",
        api_token="secret-token",
        query_id="query-id",
        minutes=60,
        timeout=15,
        now_ms=1_723_811_200_000,
    )

    assert count == 1
    assert len(events) == 1
    assert start_ms == end_ms - 3_600_000
    assert captured["payload"] == {
        "queryId": "query-id",
        "timeframe": {"from": start_ms, "to": end_ms},
    }
    assert captured["headers"]["Authorization"] == "Bearer secret-token"


def test_summarize_log_event_prefers_cloudflare_error_metadata() -> None:
    summary = summarize_log_event(
        {
            "timestamp": 1_723_811_200_000,
            "$metadata": {"error": "Feed synchronization failed: rss"},
            "$workers": {"scriptName": "raindrop-rss", "outcome": "exception"},
        }
    )

    assert "raindrop-rss (exception): Feed synchronization failed: rss" in summary
