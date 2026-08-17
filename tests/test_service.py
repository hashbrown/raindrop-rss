from __future__ import annotations

from datetime import timedelta

from conftest import NOW, FakeKV, FakeR2, FakeRaindrop, config_json, raindrop_item

from raindrop_rss.config import load_config
from raindrop_rss.raindrop import RaindropAPIError
from raindrop_rss.service import FeedService
from raindrop_rss.state import FeedState, state_key


async def test_sync_publishes_both_objects_before_state_pointer(app_config) -> None:
    events: list[tuple[str, str]] = []
    kv = FakeKV(events)
    r2 = FakeR2(events)
    raindrop = FakeRaindrop([raindrop_item(1)])
    service = FeedService(app_config, kv, r2, raindrop)

    result = await service.sync_due(NOW)

    assert result.succeeded == ("ai",)
    assert [event[0] for event in events[:3]] == ["r2.put", "r2.put", "kv.put"]
    state = FeedState.from_json(kv.values[state_key("ai")])
    assert state.atom and state.rss
    assert state.atom.object_key in r2.values
    assert state.rss.object_key in r2.values
    assert state.last_error is None
    assert state.next_sync_at == "2026-08-17T12:00:00Z"


async def test_per_feed_max_items_is_applied_after_pagination_data(app_config) -> None:
    limited_config = load_config(config_json(max_items=2))
    items = [
        raindrop_item(i, created=f"2026-08-{i:02d}T00:00:00Z") for i in range(1, 10)
    ]
    kv, r2 = FakeKV(), FakeR2()
    service = FeedService(limited_config, kv, r2, FakeRaindrop(items))
    await service.sync_due(NOW)
    state = await service.get_state("ai")
    atom = r2.values[state.atom.object_key]
    assert atom.count(b"<atom:entry>") == 2
    assert b"Article 9" in atom and b"Article 8" in atom and b"Article 7" not in atom


async def test_not_due_feed_does_not_call_raindrop(app_config) -> None:
    kv, r2, raindrop = FakeKV(), FakeR2(), FakeRaindrop([raindrop_item(1)])
    service = FeedService(app_config, kv, r2, raindrop)
    await service.sync_due(NOW)
    result = await service.sync_due(NOW + timedelta(hours=1))
    assert result.attempted == 0
    assert raindrop.calls == 1


async def test_configuration_change_forces_immediate_sync(app_config) -> None:
    kv, r2 = FakeKV(), FakeR2()
    first = FeedService(app_config, kv, r2, FakeRaindrop([raindrop_item(1)]))
    await first.sync_due(NOW)
    changed_config = load_config(config_json(max_items=25))
    changed_raindrop = FakeRaindrop([raindrop_item(1)])
    result = await FeedService(changed_config, kv, r2, changed_raindrop).sync_due(
        NOW + timedelta(minutes=1)
    )
    assert result.attempted == 1
    assert changed_raindrop.calls == 1


async def test_second_object_failure_preserves_last_good_pointer(app_config) -> None:
    kv, r2 = FakeKV(), FakeR2()
    service = FeedService(app_config, kv, r2, FakeRaindrop([raindrop_item(1)]))
    await service.sync_due(NOW)
    original = kv.values[state_key("ai")]

    r2.fail_on_put_number = r2.put_count + 2
    service.raindrop = FakeRaindrop(
        [raindrop_item(2, created="2026-08-16T13:00:00Z", updated="2026-08-16T13:00:00Z")]
    )
    result = await service.sync_due(NOW + timedelta(days=1))

    assert result.failed == ("ai",)
    state = FeedState.from_json(kv.values[state_key("ai")])
    old_state = FeedState.from_json(original)
    assert state.atom == old_state.atom
    assert state.rss == old_state.rss
    assert state.last_successful_sync == old_state.last_successful_sync
    assert state.last_error == "RuntimeError"


async def test_api_failure_records_error_without_advancing_success(app_config) -> None:
    kv, r2 = FakeKV(), FakeR2()
    service = FeedService(app_config, kv, r2, FakeRaindrop([raindrop_item(1)]))
    await service.sync_due(NOW)
    old_state = await service.get_state("ai")
    failing = FakeRaindrop()
    failing.error = RaindropAPIError("Raindrop API returned HTTP 503")
    service.raindrop = failing

    await service.sync_due(NOW + timedelta(days=1))
    state = await service.get_state("ai")

    assert state.atom == old_state.atom and state.rss == old_state.rss
    assert state.last_successful_sync == old_state.last_successful_sync
    assert state.next_sync_at == old_state.next_sync_at
    assert state.last_error == "Raindrop API returned HTTP 503"


async def test_transport_failure_is_safely_recorded(app_config) -> None:
    kv, r2 = FakeKV(), FakeR2()
    failing = FakeRaindrop()
    failing.error = RuntimeError("request failed with a potentially sensitive URL")
    service = FeedService(app_config, kv, r2, failing)

    result = await service.sync_due(NOW)
    state = await service.get_state("ai")

    assert result.failed == ("ai",)
    assert state.last_error == "RuntimeError"


async def test_failure_for_one_feed_does_not_prevent_other_due_feeds() -> None:
    class SelectiveRaindrop(FakeRaindrop):
        async def fetch_matching(
            self, tags: tuple[str, ...], max_items: int
        ) -> list[dict[str, object]]:
            self.calls += 1
            if tags == ("broken",):
                raise RaindropAPIError("Raindrop API returned HTTP 503")
            return [raindrop_item(1, tags=list(tags))]

    config = load_config(
        config_json(
            feeds=[
                {
                    "slug": "broken",
                    "title": "Broken",
                    "description": "Fails safely.",
                    "tags": ["broken"],
                    "sync_interval_hours": 24,
                    "max_items": 100,
                },
                {
                    "slug": "working",
                    "title": "Working",
                    "description": "Still publishes.",
                    "tags": ["working"],
                    "sync_interval_hours": 24,
                    "max_items": 100,
                },
            ]
        )
    )
    kv, r2, raindrop = FakeKV(), FakeR2(), SelectiveRaindrop()

    result = await FeedService(config, kv, r2, raindrop).sync_due(NOW)

    assert result.failed == ("broken",)
    assert result.succeeded == ("working",)
    assert raindrop.calls == 2


async def test_rollbacks_retain_only_two_previous_versions(app_config) -> None:
    kv, r2 = FakeKV(), FakeR2()
    service = FeedService(app_config, kv, r2, FakeRaindrop())
    for day in range(4):
        service.raindrop = FakeRaindrop(
            [raindrop_item(day + 1, created=f"2026-08-{16 + day:02d}T12:00:00Z")]
        )
        await service.sync_due(NOW + timedelta(days=day))
    state = await service.get_state("ai")
    assert len(state.history) == 2
    active_and_history = {
        state.atom.object_key,
        state.rss.object_key,
        *(entry.atom_key for entry in state.history),
        *(entry.rss_key for entry in state.history),
    }
    assert set(r2.values) == active_and_history
