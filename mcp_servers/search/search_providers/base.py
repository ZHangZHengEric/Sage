"""
搜索引擎 Provider 基类
"""

from typing import List
from dataclasses import dataclass


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


class BaseSearchProvider:
    """搜索引擎 Provider 基类"""

    name: str = ""
    env_key: str = ""
    supports_images: bool = False  # 是否支持图片搜索
    supports_time_range: bool = False  # 是否支持时间范围筛选

    def __init__(self, api_key: str):
        self.api_key = api_key

    @classmethod
    def get_required_env_vars(cls) -> dict:
        """
        获取必需的环境变量说明

        Returns:
            dict: 环境变量名 -> {description, required, url}
        """
        raise NotImplementedError

    @classmethod
    def get_config_example(cls) -> str:
        """
        获取配置示例，子类应该重写此方法

        Returns:
            str: 配置示例字符串
        """
        raise NotImplementedError

    async def search_web(self, query: str, count: int, time_range: str = "") -> List[SearchResult]:
        """
        执行网页搜索，子类必须实现
        
        Args:
            query: 搜索查询
            count: 返回结果数量
            time_range: 时间范围 (day, week, month, year, 空字符串表示不限)
        """
        raise NotImplementedError
    
    async def search_images(self, query: str, count: int, time_range: str = "") -> List[ImageResult]:
        """
        执行图片搜索，子类必须实现（如果 supports_images=True）
        
        Args:
            query: 搜索查询
            count: 返回结果数量
            time_range: 时间范围 (day, week, month, year, 空字符串表示不限)
        """
        raise NotImplementedError
