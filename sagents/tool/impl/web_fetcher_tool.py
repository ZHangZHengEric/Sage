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
import os
import aiohttp
import aiofiles
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse, unquote
from ..tool_base import tool
from ..error_codes import ToolErrorCode as _ToolErrorCode, make_tool_error as _make_tool_error
from sagents.utils.logger import logger


class WebFetcherTool:
    """基于 Scrapling 的网页抓取工具，支持网页内容提取和文件下载"""

    # 总返回内容的最大token数限制
    MAX_TOTAL_TOKENS = 8000
    # 每个token大约对应的字符数（保守估计）
    CHARS_PER_TOKEN = 2.5

    # 常见文件扩展名映射
    FILE_EXTENSIONS = {
        '.pdf': 'document',
        '.doc': 'document', '.docx': 'document',
        '.xls': 'spreadsheet', '.xlsx': 'spreadsheet',
        '.ppt': 'presentation', '.pptx': 'presentation',
        '.txt': 'text',
        '.csv': 'spreadsheet',
        '.json': 'data',
        '.xml': 'data',
        '.zip': 'archive', '.rar': 'archive', '.7z': 'archive', '.tar': 'archive', '.gz': 'archive',
        '.jpg': 'image', '.jpeg': 'image', '.png': 'image', '.gif': 'image', '.bmp': 'image', '.webp': 'image','.svg':'image',
        '.mp3': 'audio', '.wav': 'audio', '.ogg': 'audio',
        '.mp4': 'video', '.avi': 'video', '.mov': 'video', '.mkv': 'video',
        '.exe': 'executable', '.dmg': 'executable', '.pkg': 'executable',
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
        with open(save_path, 'w', encoding='utf-8') as f:
            f.write(f"URL: {url}\n")
            f.write(f"Title: {title}\n")
            f.write(f"Selector: {used_selector}\n")
            f.write(f"Content Length: {len(full_content)}\n")
            f.write("=" * 80 + "\n\n")
            f.write(full_content)

    @tool(
        description_i18n={
            "zh": "使用 Scrapling 框架智能抓取网页内容或下载文件，支持自适应解析、反爬虫绕过和文件自动保存到工作空间",
            "en": "Intelligently fetch webpage content or download files using Scrapling framework with adaptive parsing, anti-bot bypass and auto-save to workspace",
        },
        param_description_i18n={
            "urls": {"zh": "网页URL列表，支持单个URL字符串或URL列表。支持HTML页面和文件下载", "en": "List of webpage URLs, supports single URL string or list of URLs. Supports HTML pages and file downloads"},
            "max_length_per_url": {"zh": "每个URL返回的最大文本长度（字符数），默认8000。仅适用于HTML页面", "en": "Maximum text length per URL (characters), default 8000. Only applies to HTML pages"},
            "timeout": {"zh": "每个请求的超时时间（秒），默认60秒", "en": "Timeout per request (seconds), default 60"},
            "retries": {"zh": "失败重试次数，默认2", "en": "Number of retries on failure, default 2"},
            "session_id": {"zh": "会话ID，用于确定Agent工作空间路径，文件将保存到该工作空间", "en": "Session ID for determining agent workspace path, files will be saved to this workspace"},
        }
    )
    async def fetch_webpages(
        self,
        urls: List[str],
        max_length_per_url: int = 8000,
        timeout: int = 30,
        retries: int = 1,
        session_id: Optional[str] = None
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
        logger.info(f"WebFetcher: Workspace path: {workspace_path}")
        logger.info(f"WebFetcher: Starting to fetch {len(urls)} URL(s) with Scrapling")

        # 计算每个HTML页面可以返回的最大字符数
        # 总字符数 = 8000 tokens * 2.5 chars/token = 20000 字符
        # 分配给每个HTML页面
        html_url_count = sum(1 for url in urls if self._detect_url_type(url) == 'html')
        if html_url_count > 0:
            max_total_chars = int(self.MAX_TOTAL_TOKENS * self.CHARS_PER_TOKEN)
            chars_per_html = max_total_chars // html_url_count
            logger.info(f"WebFetcher: {html_url_count} HTML URLs, {chars_per_html} chars per URL")
        else:
            chars_per_html = max_length_per_url

        # 定义单个URL的处理函数
        async def process_single_url(url: str) -> Dict[str, Any]:
            """处理单个URL的抓取或下载"""
            try:
                # 检测URL类型
                url_type = self._detect_url_type(url)
                
                if url_type == 'html':
                    # HTML页面，使用新的抓取逻辑（保存完整内容到文件，返回部分内容）
                    result = await self._fetch_single_html_with_save(
                        url, chars_per_html, workspace_path, timeout, retries
                    )
                else:
                    # 文件，使用下载逻辑
                    result = await self._download_file(url, workspace_path, timeout, retries)
                
                return result
            except Exception as e:
                logger.error(f"Fetch error for {url}: {e}")
                return {
                    "url": url,
                    "status": "error",
                    "error": str(e),
                    "content": None,
                    "metadata": None
                }

        # 并发处理所有URL
        logger.info(f"WebFetcher: Concurrently processing {len(urls)} URL(s)")
        tasks = [process_single_url(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        success_count = sum(1 for r in results if r.get("status") == "success")
        error_count = len(results) - success_count

        if success_count == len(urls):
            status = "success"
            message = f"成功处理所有 {len(urls)} 个URL"
        elif success_count > 0:
            status = "partial"
            message = f"成功处理 {success_count}/{len(urls)} 个URL，{error_count} 个失败"
        else:
            status = "error"
            message = f"所有 {len(urls)} 个URL处理失败"

        return {
            "status": status,
            "message": message,
            "total_urls": len(urls),
            "success_count": success_count,
            "error_count": error_count,
            "workspace": workspace_path,
            "results": results
        }

    def _detect_url_type(self, url: str) -> str:
        """检测URL类型是HTML页面还是文件"""
        parsed = urlparse(url)
        path = unquote(parsed.path)
        
        # 获取文件扩展名
        ext = os.path.splitext(path.lower())[1]
        
        if ext in self.FILE_EXTENSIONS:
            return 'file'
        
        # 没有扩展名或常见HTML扩展名，视为HTML
        return 'html'

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
                workspace = os.path.join(sandbox_agent_workspace, "downloads")
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
        self,
        url: str,
        save_dir: str,
        timeout: int,
        retries: int
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
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                        if response.status != 200:
                            raise Exception(f"HTTP {response.status}")
                        
                        # 获取文件大小
                        content_length = response.headers.get('Content-Length')
                        if content_length:
                            size_mb = int(content_length) / (1024 * 1024)
                            if size_mb > 100:  # 限制100MB
                                raise Exception(f"文件过大 ({size_mb:.1f}MB)，超过100MB限制")
                        
                        # 下载文件
                        async with aiofiles.open(save_path, 'wb') as f:
                            async for chunk in response.content.iter_chunked(8192):
                                await f.write(chunk)
                
                # 获取文件信息
                file_size = os.path.getsize(save_path)
                file_type = self.FILE_EXTENSIONS.get(os.path.splitext(filename)[1].lower(), 'unknown')
                
                return {
                    "url": url,
                    "status": "success",
                    "type": "file",
                    "content": f"文件已下载到: {save_path}",
                    "metadata": {
                        "filename": filename,
                        "save_path": save_path,
                        "file_size": file_size,
                        "file_size_human": self._format_file_size(file_size),
                        "file_type": file_type,
                    }
                }
                
            except Exception as e:
                last_error = str(e)
                logger.warning(f"WebFetcher: Download failed for {url} (尝试 {attempt + 1}/{retries + 1}): {last_error}")
                
                if attempt < retries:
                    wait_time = 2 ** attempt
                    await asyncio.sleep(wait_time)

        return {
            "url": url,
            "status": "error",
            "error": f"下载失败，重试{retries + 1}次后仍失败: {last_error}",
            "content": None,
            "metadata": None
        }

    def _get_extension_from_url(self, url: str) -> str:
        """从URL获取文件扩展名"""
        parsed = urlparse(url)
        path = unquote(parsed.path)
        ext = os.path.splitext(path)[1]
        return ext if ext else '.bin'

    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名，移除不安全字符"""
        import re
        # 移除路径分隔符和其他不安全字符
        filename = re.sub(r'[\\/*?:"<>|]', '_', filename)
        # 限制长度
        if len(filename) > 200:
            name, ext = os.path.splitext(filename)
            filename = name[:200 - len(ext)] + ext
        return filename

    def _format_file_size(self, size_bytes: int) -> str:
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.2f} TB"

    async def _fetch_single_html_with_save(
        self,
        url: str,
        max_return_length: int,
        save_dir: str,
        timeout: int,
        retries: int
    ) -> Dict[str, Any]:
        """抓取单个HTML页面，保存完整内容到文件，返回部分内容"""
        from scrapling.fetchers import AsyncFetcher

        last_error = None
        for attempt in range(retries + 1):
            try:
                # 创建异步 fetcher
                fetcher = AsyncFetcher()

                # 抓取页面（始终使用隐身模式）
                page = await asyncio.wait_for(
                    fetcher.get(
                        url,
                        stealthy_headers=True,
                        timeout=timeout
                    ),
                    timeout=timeout + 5
                )

                # 提取标题
                title = page.css('title::text').get('')
                if not title:
                    title = page.css('h1::text').get('')
                if not title:
                    title = page.css('#activity-name::text').get('')

                # 提取正文内容
                content_selectors = [
                    '#js_content',
                    '.rich_media_content',
                    'article',
                    'main',
                    '[role="main"]',
                    '.content',
                    '.article-content',
                    '.post-content',
                    '.entry-content',
                    '#content',
                    '.main-content',
                    'body'
                ]

                full_content = ""
                used_selector = ""

                for selector in content_selectors:
                    elements = page.css(selector)
                    if elements:
                        texts = []
                        for elem in elements:
                            text = elem.get_all_text()
                            if text and len(text.strip()) > 50:
                                texts.append(text.strip())

                        if texts:
                            full_content = '\n\n'.join(texts)
                            used_selector = selector
                            if len(full_content) > 500:
                                break

                if not full_content:
                    full_content = page.get_all_text()
                    used_selector = "full_page"

                # 清理内容
                full_content = self._clean_content(full_content)

                # 生成文件名
                from urllib.parse import urlparse
                parsed = urlparse(url)
                domain = parsed.netloc.replace(':', '_')
                safe_title = self._sanitize_filename(title[:50] if title else 'untitled')
                filename = f"{domain}_{safe_title}.txt"
                
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
                    return_content = full_content[:max_return_length] + f"\n\n[内容已截断，完整内容已保存到文件: {save_path}]"
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
                        "filename": filename
                    }
                }

            except asyncio.TimeoutError:
                last_error = f"请求超时（超过 {timeout} 秒）"
                logger.warning(f"WebFetcher: {url} 请求超时 (尝试 {attempt + 1}/{retries + 1})")
            except Exception as e:
                last_error = str(e)
                logger.warning(f"WebFetcher: {url} 抓取失败 (尝试 {attempt + 1}/{retries + 1}): {last_error}")

                if attempt < retries:
                    wait_time = 2 ** attempt
                    await asyncio.sleep(wait_time)

        return {
            "url": url,
            "status": "error",
            "error": f"重试{retries + 1}次后仍失败: {last_error}",
            "content": None,
            "metadata": None
        }

    async def _fetch_single_html(
        self,
        url: str,
        max_length: int,
        timeout: int,
        retries: int
    ) -> Dict[str, Any]:
        """抓取单个HTML页面，带重试机制和严格超时控制"""
        from scrapling.fetchers import AsyncFetcher

        last_error = None
        for attempt in range(retries + 1):
            try:
                # 创建异步 fetcher
                fetcher = AsyncFetcher()

                # 抓取页面（始终使用隐身模式）
                # 使用 asyncio.wait_for 包装，确保整体超时控制
                page = await asyncio.wait_for(
                    fetcher.get(
                        url,
                        stealthy_headers=True,
                        timeout=timeout
                    ),
                    timeout=timeout + 5  # 给一些缓冲时间
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
                    "type": "html",
                    "content": content,
                    "metadata": {
                        "title": title,
                        "selector": used_selector,
                        "content_length": len(content)
                    }
                }

            except asyncio.TimeoutError:
                last_error = f"请求超时（超过 {timeout} 秒）"
                logger.warning(f"WebFetcher: {url} 请求超时 (尝试 {attempt + 1}/{retries + 1})")
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
