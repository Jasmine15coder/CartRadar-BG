import asyncio

import pytest

from app.platforms.base import ProductResult
from app.platforms.zepto import search as zepto_search
from app.platforms.zepto import client as zepto_client
from app.platforms.zepto.client import ZeptoClient, ZeptoNetworkError, ZeptoPlaywrightSession, select_random_proxy
from app.store_cache import StoreCache


def test_live_search_includes_all_bengaluru_stores_outside_search_radius(monkeypatch) -> None:
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

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def probe_location(self, lat: float, lng: float) -> dict:
            return {"serviceable": False}

        async def check_product(self, store_id: str, pvid: str) -> ProductResult:
            return ProductResult(
                status="in_stock",
                name=f"Product at {store_id}",
                price={"near": 68.0, "mid": 72.5, "far": 89.0}[store_id],
                mrp=99.0,
            )

    monkeypatch.setattr(zepto_search, "ZeptoPlaywrightSession", FakeSession)

    async def collect_events() -> list[dict]:
        return [
            event
            async for event in zepto_search.run_zepto_search(
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
    assert [event["price"] for event in store_events] == [68.0, 72.5, 89.0]
    assert all(event["status"] == "in_stock" for event in store_events)
    assert home_result["serviceable"] is False
    assert summary["stores"] == 3


def test_select_random_proxy_strips_whitespace_and_ignores_empty_entries(tmp_path, monkeypatch) -> None:
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text("  http://proxy-one:8080  \n\n http://proxy-two:8080\n", encoding="utf-8")
    monkeypatch.setattr("app.platforms.zepto.client.random.choice", lambda proxies: proxies[-1])

    assert select_random_proxy(proxy_file) == "http://proxy-two:8080"


def test_playwright_launch_uses_selected_proxy(monkeypatch, tmp_path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text("http://approved-proxy:8080\n", encoding="utf-8")
    monkeypatch.setattr(zepto_client, "PROXY_LIST_PATH", proxy_file)
    monkeypatch.delenv("ZEPTO_TEST_MODE", raising=False)
    launch_options: dict = {}

    class FakePage:
        async def goto(self, *args, **kwargs):
            return None

        async def wait_for_timeout(self, *args):
            return None

    class FakeContext:
        async def new_page(self):
            return FakePage()

        async def cookies(self):
            return []

    class FakeBrowser:
        async def new_context(self, **kwargs):
            return FakeContext()

        async def close(self):
            return None

    class FakeChromium:
        async def launch(self, **kwargs):
            launch_options.update(kwargs)
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        async def stop(self):
            return None

    class FakeManager:
        async def start(self):
            return FakePlaywright()

    monkeypatch.setattr(zepto_client, "async_playwright", lambda: FakeManager())

    async def open_session() -> None:
        session = ZeptoPlaywrightSession(proxy="http://approved-proxy:8080")
        await session.__aenter__()
        await session.__aexit__(None, None, None)

    asyncio.run(open_session())

    assert launch_options == {
        "headless": True,
        "proxy": {"server": "http://approved-proxy:8080"},
    }


def test_proxy_launch_failure_is_wrapped_and_playwright_stopped(monkeypatch, tmp_path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text("http://approved-proxy:8080\n", encoding="utf-8")
    monkeypatch.setattr(zepto_client, "PROXY_LIST_PATH", proxy_file)
    monkeypatch.delenv("ZEPTO_TEST_MODE", raising=False)
    stopped = False

    class FakeChromium:
        async def launch(self, **kwargs):
            raise TimeoutError("proxy timeout")

    class FakePlaywright:
        chromium = FakeChromium()

        async def stop(self):
            nonlocal stopped
            stopped = True

    class FakeManager:
        async def start(self):
            return FakePlaywright()

    monkeypatch.setattr(zepto_client, "async_playwright", lambda: FakeManager())

    async def open_session() -> None:
        await ZeptoPlaywrightSession(proxy="http://approved-proxy:8080").__aenter__()

    try:
        asyncio.run(open_session())
    except ZeptoNetworkError as error:
        assert "proxy connection failed" in str(error)
    else:
        raise AssertionError("A failed proxy launch must be reported.")

    assert stopped


@pytest.mark.parametrize("proxy_contents", [None, " \n\t"])
@pytest.mark.parametrize("test_mode", [False, True])
def test_missing_proxy_or_test_mode_still_starts_live_playwright(
    tmp_path, monkeypatch, proxy_contents: str | None, test_mode: bool
) -> None:
    proxy_file = tmp_path / "proxies.txt"
    if proxy_contents is not None:
        proxy_file.write_text(proxy_contents, encoding="utf-8")
    monkeypatch.setattr(zepto_client, "PROXY_LIST_PATH", proxy_file)
    if test_mode:
        monkeypatch.setenv("ZEPTO_TEST_MODE", "true")
    else:
        monkeypatch.delenv("ZEPTO_TEST_MODE", raising=False)
    launch_options: dict = {}

    class FakePage:
        async def goto(self, *args, **kwargs):
            return None

        async def wait_for_timeout(self, *args):
            return None

    class FakeContext:
        async def new_page(self):
            return FakePage()

        async def cookies(self):
            return []

    class FakeBrowser:
        async def new_context(self, **kwargs):
            return FakeContext()

        async def close(self):
            return None

    class FakeChromium:
        async def launch(self, **kwargs):
            launch_options.update(kwargs)
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        async def stop(self):
            return None

    class FakeManager:
        async def start(self):
            return FakePlaywright()

    monkeypatch.setattr(zepto_client, "async_playwright", lambda: FakeManager())

    async def open_session() -> None:
        async with ZeptoPlaywrightSession() as session:
            assert session.page is not None

    asyncio.run(open_session())

    assert launch_options == {"headless": True}
