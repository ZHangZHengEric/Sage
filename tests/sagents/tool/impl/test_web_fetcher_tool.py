import asyncio
import sys
import types

from sagents.tool.impl.web_fetcher_tool import WebFetcherTool


def test_fetch_html_page_uses_async_fetcher_class_api(monkeypatch):
    calls = []
    expected_page = object()

    class FakeAsyncFetcher:
        def __init__(self):
            raise AssertionError("AsyncFetcher should not be instantiated")

        @classmethod
        async def get(cls, url, **kwargs):
            calls.append((url, kwargs))
            return expected_page

    scrapling_module = types.ModuleType("scrapling")
    fetchers_module = types.ModuleType("scrapling.fetchers")
    fetchers_module.AsyncFetcher = FakeAsyncFetcher
    scrapling_module.fetchers = fetchers_module

    monkeypatch.setitem(sys.modules, "scrapling", scrapling_module)
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", fetchers_module)

    page = asyncio.run(WebFetcherTool()._fetch_html_page("https://example.com", 7))

    assert page is expected_page
    assert calls == [
        (
            "https://example.com",
            {
                "stealthy_headers": True,
                "timeout": 7,
            },
        )
    ]
