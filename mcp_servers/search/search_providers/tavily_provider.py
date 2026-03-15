"""
Tavily 搜索 Provider
"""

from typing import List
import httpx
from .base import BaseSearchProvider, SearchResult, ImageResult


class TavilyProvider(BaseSearchProvider):
    """Tavily 搜索 Provider"""
    
    name = "tavily"
    env_key = "TAVILY_API_KEY"
    supports_images = True
    supports_time_range = False  # Tavily 不直接支持时间范围筛选
    
    async def search_web(self, query: str, count: int, time_range: str = "") -> List[SearchResult]:
        """使用 Tavily 搜索"""
        endpoint = "https://api.tavily.com/search"
        
        payload = {
            "query": query,
            "max_results": min(count, 20),
            "search_depth": "basic"
        }
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                endpoint, headers=headers, json=payload, timeout=15.0
            )
            response.raise_for_status()
            data = response.json()
            
            results = []
            for item in data.get("results", []):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", ""),
                    source=item.get("source", "")
                ))
            return results
    
    async def search_images(self, query: str, count: int, time_range: str = "") -> List[ImageResult]:
        """使用 Tavily 搜索图片"""
        endpoint = "https://api.tavily.com/search"
        
        payload = {
            "query": query,
            "max_results": min(count, 20),
            "search_depth": "basic",
            "include_images": True
        }
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                endpoint, headers=headers, json=payload, timeout=15.0
            )
            response.raise_for_status()
            data = response.json()
            
            results = []
            for item in data.get("images", []):
                if isinstance(item, dict):
                    results.append(ImageResult(
                        title=item.get("description", ""),
                        image_url=item.get("url", ""),
                        source=""
                    ))
                elif isinstance(item, str):
                    results.append(ImageResult(
                        title="",
                        image_url=item,
                        source=""
                    ))
            return results
