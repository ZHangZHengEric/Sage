import asyncio
import aiohttp
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse
import re
from bs4 import BeautifulSoup
from ..tool_base import tool
from sagents.utils.logger import logger


class WebFetcherTool:
    """网页内容抓取工具集"""

    # 默认请求头，模拟浏览器行为
    DEFAULT_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Cache-Control': 'max-age=0',
    }

    # 需要移除的HTML标签
    REMOVE_TAGS = [
        'script', 'style', 'nav', 'header', 'footer', 'aside',
        'advertisement', 'ad', 'sidebar', 'menu', 'comment',
        'social-share', 'related-articles', 'recommended',
        'newsletter', 'subscribe', 'cookie-banner'
    ]

    @tool(
        description_i18n={
            "zh": "抓取一个或多个网页的内容，提取正文、标题等有价值的信息",
            "en": "Fetch content from one or more web pages, extracting main content, titles, etc.",
        },
        param_description_i18n={
            "urls": {"zh": "网页URL列表，支持单个URL字符串或URL列表", "en": "List of web page URLs, supports single URL string or list of URLs"},
            "max_length_per_url": {"zh": "每个URL返回的最大文本长度（字符数），默认5000", "en": "Maximum text length per URL (characters), default 5000"},
            "timeout": {"zh": "每个请求的超时时间（秒），默认30秒", "en": "Timeout per request (seconds), default 30"},
            "include_metadata": {"zh": "是否包含元数据（标题、描述、作者等），默认True", "en": "Whether to include metadata (title, description, author, etc.), default True"},
        }
    )
    async def fetch_webpages(
        self,
        urls: List[str],
        max_length_per_url: int = 5000,
        timeout: int = 30,
        include_metadata: bool = True
    ) -> Dict[str, Any]:
        """抓取网页内容

        Args:
            urls: 网页URL列表，可以是单个URL字符串或URL列表
            max_length_per_url: 每个URL返回的最大文本长度（字符数）
            timeout: 每个请求的超时时间（秒）
            include_metadata: 是否包含元数据

        Returns:
            Dict[str, Any]: 包含抓取结果的字典
        """
        # 标准化URL输入
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

        logger.info(f"WebFetcher: Starting to fetch {len(urls)} webpage(s)")

        # 并发抓取所有URL
        tasks = [
            self._fetch_single_url(url, max_length_per_url, timeout, include_metadata)
            for url in urls
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理结果
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

        # 构建返回结果
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
        include_metadata: bool
    ) -> Dict[str, Any]:
        """抓取单个URL的内容"""

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

        logger.debug(f"WebFetcher: Fetching {url}")

        try:
            timeout_obj = aiohttp.ClientTimeout(total=timeout)
            # 创建 SSL 上下文，允许我们在需要时跳过验证
            import ssl
            ssl_context = ssl.create_default_context()
            
            async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                async with session.get(url, headers=self.DEFAULT_HEADERS, allow_redirects=True, ssl=ssl_context) as response:
                    if response.status != 200:
                        return {
                            "url": url,
                            "status": "error",
                            "error": f"HTTP错误: {response.status}",
                            "content": None,
                            "metadata": None
                        }

                    # 获取内容类型
                    content_type = response.headers.get('Content-Type', '').lower()

                    # 只处理HTML内容
                    if 'text/html' not in content_type and 'application/xhtml' not in content_type:
                        return {
                            "url": url,
                            "status": "error",
                            "error": f"不支持的内容类型: {content_type}",
                            "content": None,
                            "metadata": None
                        }

                    # 读取HTML内容
                    html_content = await response.text()

                    # 解析内容
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

        # 提取元数据
        if include_metadata:
            result["metadata"] = self._extract_metadata(soup, url)

        # 移除不需要的标签
        for tag_name in self.REMOVE_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # 尝试找到主要内容区域
        main_content = None

        # 常见的正文容器选择器
        content_selectors = [
            'article',
            'main',
            '[role="main"]',
            '.content',
            '.article-content',
            '.post-content',
            '.entry-content',
            '#content',
            '#main-content',
            '.main-content',
            '.article-body',
            '.post-body',
            '.entry-body',
        ]

        for selector in content_selectors:
            main_content = soup.select_one(selector)
            if main_content:
                break

        # 如果没有找到主要内容区域，使用body
        if not main_content:
            main_content = soup.body

        if main_content:
            # 提取文本内容
            text = self._extract_text(main_content)

            # 清理文本
            text = self._clean_text(text)

            # 截断到最大长度
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

        # 尝试从 h1 获取标题（如果title为空或不合适）
        if not metadata["title"]:
            h1_tag = soup.find('h1')
            if h1_tag:
                metadata["title"] = h1_tag.get_text(strip=True)

        # 提取meta信息
        meta_selectors = [
            ('description', ['meta[name="description"]', 'meta[property="og:description"]']),
            ('author', ['meta[name="author"]', 'meta[property="og:author"]', 'meta[name="twitter:creator"]']),
            ('published_time', ['meta[property="article:published_time"]', 'meta[name="published_time"]']),
            ('site_name', ['meta[property="og:site_name"]', 'meta[name="application-name"]']),
        ]

        for key, selectors in meta_selectors:
            for selector in selectors:
                tag = soup.select_one(selector)
                if tag and tag.get('content'):
                    metadata[key] = tag['content'].strip()
                    break

        return metadata

    def _extract_text(self, element) -> str:
        """从HTML元素中提取文本，保留段落结构"""
        texts = []

        # 处理常见的块级元素
        for tag in element.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'div']):
            text = tag.get_text(strip=True)
            if text and len(text) > 10:  # 过滤太短的文本
                # 根据标签类型添加标记
                if tag.name.startswith('h'):
                    texts.append(f"\n{text}\n")
                elif tag.name == 'li':
                    texts.append(f"• {text}")
                else:
                    texts.append(text)

        if not texts:
            # 如果没有找到结构化内容，直接获取所有文本
            texts = [element.get_text(separator='\n', strip=True)]

        return '\n\n'.join(texts)

    def _clean_text(self, text: str) -> str:
        """清理文本内容"""
        # 移除多余的空白行
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        # 移除行首行尾的空白
        lines = [line.strip() for line in text.split('\n')]
        # 过滤空行但保留段落结构
        cleaned_lines = []
        for line in lines:
            if line or (cleaned_lines and cleaned_lines[-1] != ''):
                cleaned_lines.append(line)
        # 移除末尾的空行
        while cleaned_lines and cleaned_lines[-1] == '':
            cleaned_lines.pop()
        return '\n'.join(cleaned_lines)
