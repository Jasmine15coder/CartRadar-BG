import asyncio

from app.platforms.zepto.client import ZeptoClient
from app.platforms.zepto.search import run_zepto_search
from app.store_cache import StoreCache


def test_test_mode_includes_all_bengaluru_stores_outside_search_radius(monkeypatch) -> None:
    monkeypatch.setenv("ZEPTO_TEST_MODE", "true")
    cache = StoreCache(":memory:")
    cache._db.executemany(
        """INSERT INTO stores
           (id, platform, name, city, lat, lng, probe_count, discovered_at, last_seen_at)
           VALUES (?, 'zepto', ?, ?, ?, ?, 1, 'test', 'test')""",
        [
            ("near", "BLR-Chickpet New", "Bengaluru", 12.9548, 77.5790),
            ("mid", "BLR-Midtown", "Bengaluru", 12.99, 77.61),
            ("far", "BLR-North", "Bengaluru", 13.05, 77.66),
            ("other-city", "Other City", "Delhi", 28.6, 77.2),
        ],
    )
    cache._db.commit()

    async def collect_events() -> list[dict]:
        return [
            event
            async for event in run_zepto_search(
                ZeptoClient(),
                "pvid",
                12.9548,
                77.5790,
                1,
                cache,
            )
        ]

    try:
        events = asyncio.run(collect_events())
    finally:
        cache.close()
    store_events = [event for event in events if event["type"] == "store_result"]
    home_result = next(event for event in events if event["type"] == "home_result")
    summary = next(event["summary"] for event in events if event["type"] == "done")

    assert [event["store"]["id"] for event in store_events] == ["near", "mid", "far"]
    assert all(event["status"] == "in_stock" for event in store_events)
    assert home_result["store_name"] == "BLR-Chickpet New"
    assert summary["stores"] == 3
