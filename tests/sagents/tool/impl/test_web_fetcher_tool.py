import asyncio
import re
import sys
import types

from sagents.tool.impl.web_fetcher_tool import WebFetcherTool


class CssResult(list):
    def get(self, default=""):
        return self[0] if self else default


class FakeElement:
    def __init__(self, html):
        self.html = html

    def get_all_text(self):
        return re.sub(r"<[^>]+>", " ", self.html)


class FakePage:
    def __init__(self, title, selector_html, url=None):
        self.title = title
        self.selector_html = selector_html
        self.url = url

    def css(self, selector):
        if selector == "title::text":
            return CssResult([self.title])
        if selector in self.selector_html:
            return CssResult([FakeElement(self.selector_html[selector])])
        return CssResult()

    def get_all_text(self):
        return "fallback page text"


class FakeImg:
    def __init__(self, raw_tag):
        self.raw_tag = raw_tag
        self.attrs = dict(re.findall(r'([:\w-]+)="([^"]*)"', raw_tag))
        self.removed = False

    def get(self, key, default=None):
        return self.attrs.get(key, default)

    def __setitem__(self, key, value):
        self.attrs[key] = value

    def decompose(self):
        self.removed = True

    def render(self):
        if self.removed:
            return ""
        attrs = " ".join(f'{key}="{value}"' for key, value in self.attrs.items())
        return f"<img {attrs}>"


class FakeBeautifulSoup:
    def __init__(self, html, parser):
        self.html = html
        self.images = [
            FakeImg(match.group(0)) for match in re.finditer(r"<img\b[^>]*>", html)
        ]

    def __call__(self, tags):
        return []

    def find_all(self, tag):
        return self.images if tag == "img" else []

    def __str__(self):
        html = self.html
        for image in self.images:
            html = html.replace(image.raw_tag, image.render(), 1)
        return html


class FakeHtml2Text:
    ignore_links = False
    ignore_images = False
    body_width = 0
    unicode_snob = True

    def handle(self, html):
        html = re.sub(
            r'<img\b[^>]*src="([^"]+)"[^>]*alt="([^"]*)"[^>]*>',
            lambda match: f"![{match.group(2)}]({match.group(1)})",
            html,
        )
        html = re.sub(
            r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            lambda match: f"[{match.group(2)}]({match.group(1)})",
            html,
        )
        html = re.sub(r"</p\s*>", "\n\n", html)
        html = re.sub(r"<[^>]+>", "", html)
        return html


def install_html_markdown_stubs(monkeypatch):
    bs4_module = types.ModuleType("bs4")
    bs4_module.BeautifulSoup = FakeBeautifulSoup
    html2text_module = types.ModuleType("html2text")
    html2text_module.HTML2Text = FakeHtml2Text

    monkeypatch.setitem(sys.modules, "bs4", bs4_module)
    monkeypatch.setitem(sys.modules, "html2text", html2text_module)


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


def test_fetch_html_with_save_outputs_markdown_images_and_metadata(
    monkeypatch, tmp_path
):
    install_html_markdown_stubs(monkeypatch)
    page = FakePage(
        "Example",
        {
            "article": (
                "<article><p>Intro text long enough to pass the content filter "
                '<a href="https://example.com/more">more</a>.</p>'
                '<p><img src="/a.png" alt="A" title="Chart"></p>'
                "<p>Tail text keeps the original reading order intact.</p></article>"
            )
        },
    )

    async def fake_fetch(url, timeout):
        return page

    tool = WebFetcherTool()
    monkeypatch.setattr(tool, "_fetch_html_page", fake_fetch)

    result = asyncio.run(
        tool._fetch_single_html_with_save(
            "https://domain.test/path/page.html", 5000, str(tmp_path), 3, 0
        )
    )

    assert result["status"] == "success"
    assert result["metadata"]["selector"] == "article"
    assert result["metadata"]["filename"].endswith(".md")
    assert "[more](https://example.com/more)" in result["content"]
    assert "![A](https://domain.test/a.png)" in result["content"]
    assert result["metadata"]["image_count"] == 1
    assert result["metadata"]["images"] == [
        {"src": "https://domain.test/a.png", "alt": "A", "title": "Chart"}
    ]
    assert (
        "![A](https://domain.test/a.png)"
        in tmp_path.joinpath(result["metadata"]["filename"]).read_text()
    )


def test_fetch_html_with_save_truncates_markdown_and_saves_full_content(
    monkeypatch, tmp_path
):
    install_html_markdown_stubs(monkeypatch)
    page = FakePage(
        "Long",
        {
            "article": (
                "<article><p>"
                + ("Long content with enough text. " * 30)
                + '<img src="images/a.png" alt="A">'
                + "</p></article>"
            )
        },
    )

    async def fake_fetch(url, timeout):
        return page

    tool = WebFetcherTool()
    monkeypatch.setattr(tool, "_fetch_html_page", fake_fetch)

    result = asyncio.run(
        tool._fetch_single_html_with_save(
            "https://domain.test/posts/long", 80, str(tmp_path), 3, 0
        )
    )

    assert "[Content truncated. Full content saved to:" in result["content"]
    assert result["metadata"]["full_content_saved"] is True
    saved_content = tmp_path.joinpath(result["metadata"]["filename"]).read_text()
    assert "![A](https://domain.test/posts/images/a.png)" in saved_content


def test_fetch_html_without_images_returns_markdown_text(monkeypatch, tmp_path):
    install_html_markdown_stubs(monkeypatch)
    page = FakePage(
        "Text",
        {
            "main": (
                "<main><p>Plain content long enough to pass the content filter "
                '<a href="https://domain.test/ref">reference</a>.</p></main>'
            )
        },
    )

    async def fake_fetch(url, timeout):
        return page

    tool = WebFetcherTool()
    monkeypatch.setattr(tool, "_fetch_html_page", fake_fetch)

    result = asyncio.run(
        tool._fetch_single_html_with_save(
            "https://domain.test/text", 5000, str(tmp_path), 3, 0
        )
    )

    assert result["status"] == "success"
    assert result["metadata"]["image_count"] == 0
    assert result["metadata"]["images"] == []
    assert "[reference](https://domain.test/ref)" in result["content"]


def test_fetch_html_skips_embedded_data_images(monkeypatch, tmp_path):
    install_html_markdown_stubs(monkeypatch)
    page = FakePage(
        "Embedded",
        {
            "article": (
                "<article><p>Content long enough to keep this article body.</p>"
                '<p><img src="data:image/png;base64,abc" alt="inline"></p>'
                '<p><img src="/remote.png" alt="remote"></p></article>'
            )
        },
    )

    async def fake_fetch(url, timeout):
        return page

    tool = WebFetcherTool()
    monkeypatch.setattr(tool, "_fetch_html_page", fake_fetch)

    result = asyncio.run(
        tool._fetch_single_html_with_save(
            "https://domain.test/page", 5000, str(tmp_path), 3, 0
        )
    )

    assert "data:image" not in result["content"]
    assert "![remote](https://domain.test/remote.png)" in result["content"]
    assert result["metadata"]["images"] == [
        {"src": "https://domain.test/remote.png", "alt": "remote"}
    ]


def test_xiaohongshu_share_note_json_outputs_note_markdown(monkeypatch, tmp_path):
    install_html_markdown_stubs(monkeypatch)
    page = FakePage(
        "小红书",
        {
            "body": (
                "<body><script>"
                'window.__INITIAL_STATE__ = {"noteDetailMap": {"abc": {"note": {'
                '"noteId": "abc",'
                '"title": "周末探店",'
                '"desc": "咖啡不错\\n甜点也很稳",'
                '"imageList": ['
                '{"infoList": ['
                '{"imageScene": "WB_PRV", "url": "https://sns-img-qc.xhscdn.com/preview.webp"},'
                '{"imageScene": "WB_DFT", "url": "https://sns-img-qc.xhscdn.com/main.webp"}'
                "]},"
                '{"url": "/relative-cover.jpg"}'
                "]"
                "}}}};"
                "</script>"
                '<div class="main-content">feed avatar noise <img src="/avatar.png"></div>'
                "</body>"
            )
        },
    )

    async def fake_fetch(url, timeout):
        return page

    tool = WebFetcherTool()
    monkeypatch.setattr(tool, "_fetch_html_page", fake_fetch)

    result = asyncio.run(
        tool._fetch_single_html_with_save(
            "https://www.xiaohongshu.com/explore/abc?xsec_token=token",
            5000,
            str(tmp_path),
            3,
            0,
        )
    )

    assert result["status"] == "success"
    assert result["metadata"]["selector"] == "xiaohongshu_note_json"
    assert "# 周末探店" in result["content"]
    assert "咖啡不错" in result["content"]
    assert "![周末探店](https://sns-img-qc.xhscdn.com/main.webp)" in result["content"]
    assert (
        "![周末探店](https://www.xiaohongshu.com/relative-cover.jpg)"
        in result["content"]
    )
    assert "/avatar.png" not in result["content"]
    assert result["metadata"]["image_count"] == 2
    assert result["metadata"]["images"] == [
        {"src": "https://sns-img-qc.xhscdn.com/main.webp", "alt": "周末探店"},
        {"src": "https://www.xiaohongshu.com/relative-cover.jpg", "alt": "周末探店"},
    ]


def test_xiaohongshu_short_link_uses_final_url_for_relative_images(
    monkeypatch, tmp_path
):
    install_html_markdown_stubs(monkeypatch)
    page = FakePage(
        "小红书",
        {
            "body": (
                "<body><script>"
                'window.__INITIAL_STATE__ = {"note": {'
                '"note_id": "xyz",'
                '"displayTitle": "短链图片",'
                '"content": "分享链接里的帖子",'
                '"images": ['
                '{"urlList": [{"imageUrl": "/image-from-final.webp"}]},'
                '{"coverUrl": "https://sns-img-qc.xhscdn.com/cover.webp"}'
                "]"
                "}};"
                "</script></body>"
            )
        },
        url="https://www.xiaohongshu.com/explore/xyz?xsec_token=token",
    )

    async def fake_fetch(url, timeout):
        return page

    tool = WebFetcherTool()
    monkeypatch.setattr(tool, "_fetch_html_page", fake_fetch)

    result = asyncio.run(
        tool._fetch_single_html_with_save(
            "https://xhslink.com/a/abc123",
            5000,
            str(tmp_path),
            3,
            0,
        )
    )

    assert result["status"] == "success"
    assert result["metadata"]["selector"] == "xiaohongshu_note_json"
    assert (
        "![短链图片](https://www.xiaohongshu.com/image-from-final.webp)"
        in result["content"]
    )
    assert "![短链图片](https://sns-img-qc.xhscdn.com/cover.webp)" in result["content"]
    assert result["metadata"]["image_count"] == 2


def test_xiaohongshu_unavailable_page_does_not_fallback_to_shell_markdown(
    monkeypatch, tmp_path
):
    install_html_markdown_stubs(monkeypatch)
    page = FakePage(
        "小红书 - 你访问的页面不见了",
        {
            "body": (
                "<body><h1>你访问的页面不见了</h1>"
                '<script>window.__INITIAL_STATE__={"note":{"noteDetailMap":{}}}</script>'
                '<div class="main-content">站点壳子 <img src="data:image/png;base64,abc"></div>'
                "</body>"
            )
        },
    )

    async def fake_fetch(url, timeout):
        return page

    tool = WebFetcherTool()
    monkeypatch.setattr(tool, "_fetch_html_page", fake_fetch)

    result = asyncio.run(
        tool._fetch_single_html_with_save(
            "https://www.xiaohongshu.com/explore/missing",
            5000,
            str(tmp_path),
            3,
            0,
        )
    )

    assert result["status"] == "success"
    assert result["metadata"]["selector"] == "xiaohongshu_unavailable"
    assert "Xiaohongshu share post did not return body content" in result["content"]
    assert "data:image" not in result["content"]
    assert result["metadata"]["image_count"] == 0
