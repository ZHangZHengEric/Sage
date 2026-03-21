"""
SerpApi 搜索 Provider
API: https://www.searchapi.io/api/v1/search
支持 Google 网页搜索和图片搜索，支持时间范围筛选
"""

from typing import List
import httpx
from .base import BaseSearchProvider, SearchResult, ImageResult


class SerpApiProvider(BaseSearchProvider):
    """SerpApi 搜索 Provider (searchapi.io)"""
    
    name = "serpapi"
    env_key = "SERPAPI_API_KEY"
    supports_images = True
    supports_time_range = True  # 支持时间范围筛选
    
    # 时间范围映射
    TIME_RANGE_MAP = {
        "day": "day",
        "week": "week",
        "month": "month",
        "year": "year",
    }

    @classmethod
    def get_required_env_vars(cls) -> dict:
        """获取必需的环境变量说明"""
        return {
            cls.env_key: {
                "description": "SerpApi Google搜索 API Key (searchapi.io)",
                "required": True,
                "url": "https://www.searchapi.io",
            },
        }

    @classmethod
    def get_config_example(cls) -> str:
        """获取配置示例"""
        return """# SerpApi (Google搜索)
export SERPAPI_API_KEY=your_api_key_here"""

    async def search_web(self, query: str, count: int, time_range: str = "") -> List[SearchResult]:
        """使用 SerpApi 搜索网页"""
        endpoint = "https://www.searchapi.io/api/v1/search"

        params = {
            "engine": "google",
            "q": query,
            "num": min(count, 100)
        }

        # 添加时间范围参数
        if time_range and time_range in self.TIME_RANGE_MAP:
            params["time_period"] = self.TIME_RANGE_MAP[time_range]

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                endpoint, headers=headers, params=params, timeout=15.0
            )
            if response.status_code == 401:
                raise Exception(f"SerpApi API Key 无效或已过期，请检查环境变量 {self.env_key}")
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("organic_results", []):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("link", ""),
                    snippet=item.get("snippet", ""),
                    source=item.get("displayed_link", "")
                ))
            return results
    
    async def search_images(self, query: str, count: int, time_range: str = "") -> List[ImageResult]:
        """使用 SerpApi 搜索图片"""
        endpoint = "https://www.searchapi.io/api/v1/search"

        params = {
            "engine": "google_images",
            "q": query,
            "num": min(count, 100)
        }

        # 添加时间范围参数
        if time_range and time_range in self.TIME_RANGE_MAP:
            params["time_period"] = self.TIME_RANGE_MAP[time_range]

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                endpoint, headers=headers, params=params, timeout=15.0
            )
            if response.status_code == 401:
                raise Exception(f"SerpApi API Key 无效或已过期，请检查环境变量 {self.env_key}")
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("images_results", []):
                results.append(ImageResult(
                    title=item.get("title", ""),
                    image_url=item.get("original", ""),
                    thumbnail_url=item.get("thumbnail", ""),
                    source=item.get("source", "")
                ))
            return results
