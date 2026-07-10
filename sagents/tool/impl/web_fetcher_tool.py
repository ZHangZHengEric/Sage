#!/usr/bin/env python3
"""
使用 Scrapling 框架的网页抓取工具
Scrapling 特性：
- 自适应解析：自动学习页面结构，网站更新时自动重新定位元素
- 反爬虫绕过：内置绕过 Cloudflare 等反爬虫机制
- 多种 Fetcher：StealthyFetcher、DynamicFetcher 等支持无头浏览器
- 智能内容提取
- 支持文件下载：自动检测并下载非 HTML 文件到 Agent 工作空间
"""

import asyncio
import json
import os
import re
import aiohttp
import aiofiles
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin, urlparse, unquote
from ..tool_base import tool
from ..error_codes import (
    ToolErrorCode as _ToolErrorCode,
    make_tool_error as _make_tool_error,
)
from sagents.utils.logger import logger


class _HttpStatusError(Exception):
    """HTTP response that must not be parsed as webpage content."""

    def __init__(self, status: int, reason: str = "") -> None:
        self.status = status
        self.retryable = status in {408, 429} or status >= 500
        detail = f" {reason}" if reason else ""
        super().__init__(f"HTTP {status}{detail}")


class WebFetcherTool:
    """基于 Scrapling 的网页抓取工具，支持网页内容提取和文件下载"""

    # 总返回内容的最大token数限制
    MAX_TOTAL_TOKENS = 8000
    # 每个token大约对应的字符数（保守估计）
    CHARS_PER_TOKEN = 2.5

    # 常见文件扩展名映射
    FILE_EXTENSIONS = {
        ".pdf": "document",
        ".doc": "document",
        ".docx": "document",
        ".xls": "spreadsheet",
        ".xlsx": "spreadsheet",
        ".ppt": "presentation",
        ".pptx": "presentation",
        ".txt": "text",
        ".csv": "spreadsheet",
        ".json": "data",
        ".xml": "data",
        ".zip": "archive",
        ".rar": "archive",
        ".7z": "archive",
        ".tar": "archive",
        ".gz": "archive",
        ".jpg": "image",
        ".jpeg": "image",
        ".png": "image",
        ".gif": "image",
        ".bmp": "image",
        ".webp": "image",
        ".svg": "image",
        ".mp3": "audio",
        ".wav": "audio",
        ".ogg": "audio",
        ".mp4": "video",
        ".avi": "video",
        ".mov": "video",
        ".mkv": "video",
        ".exe": "executable",
        ".dmg": "executable",
        ".pkg": "executable",
    }

    @staticmethod
    def _write_html_content_sync(
        save_path: str,
        *,
        url: str,
        title: str,
        used_selector: str,
        full_content: str,
    ) -> None:
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(f"URL: {url}\n")
            f.write(f"Title: {title}\n")
            f.write(f"Selector: {used_selector}\n")
            f.write(f"Content Length: {len(full_content)}\n")
            f.write("=" * 80 + "\n\n")
            f.write(full_content)

    @staticmethod
    def _content_selectors() -> List[str]:
        return [
            "#js_content",
            ".rich_media_content",
            '[data-testid="article"]',
            ".RichContent-inner",
            ".RichContent",
            ".Post-RichTextContainer",
            ".QuestionAnswer-content",
            "article",
            "main",
            '[role="main"]',
            ".content",
            ".article-content",
            ".post-content",
            ".entry-content",
            "#content",
            ".main-content",
            "body",
        ]

    @tool(
        description_i18n={
            "zh": "使用 Scrapling 框架智能抓取网页内容或下载文件，支持自适应解析、反爬虫绕过和文件自动保存到工作空间",
            "en": "Intelligently fetch webpage content or download files using Scrapling framework with adaptive parsing, anti-bot bypass and auto-save to workspace",
        },
        param_description_i18n={
            "urls": {
                "zh": "网页URL列表，支持单个URL字符串或URL列表。支持HTML页面和文件下载",
                "en": "List of webpage URLs, supports single URL string or list of URLs. Supports HTML pages and file downloads",
            },
            "max_length_per_url": {
                "zh": "每个URL返回的最大文本长度（字符数），默认8000。仅适用于HTML页面",
                "en": "Maximum text length per URL (characters), default 8000. Only applies to HTML pages",
            },
            "timeout": {
                "zh": "每个请求的超时时间（秒），默认30秒",
                "en": "Timeout per request (seconds), default 30",
            },
            "retries": {
                "zh": "失败重试次数，默认1",
                "en": "Number of retries on failure, default 1",
            },
            "session_id": {
                "zh": "会话ID，用于确定Agent工作空间路径，文件将保存到该工作空间",
                "en": "Session ID for determining agent workspace path, files will be saved to this workspace",
            },
        },
    )
    async def fetch_webpages(
        self,
        urls: List[str],
        max_length_per_url: int = 8000,
        timeout: int = 30,
        retries: int = 1,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        抓取网页内容或下载文件

        Args:
            urls: 网页URL列表，可以是单个URL字符串或URL列表
            max_length_per_url: 每个URL返回的最大文本长度（字符数）
            timeout: 每个请求的超时时间（秒）
            retries: 失败重试次数
            session_id: 会话ID，用于确定Agent工作空间路径

        Returns:
            Dict[str, Any]: 包含抓取结果的字典
        """
        if isinstance(urls, str):
            urls = [urls]
        elif not isinstance(urls, list):
            return _make_tool_error(
                _ToolErrorCode.INVALID_ARGUMENT,
                "urls参数必须是字符串或字符串列表",
                results=[],
            )

        if not urls:
            return _make_tool_error(
                _ToolErrorCode.INVALID_ARGUMENT,
                "URL列表不能为空",
                results=[],
            )

        # 获取工作空间路径
        workspace_path = self._get_workspace_path(session_id)

        # 计算每个HTML页面可以返回的最大字符数
        # 总字符数 = 8000 tokens * 2.5 chars/token = 20000 字符
        # 分配给每个HTML页面
        html_url_count = sum(1 for url in urls if self._detect_url_type(url) == "html")
        if html_url_count > 0:
            max_total_chars = int(self.MAX_TOTAL_TOKENS * self.CHARS_PER_TOKEN)
            chars_per_html = max_total_chars // html_url_count
        else:
            chars_per_html = max_length_per_url

        # 定义单个URL的处理函数
        async def process_single_url(url: str) -> Dict[str, Any]:
            """处理单个URL的抓取或下载"""
            try:
                # 检测URL类型
                url_type = self._detect_url_type(url)

                if url_type == "html":
                    # HTML页面，使用新的抓取逻辑（保存完整内容到文件，返回部分内容）
                    result = await self._fetch_single_html_with_save(
                        url, chars_per_html, workspace_path, timeout, retries
                    )
                else:
                    # 文件，使用下载逻辑
                    result = await self._download_file(
                        url, workspace_path, timeout, retries
                    )

                return result
            except Exception as e:
                logger.error(f"Fetch error for {url}: {e}")
                return {
                    "url": url,
                    "status": "error",
                    "error": str(e),
                    "content": None,
                    "metadata": None,
                }

        # 并发处理所有URL
        tasks = [process_single_url(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        success_count = sum(1 for r in results if r.get("status") == "success")
        error_count = len(results) - success_count

        if success_count == len(urls):
            status = "success"
            message = f"Successfully processed all {len(urls)} URLs"
        elif success_count > 0:
            status = "partial"
            message = (
                f"Successfully processed {success_count}/{len(urls)} URLs; "
                f"{error_count} failed"
            )
        else:
            status = "error"
            message = f"Failed to process all {len(urls)} URLs"

        return {
            "status": status,
            "message": message,
            "total_urls": len(urls),
            "success_count": success_count,
            "error_count": error_count,
            "workspace": workspace_path,
            "results": results,
        }

    def _detect_url_type(self, url: str) -> str:
        """检测URL类型是HTML页面还是文件"""
        parsed = urlparse(url)
        path = unquote(parsed.path)

        # 获取文件扩展名
        ext = os.path.splitext(path.lower())[1]

        if ext in self.FILE_EXTENSIONS:
            return "file"

        # 没有扩展名或常见HTML扩展名，视为HTML
        return "html"

    def _get_session_context(self, session_id: Optional[str] = None):
        """通过 session_id 获取 session_context"""
        if not session_id:
            return None
        try:
            from sagents.utils.agent_session_helper import get_live_session_context

            ctx = get_live_session_context(session_id, log_prefix="WebFetcherTool")
            if ctx:
                return ctx
        except Exception as e:
            logger.warning(f"通过 session_id 获取 session_context 失败: {e}")
        return None

    def _get_workspace_path(self, session_id: Optional[str]) -> str:
        """获取Agent工作空间路径"""
        # 尝试通过 session_id 获取虚拟工作区
        session_context = self._get_session_context(session_id)
        if session_context:
            try:
                sandbox_agent_workspace = session_context.sandbox_agent_workspace
                # 在工作空间下创建 downloads 目录
                workspace = os.path.join(sandbox_agent_workspace, "downloads")  # pyright: ignore[reportArgumentType,reportCallIssue]
                os.makedirs(workspace, exist_ok=True)
                return workspace
            except Exception as e:
                logger.warning(f"通过 session_context 获取路径失败: {e}")

        # 退化为默认下载目录
        user_home = os.path.expanduser("~")
        workspace = os.path.join(user_home, ".sage", "downloads")
        os.makedirs(workspace, exist_ok=True)
        return workspace

    async def _download_file(
        self, url: str, save_dir: str, timeout: int, retries: int
    ) -> Dict[str, Any]:
        """下载文件到指定目录"""
        last_error = None

        # 从URL提取文件名
        parsed = urlparse(url)
        path = unquote(parsed.path)
        filename = os.path.basename(path)

        # 如果没有文件名，使用默认名称
        if not filename:
            ext = self._get_extension_from_url(url)
            filename = f"download_{int(asyncio.get_event_loop().time())}{ext}"

        # 确保文件名安全
        filename = self._sanitize_filename(filename)
        save_path = os.path.join(save_dir, filename)

        # 如果文件已存在，添加序号
        counter = 1
        original_name = filename
        while os.path.exists(save_path):
            name, ext = os.path.splitext(original_name)
            filename = f"{name}_{counter}{ext}"
            save_path = os.path.join(save_dir, filename)
            counter += 1

        for attempt in range(retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url, timeout=aiohttp.ClientTimeout(total=timeout)
                    ) as response:
                        if response.status != 200:
                            raise Exception(f"HTTP {response.status}")

                        # 获取文件大小
                        content_length = response.headers.get("Content-Length")
                        if content_length:
                            size_mb = int(content_length) / (1024 * 1024)
                            if size_mb > 100:  # 限制100MB
                                raise Exception(
                                    f"文件过大 ({size_mb:.1f}MB)，超过100MB限制"
                                )

                        # 下载文件
                        async with aiofiles.open(save_path, "wb") as f:
                            async for chunk in response.content.iter_chunked(8192):
                                await f.write(chunk)

                # 获取文件信息
                file_size = os.path.getsize(save_path)
                file_type = self.FILE_EXTENSIONS.get(
                    os.path.splitext(filename)[1].lower(), "unknown"
                )

                return {
                    "url": url,
                    "status": "success",
                    "type": "file",
                    "content": f"File downloaded to: {save_path}",
                    "metadata": {
                        "filename": filename,
                        "save_path": save_path,
                        "file_size": file_size,
                        "file_size_human": self._format_file_size(file_size),
                        "file_type": file_type,
                    },
                }

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"WebFetcher: Download failed for {url} (尝试 {attempt + 1}/{retries + 1}): {last_error}"
                )

                if attempt < retries:
                    wait_time = 2**attempt
                    await asyncio.sleep(wait_time)

        return {
            "url": url,
            "status": "error",
            "error": f"Download failed after {retries + 1} attempts: {last_error}",
            "content": None,
            "metadata": None,
        }

    def _get_extension_from_url(self, url: str) -> str:
        """从URL获取文件扩展名"""
        parsed = urlparse(url)
        path = unquote(parsed.path)
        ext = os.path.splitext(path)[1]
        return ext if ext else ".bin"

    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名，移除不安全字符"""
        import re

        # 移除路径分隔符和其他不安全字符
        filename = re.sub(r'[\\/*?:"<>|]', "_", filename)
        # 限制长度
        if len(filename) > 200:
            name, ext = os.path.splitext(filename)
            filename = name[: 200 - len(ext)] + ext
        return filename

    def _format_file_size(self, size_bytes: int) -> str:
        """格式化文件大小"""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024  # pyright: ignore[reportAssignmentType]
        return f"{size_bytes:.2f} TB"

    async def _fetch_single_html_with_save(
        self,
        url: str,
        max_return_length: int,
        save_dir: str,
        timeout: int,
        retries: int,
    ) -> Dict[str, Any]:
        """抓取单个HTML页面，保存完整内容到文件，返回部分内容"""
        last_error = None
        for attempt in range(retries + 1):
            try:
                page = await self._fetch_html_page(url, timeout)

                # 提取标题
                title = page.css("title::text").get("")
                if not title:
                    title = page.css("h1::text").get("")
                if not title:
                    title = page.css("#activity-name::text").get("")

                effective_base_url = self._effective_base_url(page, url)
                full_content, used_selector, images = self._extract_markdown_content(
                    page, effective_base_url
                )

                # 生成文件名
                from urllib.parse import urlparse

                parsed = urlparse(url)
                domain = parsed.netloc.replace(":", "_")
                safe_title = self._sanitize_filename(
                    title[:50] if title else "untitled"
                )
                filename = f"{domain}_{safe_title}.md"

                # 处理文件名冲突
                save_path = os.path.join(save_dir, filename)
                counter = 1
                original_name = filename
                while os.path.exists(save_path):
                    name, ext = os.path.splitext(original_name)
                    filename = f"{name}_{counter}{ext}"
                    save_path = os.path.join(save_dir, filename)
                    counter += 1

                # 保存完整内容到文件
                await asyncio.to_thread(
                    self._write_html_content_sync,
                    save_path,
                    url=url,
                    title=title,
                    used_selector=used_selector,
                    full_content=full_content,
                )

                # 准备返回的内容（截断后的）
                if len(full_content) > max_return_length:
                    return_content = (
                        full_content[:max_return_length]
                        + f"\n\n[Content truncated. Full content saved to: {save_path}]"
                    )
                else:
                    return_content = full_content

                return {
                    "url": url,
                    "status": "success",
                    "type": "html",
                    "content": return_content,
                    "metadata": {
                        "title": title,
                        "selector": used_selector,
                        "content_length": len(full_content),
                        "return_length": len(return_content),
                        "full_content_saved": True,
                        "save_path": save_path,
                        "filename": filename,
                        "image_count": len(images),
                        "images": images,
                    },
                }

            except _HttpStatusError as e:
                last_error = str(e)
                logger.warning(
                    f"WebFetcher: {url} HTTP响应失败 "
                    f"(尝试 {attempt + 1}/{retries + 1}): {last_error}"
                )
                if not e.retryable:
                    return {
                        "url": url,
                        "status": "error",
                        "error": last_error,
                        "content": None,
                        "metadata": None,
                    }
                if attempt < retries:
                    await asyncio.sleep(2**attempt)
            except asyncio.TimeoutError:
                last_error = f"请求超时（超过 {timeout} 秒）"
                logger.warning(
                    f"WebFetcher: {url} 请求超时 (尝试 {attempt + 1}/{retries + 1})"
                )
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"WebFetcher: {url} 抓取失败 (尝试 {attempt + 1}/{retries + 1}): {last_error}"
                )

                if attempt < retries:
                    wait_time = 2**attempt
                    await asyncio.sleep(wait_time)

        return {
            "url": url,
            "status": "error",
            "error": f"Failed after {retries + 1} attempts: {last_error}",
            "content": None,
            "metadata": None,
        }

    async def _fetch_single_html(
        self, url: str, max_length: int, timeout: int, retries: int
    ) -> Dict[str, Any]:
        """抓取单个HTML页面，带重试机制和严格超时控制"""
        last_error = None
        for attempt in range(retries + 1):
            try:
                page = await self._fetch_html_page(url, timeout)

                # 提取标题
                title = page.css("title::text").get("")
                if not title:
                    title = page.css("h1::text").get("")
                if not title:
                    title = page.css("#activity-name::text").get("")

                effective_base_url = self._effective_base_url(page, url)
                content, used_selector, images = self._extract_markdown_content(
                    page, effective_base_url
                )

                # 截断内容
                if len(content) > max_length:
                    content = (
                        content[:max_length]
                        + "\n\n[Content truncated because it exceeds the maximum length]"
                    )

                return {
                    "url": url,
                    "status": "success",
                    "type": "html",
                    "content": content,
                    "metadata": {
                        "title": title,
                        "selector": used_selector,
                        "content_length": len(content),
                        "image_count": len(images),
                        "images": images,
                    },
                }

            except _HttpStatusError as e:
                last_error = str(e)
                logger.warning(
                    f"WebFetcher: {url} HTTP响应失败 "
                    f"(尝试 {attempt + 1}/{retries + 1}): {last_error}"
                )
                if not e.retryable:
                    return {
                        "url": url,
                        "status": "error",
                        "error": last_error,
                        "content": None,
                        "metadata": None,
                    }
                if attempt < retries:
                    await asyncio.sleep(2**attempt)
            except asyncio.TimeoutError:
                last_error = f"请求超时（超过 {timeout} 秒）"
                logger.warning(
                    f"WebFetcher: {url} 请求超时 (尝试 {attempt + 1}/{retries + 1})"
                )
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"WebFetcher: {url} 抓取失败 (尝试 {attempt + 1}/{retries + 1}): {last_error}"
                )

                if attempt < retries:
                    wait_time = 2**attempt  # 指数退避: 1, 2, 4 秒
                    await asyncio.sleep(wait_time)

        return {
            "url": url,
            "status": "error",
            "error": f"Failed after {retries + 1} attempts: {last_error}",
            "content": None,
            "metadata": None,
        }

    async def _fetch_html_page(self, url: str, timeout: int):
        """Fetch an HTML page with Scrapling's class-level async fetcher API."""
        from scrapling.fetchers import AsyncFetcher  # pyright: ignore[reportMissingImports]

        page = await asyncio.wait_for(
            AsyncFetcher.get(
                url,
                stealthy_headers=True,
                timeout=timeout,
                retries=1,
            ),
            timeout=timeout + 5,
        )
        if not 200 <= page.status < 300:
            raise _HttpStatusError(page.status, page.reason)
        return page

    def _clean_content(self, text: str) -> str:
        """清理内容"""
        import re

        # 移除多余的空白行
        text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)

        # 移除行首行尾空白
        lines = [line.strip() for line in text.split("\n")]

        # 移除空行但保留段落间距
        cleaned_lines = []
        prev_empty = False
        for line in lines:
            if line:
                cleaned_lines.append(line)
                prev_empty = False
            elif not prev_empty:
                cleaned_lines.append("")
                prev_empty = True

        # 移除末尾空行
        while cleaned_lines and cleaned_lines[-1] == "":
            cleaned_lines.pop()

        return "\n".join(cleaned_lines)

    def _extract_markdown_content(self, page, base_url: str):
        """Extract the main content as Markdown while keeping image references."""
        platform_content = self._extract_platform_markdown_content(page, base_url)
        if platform_content:
            return platform_content

        best_content = ""
        best_selector = ""
        best_images: List[Dict[str, str]] = []

        for selector in self._content_selectors():
            elements = page.css(selector)
            if not elements:
                continue

            parts = []
            images: List[Dict[str, str]] = []
            for elem in elements:
                markdown, elem_images = self._element_to_markdown(elem, base_url)
                if markdown and (len(markdown.strip()) > 50 or elem_images):
                    parts.append(markdown.strip())
                    images.extend(elem_images)

            if not parts:
                continue

            content = self._clean_content("\n\n".join(parts))
            best_content = content
            best_selector = selector
            best_images = images

            if len(content) > 500 or images or selector == "body":
                break

        if best_content:
            return best_content, best_selector, self._dedupe_images(best_images)

        fallback = self._clean_content(page.get_all_text())
        return fallback, "full_page", []

    def _effective_base_url(self, page, requested_url: str) -> str:
        for attr in ("url", "real_url", "final_url"):
            value = getattr(page, attr, None)
            if callable(value):
                try:
                    value = value()
                except TypeError:
                    continue
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
        return requested_url

    def _extract_platform_markdown_content(self, page, base_url: str):
        """Extract platform-specific article/note payloads before generic HTML."""
        parsed = urlparse(base_url)
        page_html = self._get_page_html(page)

        if "xiaohongshu.com" in parsed.netloc or "xhslink.com" in parsed.netloc:
            return self._extract_xiaohongshu_note_markdown(
                page_html, base_url
            ) or self._extract_xiaohongshu_unavailable_markdown(page_html)

        return None

    def _get_page_html(self, page) -> str:
        for attr in ("html", "markup", "text"):
            value = getattr(page, attr, None)
            if callable(value):
                try:
                    value = value()
                except TypeError:
                    continue
            if isinstance(value, str) and "<" in value:
                return value

        body = page.css("body")
        if body:
            html_parts = [self._get_element_html(elem) for elem in body]
            html = "\n".join(part for part in html_parts if part)
            if html:
                return html

        rendered = str(page)
        return rendered if "<" in rendered else ""

    def _extract_xiaohongshu_note_markdown(self, html: str, base_url: str):
        if not html:
            return None

        note = self._find_xiaohongshu_note(html, base_url)
        if not note:
            return None

        title = note.get("title", "").strip()
        desc = note.get("desc", "").strip()
        images = note.get("images", [])

        parts = []
        if title:
            parts.append(f"# {title}")
        if desc:
            parts.append(desc)

        for index, image in enumerate(images, start=1):
            alt = image.get("alt") or title or f"Image {index}"
            parts.append(f"![{alt}]({image['src']})")

        content = self._clean_content("\n\n".join(parts))
        if not content:
            return None

        return content, "xiaohongshu_note_json", images

    def _extract_xiaohongshu_unavailable_markdown(self, html: str):
        if not html:
            return None

        plain_text = re.sub(r"\s+", " ", self._html_to_text(html)).strip()
        unavailable_markers = (
            "你访问的页面不见了",
            "页面不见了",
            "内容无法展示",
            "登录后查看",
            "验证码",
            "安全验证",
        )
        has_initial_state = "__INITIAL_STATE__" in html
        has_empty_note_state = '"noteDetailMap":{}' in html or '"noteDetailMap": {}' in html
        if not any(marker in plain_text for marker in unavailable_markers):
            if not (has_initial_state and has_empty_note_state):
                return None

        content = (
            "# Xiaohongshu share post did not return body content\n\n"
            "The fetched page is an empty state, error page, login page, or security verification page. "
            "The HTML does not contain usable post text or image lists."
        )
        return content, "xiaohongshu_unavailable", []

    def _html_to_text(self, html: str) -> str:
        try:
            from bs4 import BeautifulSoup

            return BeautifulSoup(html, "html.parser").get_text(" ")
        except Exception:
            return re.sub(r"<[^>]+>", " ", html)

    def _find_xiaohongshu_note(self, html: str, base_url: str):
        for payload in self._extract_json_payloads_from_html(html):
            best_note = self._find_best_note_payload(payload, base_url)
            if best_note:
                return best_note

        return None

    def _extract_json_payloads_from_html(self, html: str):
        payloads = []

        for match in re.finditer(
            r"<script[^>]*>(?P<script>.*?)</script>",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            script = match.group("script").strip()
            if not script:
                continue

            parsed_script = self._parse_json_like_script(script)
            if parsed_script is not None:
                payloads.append(parsed_script)

        parsed_html = self._parse_json_like_script(html)
        if parsed_html is not None:
            payloads.append(parsed_html)

        return payloads

    def _parse_json_like_script(self, text: str):
        candidates = []

        stripped = text.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            candidates.append(stripped)

        for marker in ("__INITIAL_STATE__", "__NEXT_DATA__", "window.__INITIAL_STATE__"):
            marker_index = text.find(marker)
            if marker_index == -1:
                continue
            brace_index = text.find("{", marker_index)
            if brace_index != -1:
                candidates.append(text[brace_index:])

        for candidate in candidates:
            json_text = self._balanced_json_text(candidate)
            if not json_text:
                continue
            normalized = re.sub(r"\bundefined\b", "null", json_text)
            try:
                return json.loads(normalized)
            except json.JSONDecodeError:
                continue

        return None

    def _balanced_json_text(self, text: str) -> str:
        start = text.find("{")
        if start == -1:
            return ""

        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]

        return ""

    def _find_best_note_payload(self, payload, base_url: str):
        best_note = None
        best_score = 0

        for item in self._walk_json(payload):
            note = self._normalize_xiaohongshu_note(item, base_url)
            if not note:
                continue

            score = len(note.get("desc", "")) + len(note.get("title", "")) * 2
            score += len(note.get("images", [])) * 100
            if score > best_score:
                best_score = score
                best_note = note

        return best_note

    def _walk_json(self, value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from self._walk_json(child)
        elif isinstance(value, list):
            for child in value:
                yield from self._walk_json(child)

    def _normalize_xiaohongshu_note(self, value: Any, base_url: str):
        if not isinstance(value, dict):
            return None

        note = value.get("note")
        if isinstance(note, dict):
            nested_note = self._normalize_xiaohongshu_note(note, base_url)
            if nested_note:
                return nested_note

        title = self._first_text_value(
            value, ("title", "displayTitle", "display_title", "name")
        )
        desc = self._first_text_value(
            value, ("desc", "description", "content", "noteText", "text")
        )

        raw_images = None
        for key in ("imageList", "images", "image_list", "imgs", "cover", "coverList"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                raw_images = candidate
                break
            if isinstance(candidate, dict):
                raw_images = [candidate]
                break

        images = self._extract_images_from_json(raw_images or [], base_url, title)
        has_note_marker = any(key in value for key in ("noteId", "note_id", "noteCard"))
        if not (has_note_marker or images) or not (title or desc or images):
            return None

        return {
            "title": title,
            "desc": desc,
            "images": self._dedupe_images(images),
        }

    def _first_text_value(self, value: Dict[str, Any], keys) -> str:
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return ""

    def _extract_images_from_json(
        self, values: List[Any], base_url: str, default_alt: str = ""
    ) -> List[Dict[str, str]]:
        images: List[Dict[str, str]] = []
        for value in values:
            image = self._extract_image_from_json(value, base_url, default_alt)
            if image:
                images.append(image)
        return images

    def _extract_image_from_json(
        self, value: Any, base_url: str, default_alt: str = ""
    ) -> Optional[Dict[str, str]]:
        if isinstance(value, str):
            src = value.strip()
        elif isinstance(value, dict):
            src = self._first_image_url_from_dict(value)
        else:
            return None

        if not src or not self._should_keep_image_src(src):
            return None

        return {"src": urljoin(base_url, src), "alt": default_alt}

    def _first_image_url_from_dict(self, value: Dict[str, Any]) -> str:
        info_list = value.get("infoList") or value.get("info_list")
        if isinstance(info_list, list):
            urls = []
            for item in info_list:
                if not isinstance(item, dict):
                    continue
                url = self._first_text_value(
                    item,
                    ("url", "src", "originalUrl", "originUrl", "urlDefault", "urlPre"),
                )
                if not url:
                    continue
                scene = item.get("imageScene") or item.get("image_scene") or ""
                urls.append((scene, url))

            for preferred_scene in (
                "H5_DTL",
                "WB_DFT",
                "CRD_WM_WEBP",
                "H5_PRV",
                "WB_PRV",
            ):
                for scene, url in urls:
                    if scene == preferred_scene:
                        return url
            if urls:
                return urls[0][1]

        for key in ("urlList", "url_list", "urls"):
            url_list = value.get(key)
            if isinstance(url_list, list):
                for item in url_list:
                    if isinstance(item, str) and item.strip():
                        return item.strip()
                    if isinstance(item, dict):
                        url = self._first_text_value(
                            item,
                            (
                                "url",
                                "src",
                                "imageUrl",
                                "image_url",
                                "originalUrl",
                                "originUrl",
                                "urlDefault",
                                "urlPre",
                            ),
                        )
                        if url:
                            return url

        return self._first_text_value(
            value,
            (
                "url",
                "src",
                "imageUrl",
                "image_url",
                "originalUrl",
                "originUrl",
                "urlDefault",
                "urlPre",
                "coverUrl",
                "cover_url",
            ),
        )

    def _should_keep_image_src(self, src: str) -> bool:
        normalized = src.strip().lower()
        if not normalized:
            return False
        return not normalized.startswith(("data:", "blob:", "javascript:"))

    def _element_to_markdown(self, elem, base_url: str):
        html = self._get_element_html(elem)
        if not html:
            return self._clean_content(elem.get_all_text()), []

        prepared_html, images = self._prepare_html_for_markdown(html, base_url)
        try:
            import html2text

            converter = html2text.HTML2Text()
            converter.ignore_links = False
            converter.ignore_images = False
            converter.body_width = 0
            converter.unicode_snob = True
            markdown = converter.handle(prepared_html)
            return self._clean_content(markdown.strip()), images
        except Exception as e:
            logger.warning(f"HTML 转 Markdown 失败，降级为纯文本: {e}")
            return self._clean_content(elem.get_all_text()), images

    def _get_element_html(self, elem) -> str:
        for attr in ("html", "markup", "text"):
            value = getattr(elem, attr, None)
            if callable(value):
                try:
                    value = value()
                except TypeError:
                    continue
            if isinstance(value, str) and "<" in value:
                return value

        rendered = str(elem)
        return rendered if "<" in rendered else ""

    def _prepare_html_for_markdown(self, html: str, base_url: str):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        images: List[Dict[str, str]] = []
        for img in soup.find_all("img"):
            src = self._get_image_src(img)
            if not src or not self._should_keep_image_src(src):
                img.decompose()
                continue

            absolute_src = urljoin(base_url, src)
            img["src"] = absolute_src

            image: Dict[str, str] = {"src": absolute_src, "alt": img.get("alt", "")}
            title = img.get("title")
            if title:
                image["title"] = title
            images.append(image)

        return str(soup), images

    def _get_image_src(self, img) -> str:
        for attr in (
            "src",
            "data-src",
            "data-original",
            "data-url",
            "data-lazy-src",
            "data-actualsrc",
        ):
            value = img.get(attr)
            if value:
                return value.strip()

        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:
            first_candidate = srcset.split(",", 1)[0].strip()
            if first_candidate:
                return first_candidate.split()[0]

        return ""

    def _dedupe_images(self, images: List[Dict[str, str]]) -> List[Dict[str, str]]:
        seen = set()
        unique_images = []
        for image in images:
            src = image.get("src")
            if not src or src in seen:
                continue
            seen.add(src)
            unique_images.append(image)
        return unique_images
