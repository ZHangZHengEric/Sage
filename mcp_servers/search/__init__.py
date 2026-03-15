"""
统一搜索 MCP 服务器

提供网页搜索和图片搜索功能，支持多个搜索引擎：
- SerpApi
- Serper
- Tavily
- Brave
- Zhipu(智谱)
- Bocha(博查)
- Shuyan(数眼)
"""

from .unified_search_server import search_web_page, search_image_from_web

__all__ = ["search_web_page", "search_image_from_web"]
