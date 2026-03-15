"""
Brave 搜索 Provider
"""

from typing import List
import httpx
from .base import BaseSearchProvider, SearchResult, ImageResult


class BraveProvider(BaseSearchProvider):
    """Brave 搜索 Provider"""
    
    name = "brave"
    env_key = "BRAVE_API_KEY"
    supports_images = True
    supports_time_range = True  # 支持时间范围筛选
    
    # 时间范围映射
    TIME_RANGE_MAP = {
        "day": "day",
        "week": "week",
        "month": "month",
        "year": "year",
    }
    
    async def search_web(self, query: str, count: int, time_range: str = "") -> List[SearchResult]:
        """使用 Brave 搜索"""
        endpoint = "https://api.search.brave.com/res/v1/web/search"
        
        params = {
            "q": query,
            "count": min(count, 20)
        }
        
        # 添加时间范围参数
        if time_range and time_range in self.TIME_RANGE_MAP:
            params["freshness"] = self.TIME_RANGE_MAP[time_range]
        
        headers = {
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip',
            'X-Subscription-Token': self.api_key
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                endpoint, headers=headers, params=params, timeout=10.0
            )
            response.raise_for_status()
            data = response.json()
            
            results = []
            for item in data.get("web", {}).get("results", []):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("description", ""),
                    source=item.get("profile", {}).get("name", "")
                ))
            return results
    
    async def search_images(self, query: str, count: int, time_range: str = "") -> List[ImageResult]:
        """使用 Brave 搜索图片"""
        endpoint = "https://api.search.brave.com/res/v1/images/search"
        
        params = {
            "q": query,
            "count": min(count, 20)
        }
        
        # 添加时间范围参数
        if time_range and time_range in self.TIME_RANGE_MAP:
            params["freshness"] = self.TIME_RANGE_MAP[time_range]
        
        headers = {
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip',
            'X-Subscription-Token': self.api_key
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                endpoint, headers=headers, params=params, timeout=10.0
            )
            response.raise_for_status()
            data = response.json()
            
            results = []
            for item in data.get("results", []):
                results.append(ImageResult(
                    title=item.get("title", ""),
                    image_url=item.get("image", {}).get("url", ""),
                    thumbnail_url=item.get("thumbnail", {}).get("url", ""),
                    source=item.get("source", "")
                ))
            return results
