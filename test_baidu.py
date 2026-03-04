#!/usr/bin/env python3
"""测试抓取百度百家号文章"""

import asyncio
import sys
sys.path.insert(0, '/Users/zhangzheng/zavixai/Sage')

from sagents.tool.impl.web_fetcher_tool import WebFetcherTool

async def test_baidu():
    """测试抓取百度百家号"""
    tool = WebFetcherTool()
    
    url = "https://baijiahao.baidu.com/s?id=1858707449795620871&wfr=spider&for=pc"
    
    print("=" * 60)
    print(f"测试抓取: {url}")
    print("=" * 60)
    
    result = await tool.fetch_webpages(
        urls=url,
        max_length_per_url=3000,
        timeout=30,
        include_metadata=True
    )
    
    print(f"\n整体状态: {result['status']}")
    print(f"消息: {result['message']}")
    print(f"成功数: {result['success_count']}")
    print(f"失败数: {result['error_count']}")
    
    if result['results']:
        r = result['results'][0]
        print(f"\n--- 详细结果 ---")
        print(f"URL: {r['url']}")
        print(f"状态: {r['status']}")
        
        if r.get('error'):
            print(f"错误: {r['error']}")
        
        if r['metadata']:
            print(f"\n元数据:")
            for key, value in r['metadata'].items():
                if value:
                    print(f"  {key}: {value}")
        
        if r['content']:
            print(f"\n内容 (前500字符):")
            print(r['content'][:500])
            if len(r['content']) > 500:
                print(f"\n... [共 {len(r['content'])} 字符]")

if __name__ == "__main__":
    asyncio.run(test_baidu())
