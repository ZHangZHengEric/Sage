"""
Zhipu (智谱AI) 搜索 Provider
"""

from typing import List
import httpx
from .base import BaseSearchProvider, SearchResult, ImageResult


class ZhipuProvider(BaseSearchProvider):
    """智谱AI 搜索 Provider"""
    
    name = "zhipu"
    env_key = "ZHIPU_API_KEY"
    supports_images = False
    supports_time_range = False  # 智谱不支持时间范围筛选
    
    async def search_web(self, query: str, count: int, time_range: str = "") -> List[SearchResult]:
        """使用智谱AI搜索"""
        endpoint = "https://open.bigmodel.cn/api/paas/v4/web_search"
        
        payload = {
            "search_query": query,
            "search_engine": "search_pro",
            "search_intent": False,
            "count": min(count, 50)
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
            for item in data.get("search_result", []):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("link", ""),
                    snippet=item.get("content", ""),
                    source=item.get("media", "")
                ))
            return results
    
    async def search_images(self, query: str, count: int, time_range: str = "") -> List[ImageResult]:
        """智谱AI暂不支持图片搜索"""
        return []
