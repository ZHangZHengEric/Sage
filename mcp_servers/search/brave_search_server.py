
import os
import json
import random
import asyncio
import logging
from typing import List, Optional, Dict, Any
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from mcp.server.fastmcp import FastMCP
from sagents.tool.mcp_tool_base import sage_mcp_tool

# Initialize FastMCP server
mcp = FastMCP("Brave Search Service")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("BraveSearch")

# Constants
BRAVE_SEARCH_URL = "https://search.brave.com/search"
BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"

# User-Agent list for rotation to mitigate anti-scraping
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/116.0",
]

def _get_headers() -> Dict[str, str]:
    """Generate headers to mimic a real browser."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }

async def _scrape_brave_search(query: str, count: int = 10) -> List[Dict[str, str]]:
    """Scrape results from Brave Search HTML."""
    results = []
    
    params = {"q": query}
    
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.get(BRAVE_SEARCH_URL, params=params, headers=_get_headers())
            
            if response.status_code != 200:
                logger.warning(f"Brave Search returned status {response.status_code}")
                return []
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find all search result snippets
            # Based on the JS script: div.snippet[data-type="web"]
            snippets = soup.find_all('div', class_='snippet', attrs={'data-type': 'web'})
            
            for snippet in snippets:
                if len(results) >= count:
                    break
                    
                # Title and Link
                # The JS script looks for 'a' tag. We look for the main link.
                # Usually it's the first 'a' tag in the snippet or one with a specific class.
                # Let's try to find the 'a' tag that contains the title.
                title_link = snippet.find('a')
                if not title_link or not title_link.get('href'):
                    continue
                    
                link = title_link.get('href')
                
                # Filter internal Brave links
                if 'brave.com' in link:
                    continue
                    
                # Title text
                # Try to find an element with class 'title' inside the link, or just use link text
                title_el = title_link.find(class_='title')
                title = title_el.get_text(strip=True) if title_el else title_link.get_text(strip=True)
                
                # Description/Snippet
                # JS script: .generic-snippet .content
                desc_el = snippet.select_one('.generic-snippet .content')
                # Fallback: look for other description containers if structure changed
                if not desc_el:
                    desc_el = snippet.find(class_='snippet-content') or snippet.find('div', style=lambda s: s and 'color' in s)
                
                snippet_text = desc_el.get_text(strip=True) if desc_el else ""
                
                # Remove date prefix if present (e.g., "Feb 13, 2026 - ...")
                # Simple heuristic: split by " - " if it starts with a date-like pattern
                # For now, we leave it as is or do simple cleanup
                
                if title and link:
                    results.append({
                        "title": title,
                        "link": link,
                        "snippet": snippet_text
                    })
                    
    except Exception as e:
        logger.error(f"Error scraping Brave Search: {e}")
        
    return results

async def _api_brave_search(query: str, api_key: str, count: int = 10) -> List[Dict[str, str]]:
    """Use Brave Search API."""
    results = []
    
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key
    }
    params = {"q": query, "count": min(count, 20)} # API max is usually 20 per page
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(BRAVE_API_URL, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                web_results = data.get('web', {}).get('results', [])
                
                for item in web_results:
                    if len(results) >= count:
                        break
                    results.append({
                        "title": item.get('title', ''),
                        "link": item.get('url', ''),
                        "snippet": item.get('description', '')
                    })
            else:
                logger.error(f"Brave API returned status {response.status_code}: {response.text}")
                
    except Exception as e:
        logger.error(f"Error calling Brave API: {e}")
        
    return results

@mcp.tool()
@sage_mcp_tool(server_name="brave_search")
async def brave_search(query: str, count: int = 10) -> str:
    """
    Search the web using Brave Search.
    
    [Effect]
    - Performs a web search for the given query.
    - Returns a list of results with titles, links, and snippets.
    
    [When to Use]
    - Use this tool when you need to find up-to-date information from the internet.
    - Use this as a general purpose search engine.
    - If the user asks for "search for X", use this tool.
    
    [Anti-Scraping / Rate Limits]
    - This tool automatically rotates User-Agents to mimic real browsers.
    - If you encounter blocking (e.g. empty results or errors), you can set the `BRAVE_SEARCH_API_KEY` environment variable to use the official API instead.
    
    Args:
        query: The search query.
        count: Number of results to return (default 10, max 20).
        
    Returns:
        JSON string containing list of search results.
    """
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    
    if api_key:
        logger.info("Using Brave Search API key.")
        results = await _api_brave_search(query, api_key, count)
    else:
        logger.info("Using Brave Search Scraping (Fallback).")
        # Add a small random delay to be polite and avoid burst detection
        await asyncio.sleep(random.uniform(0.5, 2.0))
        results = await _scrape_brave_search(query, count)
        
    return json.dumps(results, indent=2, ensure_ascii=False)

@mcp.tool()
@sage_mcp_tool(server_name="brave_search")
async def visit_page(url: str) -> str:
    """
    Visit a web page and extract its content as Markdown.
    
    [Effect]
    - Fetches the HTML of the given URL.
    - Cleans up the content (removes scripts, styles, ads).
    - Converts the main content to Markdown format.
    
    [When to Use]
    - Use this tool after performing a search to read the details of a specific search result.
    - Use this when the user provides a specific URL to analyze.
    
    Args:
        url: The URL to visit.
        
    Returns:
        String containing the page content in Markdown.
    """
    try:
        headers = _get_headers()
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code != 200:
                return f"Error: HTTP {response.status_code} - {response.reason_phrase}"
                
            html = response.text
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remove unwanted tags
            for tag in soup(["script", "style", "noscript", "iframe", "svg", "header", "footer", "nav", "aside"]):
                tag.decompose()
                
            # Try to find the main content area
            main_content = soup.find('main') or soup.find('article') or soup.find('div', class_='content') or soup.body
            
            if not main_content:
                return "Error: Could not extract main content from page."
                
            # Convert to Markdown
            # heading_style="atx" uses # headers
            content_md = md(str(main_content), heading_style="atx", strip=['a', 'img']) 
            # Note: strip=['a', 'img'] helps reduce noise if we just want text, but user might want links. 
            # Let's keep links but maybe strip images to save tokens?
            # For now, let's keep it simple and default behavior.
            content_md = md(str(main_content), heading_style="atx")
            
            # Post-processing cleanup
            # Remove excessive newlines
            import re
            content_md = re.sub(r'\n{3,}', '\n\n', content_md)
            
            # Truncate if too long (e.g. 20k chars) to avoid context overflow
            if len(content_md) > 20000:
                content_md = content_md[:20000] + "\n\n...(Content Truncated)..."
                
            return content_md.strip()
            
    except Exception as e:
        return f"Error visiting page: {str(e)}"

if __name__ == "__main__":
    mcp.run()
