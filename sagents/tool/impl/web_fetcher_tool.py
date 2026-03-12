import asyncio
import aiohttp
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse
import re
import random
import ssl
from bs4 import BeautifulSoup
from ..tool_base import tool
from sagents.utils.logger import logger


class WebFetcherTool:
    """网页内容抓取工具集 - 支持重试、隐身模式和智能解析"""

    # 需要移除的HTML标签
    REMOVE_TAGS = [
        'script', 'style', 'nav', 'header', 'footer', 'aside',
        'advertisement', 'ad', 'sidebar', 'menu', 'comment',
        'social-share', 'related-articles', 'recommended',
        'newsletter', 'subscribe', 'cookie-banner', 'iframe',
        'noscript', 'form', 'button', 'input'
    ]

    # 常见的内容选择器
    CONTENT_SELECTORS = [
        'article', 'main', '[role="main"]',
        '.content', '.article-content', '.post-content', '.entry-content',
        '#content', '#main-content', '.main-content',
        '.article-body', '.post-body', '.entry-body',
        '.story', '.story-body', '#article-body',
        '.text-content', '.article__body'
    ]

    def _get_random_user_agent(self) -> str:
        """生成随机的 User-Agent"""
        user_agents = [
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1',
            'Mozilla/5.0 (iPad; CPU OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1',
        ]
        return random.choice(user_agents)

    def _get_default_headers(self) -> Dict[str, str]:
        """获取默认请求头"""
        return {
            'User-Agent': self._get_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'DNT': '1',
        }

    @tool(
        description_i18n={
            "zh": "抓取一个或多个网页的内容，提取正文、标题等有价值的信息。支持隐身模式以绕过反爬虫机制",
            "en": "Fetch content from one or more web pages, extracting main content, titles, etc. Supports stealth mode to bypass anti-scraping",
        },
        param_description_i18n={
            "urls": {"zh": "网页URL列表，支持单个URL字符串或URL列表", "en": "List of web page URLs, supports single URL string or list of URLs"},
            "max_length_per_url": {"zh": "每个URL返回的最大文本长度（字符数），默认8000", "en": "Maximum text length per URL (characters), default 8000"},
            "timeout": {"zh": "每个请求的超时时间（秒），默认60秒", "en": "Timeout per request (seconds), default 60"},
            "include_metadata": {"zh": "是否包含元数据（标题、描述、作者等），默认True", "en": "Whether to include metadata (title, description, author, etc.), default True"},
            "stealth": {"zh": "是否使用隐身模式（模拟真实浏览器），默认True", "en": "Whether to use stealth mode (simulate real browser), default True"},
            "retries": {"zh": "失败重试次数，默认2", "en": "Number of retries on failure, default 2"},
        }
    )
    async def fetch_webpages(
        self,
        urls: List[str],
        max_length_per_url: int = 8000,
        timeout: int = 60,
        include_metadata: bool = True,
        stealth: bool = True,
        retries: int = 2
    ) -> Dict[str, Any]:
        """抓取网页内容

        Args:
            urls: 网页URL列表，可以是单个URL字符串或URL列表
            max_length_per_url: 每个URL返回的最大文本长度（字符数）
            timeout: 每个请求的超时时间（秒）
            include_metadata: 是否包含元数据
            stealth: 是否使用隐身模式（模拟真实浏览器）
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

        logger.info(f"WebFetcher: Starting to fetch {len(urls)} webpage(s), stealth={stealth}, retries={retries}")

        tasks = [
            self._fetch_single_url(url, max_length_per_url, timeout, include_metadata, stealth, retries)
            for url in urls
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_results = []
        success_count = 0
        error_count = 0

        for i, result in enumerate(results):
            url = urls[i]
            if isinstance(result, Exception):
                error_count += 1
                processed_results.append({
                    "url": url,
                    "status": "error",
                    "error": str(result),
                    "content": None,
                    "metadata": None
                })
            else:
                if result.get("status") == "success":
                    success_count += 1
                else:
                    error_count += 1
                processed_results.append(result)

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
            "results": processed_results
        }

    async def _fetch_single_url(
        self,
        url: str,
        max_length: int,
        timeout: int,
        include_metadata: bool,
        stealth: bool,
        retries: int
    ) -> Dict[str, Any]:
        """抓取单个URL的内容，带重试机制"""

        # 验证URL
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        try:
            parsed = urlparse(url)
            if not parsed.netloc:
                return {
                    "url": url,
                    "status": "error",
                    "error": "无效的URL格式",
                    "content": None,
                    "metadata": None
                }
        except Exception as e:
            return {
                "url": url,
                "status": "error",
                "error": f"URL解析错误: {str(e)}",
                "content": None,
                "metadata": None
            }

        # 重试循环
        last_error = None
        for attempt in range(retries + 1):
            try:
                result = await self._do_fetch(url, max_length, timeout, include_metadata, stealth)
                if result.get("status") == "success":
                    return result
                last_error = result.get("error", "未知错误")
            except Exception as e:
                last_error = str(e)

            if attempt < retries:
                wait_time = 2 ** attempt  # 指数退避: 1, 2, 4 秒
                logger.warning(f"WebFetcher: {url} 抓取失败 (尝试 {attempt + 1}/{retries + 1})，{wait_time}秒后重试: {last_error}")
                await asyncio.sleep(wait_time)

        return {
            "url": url,
            "status": "error",
            "error": f"重试{retries + 1}次后仍失败: {last_error}",
            "content": None,
            "metadata": None
        }

    async def _do_fetch(
        self,
        url: str,
        max_length: int,
        timeout: int,
        include_metadata: bool,
        stealth: bool
    ) -> Dict[str, Any]:
        """执行实际的网页抓取"""
        logger.debug(f"WebFetcher: Fetching {url} (stealth={stealth})")

        # 创建SSL上下文
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED

        # 如果不是隐身模式，可以禁用SSL验证（用于调试）
        # ssl_context.check_hostname = False
        # ssl_context.verify_mode = ssl.CERT_NONE

        timeout_obj = aiohttp.ClientTimeout(
            total=timeout,
            connect=timeout / 2,
            sock_read=timeout / 2
        )

        headers = self._get_default_headers()

        # 如果是隐身模式，添加更多请求头
        if stealth:
            headers.update({
                'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"macOS"',
            })

        try:
            async with aiohttp.ClientSession(timeout=timeout_obj, trust_env=True) as session:
                async with session.get(
                    url,
                    headers=headers,
                    allow_redirects=True,
                    ssl=ssl_context
                ) as response:

                    if response.status == 403:
                        return {
                            "url": url,
                            "status": "error",
                            "error": "HTTP 403 禁止访问 - 网站拒绝了请求，可能需要隐身模式",
                            "content": None,
                            "metadata": None
                        }

                    if response.status == 429:
                        return {
                            "url": url,
                            "status": "error",
                            "error": "HTTP 429 请求过多 - 网站限流中",
                            "content": None,
                            "metadata": None
                        }

                    if response.status != 200:
                        return {
                            "url": url,
                            "status": "error",
                            "error": f"HTTP错误: {response.status}",
                            "content": None,
                            "metadata": None
                        }

                    content_type = response.headers.get('Content-Type', '').lower()

                    if 'text/html' not in content_type and 'application/xhtml' not in content_type:
                        return {
                            "url": url,
                            "status": "error",
                            "error": f"不支持的内容类型: {content_type}",
                            "content": None,
                            "metadata": None
                        }

                    html_content = await response.text()

                    # 检测是否被反爬虫拦截
                    if self._is_blocked(html_content):
                        return {
                            "url": url,
                            "status": "error",
                            "error": "检测到反爬虫拦截页面，建议使用隐身模式或更换代理",
                            "content": None,
                            "metadata": None
                        }

                    result = self._parse_html(html_content, url, max_length, include_metadata)
                    result["status"] = "success"

                    return result

        except asyncio.TimeoutError:
            return {
                "url": url,
                "status": "error",
                "error": f"请求超时（{timeout}秒）",
                "content": None,
                "metadata": None
            }
        except aiohttp.ClientError as e:
            return {
                "url": url,
                "status": "error",
                "error": f"网络请求错误: {str(e)}",
                "content": None,
                "metadata": None
            }
        except Exception as e:
            logger.error(f"WebFetcher: Error fetching {url}: {e}", exc_info=True)
            return {
                "url": url,
                "status": "error",
                "error": f"抓取错误: {str(e)}",
                "content": None,
                "metadata": None
            }

    def _is_blocked(self, html: str) -> bool:
        """检测是否被反爬虫拦截"""
        # 常见的反爬虫页面特征
        blocked_patterns = [
            'captcha', 'verify', 'blocked', 'forbidden',
            'access denied', 'denied access',
            '请验证', '验证码', '访问受限',
            'robot', 'spider', 'scraper'
        ]

        html_lower = html.lower()

        # 检查标题
        title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).lower()
            for pattern in blocked_patterns:
                if pattern in title:
                    return True

        # 检查内容
        for pattern in blocked_patterns:
            if pattern in html_lower:
                # 进一步检查是否是主要内容
                content_start = html_lower.find('<body')
                if content_start > 0:
                    body_content = html_lower[content_start:content_start + 5000]
                    if pattern in body_content:
                        return True

        return False

    def _parse_html(
        self,
        html: str,
        url: str,
        max_length: int,
        include_metadata: bool
    ) -> Dict[str, Any]:
        """解析HTML内容，提取正文和元数据"""

        soup = BeautifulSoup(html, 'lxml')

        result = {
            "url": url,
            "content": "",
            "metadata": {}
        }

        if include_metadata:
            result["metadata"] = self._extract_metadata(soup, url)

        # 移除不需要的标签
        for tag_name in self.REMOVE_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # 尝试找到主要内容区域
        main_content = None

        for selector in self.CONTENT_SELECTORS:
            main_content = soup.select_one(selector)
            if main_content:
                break

        if not main_content:
            main_content = soup.body

        if main_content:
            text = self._extract_text(main_content)
            text = self._clean_text(text)

            if len(text) > max_length:
                text = text[:max_length] + "\n\n[内容已截断，超过最大长度限制]"

            result["content"] = text
        else:
            result["content"] = "[无法提取正文内容]"

        return result

    def _extract_metadata(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """提取页面元数据"""
        metadata = {
            "title": "",
            "description": "",
            "author": "",
            "published_time": "",
            "site_name": "",
            "url": url
        }

        # 提取标题
        title_tag = soup.find('title')
        if title_tag:
            metadata["title"] = title_tag.get_text(strip=True)

        if not metadata["title"]:
            h1_tag = soup.find('h1')
            if h1_tag:
                metadata["title"] = h1_tag.get_text(strip=True)

        # 提取meta信息
        meta_mappings = [
            ('description', [
                'meta[name="description"]',
                'meta[property="og:description"]',
                'meta[name="twitter:description"]'
            ]),
            ('author', [
                'meta[name="author"]',
                'meta[property="og:author"]',
                'meta[name="twitter:creator"]'
            ]),
            ('published_time', [
                'meta[property="article:published_time"]',
                'meta[name="published_time"]',
                'meta[property="og:updated_time"]'
            ]),
            ('site_name', [
                'meta[property="og:site_name"]',
                'meta[name="application-name"]'
            ]),
        ]

        for key, selectors in meta_mappings:
            for selector in selectors:
                tag = soup.select_one(selector)
                if tag and tag.get('content'):
                    metadata[key] = tag['content'].strip()
                    break

        return metadata

    def _extract_text(self, element) -> str:
        """从HTML元素中提取文本"""
        texts = []

        for tag in element.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'div', 'section', 'article']):
            text = tag.get_text(strip=True)
            if text and len(text) > 10:
                if tag.name.startswith('h'):
                    texts.append(f"\n## {text}\n")
                elif tag.name == 'li':
                    texts.append(f"• {text}")
                else:
                    texts.append(text)

        if not texts:
            texts = [element.get_text(separator='\n', strip=True)]

        return '\n\n'.join(texts)

    def _clean_text(self, text: str) -> str:
        """清理文本内容"""
        # 移除多余的空白行
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)

        lines = [line.strip() for line in text.split('\n')]
        cleaned_lines = []
        for line in lines:
            if line or (cleaned_lines and cleaned_lines[-1] != ''):
                cleaned_lines.append(line)

        while cleaned_lines and cleaned_lines[-1] == '':
            cleaned_lines.pop()

        return '\n'.join(cleaned_lines)
