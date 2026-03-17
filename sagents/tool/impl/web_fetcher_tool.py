#!/usr/bin/env python3
"""
使用 Scrapling 框架的网页抓取工具
Scrapling 特性：
- 自适应解析：自动学习页面结构，网站更新时自动重新定位元素
- 反爬虫绕过：内置绕过 Cloudflare 等反爬虫机制
- 多种 Fetcher：StealthyFetcher、DynamicFetcher 等支持无头浏览器
- 智能内容提取
"""
import asyncio
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse
from ..tool_base import tool
from sagents.utils.logger import logger


class WebFetcherTool:
    """基于 Scrapling 的网页抓取工具"""

    @tool(
        description_i18n={
            "zh": "使用 Scrapling 框架智能抓取网页内容，支持自适应解析和反爬虫绕过",
            "en": "Intelligently fetch webpage content using Scrapling framework with adaptive parsing and anti-bot bypass",
        },
        param_description_i18n={
            "urls": {"zh": "网页URL列表，支持单个URL字符串或URL列表", "en": "List of webpage URLs, supports single URL string or list of URLs"},
            "max_length_per_url": {"zh": "每个URL返回的最大文本长度（字符数），默认8000", "en": "Maximum text length per URL (characters), default 8000"},
            "timeout": {"zh": "每个请求的超时时间（秒），默认60秒", "en": "Timeout per request (seconds), default 60"},
            "retries": {"zh": "失败重试次数，默认2", "en": "Number of retries on failure, default 2"},
        }
    )
    async def fetch_webpages(
        self,
        urls: List[str],
        max_length_per_url: int = 8000,
        timeout: int = 60,
        retries: int = 2
    ) -> Dict[str, Any]:
        """
        抓取网页内容

        Args:
            urls: 网页URL列表，可以是单个URL字符串或URL列表
            max_length_per_url: 每个URL返回的最大文本长度（字符数）
            timeout: 每个请求的超时时间（秒）
            retries: 失败重试次数

        Returns:
            Dict[str, Any]: 包含抓取结果的字典
        """
        if isinstance(urls, str):
            urls = [urls]
        elif not isinstance(urls, list):
            return {
                "status": "error",
                "message": "urls参数必须是字符串或字符串列表",
                "results": []
            }

        if not urls:
            return {
                "status": "error",
                "message": "URL列表不能为空",
                "results": []
            }

        logger.info(f"WebFetcher: Starting to fetch {len(urls)} webpage(s) with Scrapling")

        results = []
        for url in urls:
            try:
                result = await self._fetch_single(url, max_length_per_url, timeout, retries)
                results.append(result)
            except Exception as e:
                logger.error(f"Scrapling fetch error for {url}: {e}")
                results.append({
                    "url": url,
                    "status": "error",
                    "error": str(e),
                    "content": None,
                    "metadata": None
                })

        success_count = sum(1 for r in results if r.get("status") == "success")
        error_count = len(results) - success_count

        if success_count == len(urls):
            status = "success"
            message = f"成功抓取所有 {len(urls)} 个网页"
        elif success_count > 0:
            status = "partial"
            message = f"成功抓取 {success_count}/{len(urls)} 个网页，{error_count} 个失败"
        else:
            status = "error"
            message = f"所有 {len(urls)} 个网页抓取失败"

        return {
            "status": status,
            "message": message,
            "total_urls": len(urls),
            "success_count": success_count,
            "error_count": error_count,
            "results": results
        }

    async def _fetch_single(
        self,
        url: str,
        max_length: int,
        timeout: int,
        retries: int
    ) -> Dict[str, Any]:
        """抓取单个URL，带重试机制"""
        from scrapling.fetchers import AsyncFetcher

        last_error = None
        for attempt in range(retries + 1):
            try:
                # 创建异步 fetcher
                fetcher = AsyncFetcher()

                # 抓取页面（始终使用隐身模式）
                page = await fetcher.get(
                    url,
                    stealthy_headers=True,
                    timeout=timeout
                )

                # 提取标题
                title = page.css('title::text').get('')
                if not title:
                    title = page.css('h1::text').get('')
                if not title:
                    title = page.css('#activity-name::text').get('')

                # 提取正文内容
                # 尝试多种选择器，按优先级排序
                content_selectors = [
                    '#js_content',           # 微信公众号
                    '.rich_media_content',   # 微信公众号
                    'article',               # 标准文章标签
                    'main',                  # 主内容区
                    '[role="main"]',
                    '.content',              # 常见内容类名
                    '.article-content',
                    '.post-content',
                    '.entry-content',
                    '#content',
                    '.main-content',
                    'body'                   # 回退到 body
                ]

                content = ""
                used_selector = ""

                for selector in content_selectors:
                    elements = page.css(selector)
                    if elements:
                        # 使用 get_all_text() 获取元素的所有文本
                        texts = []
                        for elem in elements:
                            text = elem.get_all_text()
                            if text and len(text.strip()) > 50:  # 过滤短文本
                                texts.append(text.strip())

                        if texts:
                            content = '\n\n'.join(texts)
                            used_selector = selector
                            # 如果内容足够长，就使用这个选择器
                            if len(content) > 500:
                                break

                # 如果还是没有内容，使用整个页面的文本
                if not content:
                    content = page.get_all_text()
                    used_selector = "full_page"

                # 清理内容
                content = self._clean_content(content)

                # 截断内容
                if len(content) > max_length:
                    content = content[:max_length] + "\n\n[内容已截断，超过最大长度限制]"

                return {
                    "url": url,
                    "status": "success",
                    "content": content,
                    "metadata": {
                        "title": title,
                        "selector": used_selector,
                        "content_length": len(content)
                    }
                }

            except Exception as e:
                last_error = str(e)
                logger.warning(f"WebFetcher: {url} 抓取失败 (尝试 {attempt + 1}/{retries + 1}): {last_error}")

                if attempt < retries:
                    wait_time = 2 ** attempt  # 指数退避: 1, 2, 4 秒
                    await asyncio.sleep(wait_time)

        return {
            "url": url,
            "status": "error",
            "error": f"重试{retries + 1}次后仍失败: {last_error}",
            "content": None,
            "metadata": None
        }

    def _clean_content(self, text: str) -> str:
        """清理内容"""
        import re

        # 移除多余的空白行
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)

        # 移除行首行尾空白
        lines = [line.strip() for line in text.split('\n')]

        # 移除空行但保留段落间距
        cleaned_lines = []
        prev_empty = False
        for line in lines:
            if line:
                cleaned_lines.append(line)
                prev_empty = False
            elif not prev_empty:
                cleaned_lines.append('')
                prev_empty = True

        # 移除末尾空行
        while cleaned_lines and cleaned_lines[-1] == '':
            cleaned_lines.pop()

        return '\n'.join(cleaned_lines)
