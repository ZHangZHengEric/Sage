import argparse
import os

import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Mount

mcp = FastMCP("Serper Search")

parser = argparse.ArgumentParser(description='启动 MCP Server 并传入 API Key')
parser.add_argument('--api_key', type=str, help='serper API Key')
args = parser.parse_args()

# 返回提取的内容，以及内容的长度


@mcp.tool()
async def search_web_page(
    query: str,
    date_range: str = None,
    count: int = 10,
    page_index: int = 1,
    country: str = None,
    language: str = None,
) -> str:
    """
    Search the web using the google API. 
    It has a better effect when searching for non-Chinese content, and it can also search for Chinese content currently.
    The results are returned in a list of dictionaries, each dictionary contains the following keys:
        title: The title of the page
        url: The url of the page
        snippet: The summary of the page, it does not contain the full text of the page, if you need the full text, you can use the url to get the full text.

    Args:
        query: Search query (required)
        date_range: The time range for the search results. (Available options qdr:h , qdr:d, qdr:w, qdr:m, qdr:y. Default is None)
        count: Number of results (1-50, default 10)
        page_index: The page number of the search results. (default 1)
        country: The country code for the search results. (default None for united states, otherwise use the country code, e.g. cn, jp, etc. )
        language: The language code for the search results. (default None for english, otherwise use the language code, e.g. zh, ja, etc. )

    Returns:
        List[Dict[str, Any]]: A list of dictionaries containing the search results.
    """
    # Get API key from environment
    serper_api_key = os.environ.get("SERPER_API_KEY", args.api_key)

    if not serper_api_key:
        return (
            "Error: SERPER API key is not configured. Please set the "
            "SERPER_API_KEY environment variable."
        )

    # Endpoint
    endpoint = "https://google.serper.dev/search"

    try:
        payload = {
            "q": query,
        }
        if date_range:
            payload["tbs"] = date_range
        if count:
            payload["num"] = count
        if page_index > 1:
            payload["page"] = page_index
        if country:
            payload["gl"] = country
        if language:
            payload["hl"] = language

        headers = {
            'X-API-KEY': serper_api_key,
            'Content-Type': 'application/json'
        }
        print(f'search payload: {payload}')
        async with httpx.AsyncClient() as client:
            response = await client.post(
                endpoint, headers=headers, json=payload, timeout=10.0
            )

            response.raise_for_status()
            data = response.json()
            # print(f'search response: {data}')

            if "organic" not in data:
                return "No results found."

            results = []
            for result in data["organic"]:
                results.append(
                    {
                        "title": result["title"],
                        "url": result["link"],
                        "snippet": result["snippet"],
                    }
                )
            return results

    except httpx.HTTPStatusError as e:
        return f"Bocha Web Search API HTTP error occurred: {e.response.status_code} - {e.response.text}"
    except httpx.RequestError as e:
        return f"Error communicating with Bocha Web Search API: {str(e)}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"


@mcp.tool()
async def search_image_from_web(query: str, date_range: str = None, country: str = None, count: int = 10):
    """ this tool is used to search images from web.
    The results are returned in a list of dictionaries, each dictionary contains the following keys:
        title: The title of the image
        image_url: The url of the image
    Args:
        query: Search query (required)
        count: Number of results (1-50, default 10)
        date_range: The time range for the search results. (Available options qdr:h, qdr:d, qdr:w, qdr:m, qdr:y. Default is None)
        country: The country code for the search results. (default None for united states, otherwise use the country code, e.g. cn, jp, etc. )
    Returns:
        List[Dict[str, Any]]: A list of dictionaries containing the search results.
    """
    # Get API key from environment
    serper_api_key = os.environ.get("SERPER_API_KEY", args.api_key)
    if not serper_api_key:
        return (
            "Error: SERPER API key is not configured. Please set the "
            "SERPER_API_KEY environment variable."
        )
    # Endpoint
    url = "https://google.serper.dev/images"

    try:
        payload = {
            "q": query,
        }
        if date_range:
            payload["tbs"] = date_range
        if count:
            payload["num"] = count
        if country:
            payload["gl"] = country
        headers = {
            "X-API-KEY": serper_api_key,
            "Content-Type": "application/json",
        }
        print(f'search payload: {payload}')
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, headers=headers, json=payload, timeout=10.0
            )

            response.raise_for_status()
            data = response.json()
            # print(f'search response: {data}')

            if "images" not in data:
                return "No results found."

            results = []
            for result in data["images"]:
                results.append(
                    {
                        "title": result["title"],
                        "image_url": result["imageUrl"],
                    }
                )
            return results

    except httpx.HTTPStatusError as e:
        return f"Bocha Web Search API HTTP error occurred: {e.response.status_code} - {e.response.text}"
    except httpx.RequestError as e:
        return f"Error communicating with Bocha Web Search API: {str(e)}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"

if __name__ == "__main__":
    app = Starlette(
        routes=[
            Mount('/', app=mcp.sse_app()),
        ]
    )
    uvicorn.run(app, host="0.0.0.0", port=34011)
    # result  =  asyncio.run(web_search("长跑运动中需要关注的指标"))
    # print(result)

    # mcp.run(transport='stdio')
