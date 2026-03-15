"""
搜索引擎 Provider 模块

提供统一的搜索引擎接口，支持多个搜索提供商：
- SerpApi (searchapi.io)
- Serper (Google搜索)
- Tavily
- Brave
- Zhipu (智谱AI)
- Bocha (博查)
- Shuyan (数眼)

注: qveris 是工具搜索API，不是网页搜索引擎，未包含在内
"""

from typing import List, Optional, Tuple, Protocol
from dataclasses import dataclass
from enum import Enum


@dataclass
class SearchResult:
    """统一的搜索结果格式"""
    title: str
    url: str
    snippet: str
    source: str = ""


@dataclass
class ImageResult:
    """统一的图片搜索结果格式"""
    title: str
    image_url: str
    source: str = ""
    thumbnail_url: str = ""


class SearchProviderEnum(Enum):
    """支持的搜索引擎提供商枚举"""
    SERPAPI = "serpapi"    # searchapi.io
    SERPER = "serper"      # serper.dev
    TAVILY = "tavily"
    BRAVE = "brave"
    ZHIPU = "zhipu"        # 智谱AI
    BOCHA = "bocha"        # 博查
    SHUYAN = "shuyan"      # 数眼


# 导出所有模块
from .base import BaseSearchProvider
from .serpapi_provider import SerpApiProvider
from .serper_provider import SerperProvider
from .tavily_provider import TavilyProvider
from .brave_provider import BraveProvider
from .zhipu_provider import ZhipuProvider
from .bocha_provider import BochaProvider
from .shuyan_provider import ShuyanProvider


__all__ = [
    "SearchResult",
    "ImageResult",
    "BaseSearchProvider",
    "SearchProviderEnum",
    "SerpApiProvider",
    "SerperProvider",
    "TavilyProvider",
    "BraveProvider",
    "ZhipuProvider",
    "BochaProvider",
    "ShuyanProvider",
]
