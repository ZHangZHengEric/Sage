"""
Bocha (博查) 搜索 Provider
API文档: https://api.bocha.cn/v1/web-search
"""

from typing import List
import httpx
from .base import BaseSearchProvider, SearchResult, ImageResult


class BochaProvider(BaseSearchProvider):
    """博查搜索 Provider"""
    
    name = "bocha"
    env_key = "BOCHA_API_KEY"
    supports_images = True
    supports_time_range = True  # 支持时间范围筛选
    
    # 时间范围映射
    TIME_RANGE_MAP = {
        "day": "oneDay",
        "week": "oneWeek",
        "month": "oneMonth",
        "year": "oneYear",
    }
    
    async def search_web(self, query: str, count: int, time_range: str = "") -> List[SearchResult]:
        """使用博查搜索网页"""
        endpoint = "https://api.bocha.cn/v1/web-search"
        
        payload = {
            "query": query,
            "freshness": "noLimit",
            "summary": False,
            "count": min(count, 50)
        }
        
        # 添加时间范围参数
        if time_range and time_range in self.TIME_RANGE_MAP:
            payload["freshness"] = self.TIME_RANGE_MAP[time_range]
        
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                endpoint, headers=headers, json=payload, timeout=15.0
            )
            response.raise_for_status()
            result = response.json()
            
            # 检查响应码
            if result.get("code") != 200:
                error_msg = result.get("msg", "未知错误")
                raise Exception(f"博查搜索API错误: {error_msg}")
            
            data = result.get("data", {})
            web_pages = data.get("webPages", {})
            items = web_pages.get("value", [])
            
            results = []
            for item in items:
                results.append(SearchResult(
                    title=item.get("name", ""),
                    url=item.get("url", ""),
                    snippet=item.get("snippet", ""),
                    source=item.get("siteName", "")
                ))
            return results
    
    async def search_images(self, query: str, count: int, time_range: str = "") -> List[ImageResult]:
        """使用博查搜索图片"""
        endpoint = "https://api.bocha.cn/v1/web-search"
        
        payload = {
            "query": query,
            "freshness": "noLimit",
            "summary": False,
            "count": min(count, 50)
        }
        
        # 添加时间范围参数
        if time_range and time_range in self.TIME_RANGE_MAP:
            payload["freshness"] = self.TIME_RANGE_MAP[time_range]
        
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                endpoint, headers=headers, json=payload, timeout=15.0
            )
            response.raise_for_status()
            result = response.json()
            
            # 检查响应码
            if result.get("code") != 200:
                error_msg = result.get("msg", "未知错误")
                raise Exception(f"博查搜索API错误: {error_msg}")
            
            data = result.get("data", {})
            images = data.get("images", {})
            items = images.get("value", [])
            
            results = []
            for item in items:
                results.append(ImageResult(
                    title=item.get("name", ""),
                    image_url=item.get("contentUrl", ""),
                    thumbnail_url=item.get("thumbnailUrl", ""),
                    source=item.get("hostPageUrl", "")
                ))
            return results
