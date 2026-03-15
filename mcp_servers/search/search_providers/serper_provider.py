"""
Serper (Google) 搜索 Provider
"""

from typing import List
import httpx
from .base import BaseSearchProvider, SearchResult, ImageResult


class SerperProvider(BaseSearchProvider):
    """Serper (Google) 搜索 Provider"""
    
    name = "serper"
    env_key = "SERPER_API_KEY"
    supports_images = True
    supports_time_range = True  # 支持时间范围筛选
    
    # 时间范围映射 (Serper 使用 tbs 参数)
    TIME_RANGE_MAP = {
        "day": "qdr:d",
        "week": "qdr:w",
        "month": "qdr:m",
        "year": "qdr:y",
    }
    
    async def search_web(self, query: str, count: int, time_range: str = "") -> List[SearchResult]:
        """使用 Serper (Google) 搜索"""
        endpoint = "https://google.serper.dev/search"

        payload = {
            "q": query,
            "num": min(count, 50)
        }

        # 添加时间范围参数
        if time_range and time_range in self.TIME_RANGE_MAP:
            payload["tbs"] = self.TIME_RANGE_MAP[time_range]

        headers = {
            'X-API-KEY': self.api_key,
            'Content-Type': 'application/json'
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                endpoint, headers=headers, json=payload, timeout=10.0
            )
            if response.status_code == 401 or response.status_code == 403:
                raise Exception(f"Serper API Key 无效或没有权限，请检查环境变量 {self.env_key}")
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("organic", []):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("link", ""),
                    snippet=item.get("snippet", ""),
                    source=item.get("source", "")
                ))
            return results
    
    async def search_images(self, query: str, count: int, time_range: str = "") -> List[ImageResult]:
        """使用 Serper 搜索图片"""
        endpoint = "https://google.serper.dev/images"

        payload = {
            "q": query,
            "num": min(count, 50)
        }

        # 添加时间范围参数
        if time_range and time_range in self.TIME_RANGE_MAP:
            payload["tbs"] = self.TIME_RANGE_MAP[time_range]

        headers = {
            'X-API-KEY': self.api_key,
            'Content-Type': 'application/json'
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                endpoint, headers=headers, json=payload, timeout=10.0
            )
            if response.status_code == 401 or response.status_code == 403:
                raise Exception(f"Serper API Key 无效或没有权限，请检查环境变量 {self.env_key}")
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("images", []):
                results.append(ImageResult(
                    title=item.get("title", ""),
                    image_url=item.get("imageUrl", ""),
                    thumbnail_url=item.get("thumbnailUrl", ""),
                    source=item.get("source", "")
                ))
            return results
