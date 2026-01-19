import asyncio
import json
import time
import uuid
import argparse
import aiohttp
import statistics
from typing import List, Dict

# Configuration
API_URL = "http://localhost:8080/api/stream"

class Metrics:
    def __init__(self):
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.ttfts = []  # Time To First Token
        self.total_times = []
        self.errors = []

    def report(self):
        print("\n=== Load Test Results ===")
        print(f"Total Requests: {self.total_requests}")
        print(f"Successful (200 OK): {self.successful_requests}")
        print(f"Failed: {self.failed_requests}")
        
        if self.total_requests > 0:
            success_rate = (self.successful_requests / self.total_requests) * 100
            print(f"Success Rate: {success_rate:.2f}%")
        
        # User requested to focus on 200 count and resource usage, ignoring latency metrics.
        # Uncomment below if latency metrics are needed.
        # if self.ttfts:
        #     print(f"TTFT (avg): {statistics.mean(self.ttfts):.4f}s")
        #     ...
        
        if self.errors:
            print("\nRecent Errors:")
            for e in self.errors[:5]:
                print(f"- {e}")

metrics = Metrics()

async def run_session(session: aiohttp.ClientSession, user_idx: int):
    session_id = str(uuid.uuid4())
    # Constructing StreamRequest payload
    # Randomly select between normal chat and weather tool call
    content = f"北京天气怎么样？" 

    payload = {
        "messages": [{"role": "user", "content": content}],
        "session_id": session_id,
        "user_id": f"stress_user_{user_idx}",
        "available_tools": ["get_weather"],
        "system_prefix": "你是一个专业的天气助手，能够调用get_weather回答用户关于天气的问题。",
        # These fields are from StreamRequest definition
        "multi_agent": False,
        "deep_thinking": False,
    }

    start_time = time.time()
    ttft = None

    try:
        metrics.total_requests += 1
        async with session.post(API_URL, json=payload) as response:
            if response.status != 200:
                error_text = await response.text()
                metrics.failed_requests += 1
                metrics.errors.append(f"Status {response.status}: {error_text[:100]}")
                return

            async for line in response.content:
                if line:
                    if ttft is None:
                        ttft = time.time() - start_time
                        metrics.ttfts.append(ttft)

            total_time = time.time() - start_time
            metrics.total_times.append(total_time)
            metrics.successful_requests += 1

    except Exception as e:
        metrics.failed_requests += 1
        metrics.errors.append(str(e))

async def dispatcher(session: aiohttp.ClientSession, total_requests: int, qps: float):
    tasks = []
    for i in range(total_requests):
        task = asyncio.create_task(run_session(session, i))
        tasks.append(task)
        if qps > 0:
            # Sleep to maintain QPS
            # 1/QPS seconds per request
            await asyncio.sleep(1.0 / qps)
    
    # Wait for all tasks to complete
    await asyncio.gather(*tasks)

async def main():
    parser = argparse.ArgumentParser(description="Sage Stream API Load Test")
    parser.add_argument("--requests", type=int, default=50, help="Total number of requests to send")
    parser.add_argument("--qps", type=float, default=0, help="Target queries per second (0 for unlimited)")
    parser.add_argument("--url", type=str, default="http://localhost:8080/api/stream", help="Target URL")
    parser.add_argument("--timeout", type=int, default=600, help="Request timeout in seconds (default: 300)")
    args = parser.parse_args()
    
    global API_URL
    API_URL = args.url

    print(f"Starting load test with {args.requests} total requests...")
    if args.qps > 0:
        print(f"Target QPS: {args.qps}")
    print(f"Target: {API_URL}")
    print(f"Timeout: {args.timeout}s")

    # Set client timeout
    timeout = aiohttp.ClientTimeout(total=args.timeout)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # Wait for server to be ready
        print("Waiting for server to be ready...")
        start_wait = time.time()
        server_ready = False
        while time.time() - start_wait < 60:
            try:
                # Use /api/health for readiness check
                async with session.get(API_URL.replace("/stream", "/health"), timeout=2) as resp:
                    if resp.status == 200:
                        server_ready = True
                        print(f"Server ready after {time.time() - start_wait:.2f}s")
                        break
            except Exception:
                pass
            await asyncio.sleep(1)
        
        if not server_ready:
            print("Timeout waiting for server to be active")
            return

        # Register/Refresh Mock MCP
        print("Ensuring Mock MCP is registered...")
        mcp_payload = {
            "name": "mock-weather",
            "protocol": "sse",
            "sse_url": "http://mock-mcp:9001/sse"
        }
        try:
            # Try to add
            async with session.post(API_URL.replace("/stream", "/mcp/add"), json=mcp_payload) as resp:
                if resp.status == 200:
                    print("Mock MCP registered successfully")
                else:
                    # If add fails (maybe exists), try refresh
                    print(f"Add MCP result: {resp.status}, trying refresh...")
                    async with session.post(API_URL.replace("/stream", "/mcp/mock-weather/refresh")) as ref_resp:
                        print(f"Refresh Mock MCP status: {ref_resp.status}")
        except Exception as e:
            print(f"Error registering MCP: {e}")

        # Wait for MCP tool 'get_weather' to be available
        print("Waiting for 'get_weather' tool to be available...")
        tools_url = API_URL.replace("/api/stream", "/api/tools")
        tool_ready = False
        start_wait_tool = time.time()
        while time.time() - start_wait_tool < 60:
            try:
                async with session.get(tools_url, timeout=2) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        tools = data.get("data", {}).get("tools", [])
                        tool_names = [t.get("name") for t in tools]
                        if "get_weather" in tool_names:
                            print(f"Tool 'get_weather' is available after {time.time() - start_wait_tool:.2f}s")
                            tool_ready = True
                            break
                        else:
                            # Try to refresh MCP if tool not found (optional, if we had an endpoint)
                            pass
            except Exception as e:
                print(f"Error checking tools: {e}")
            await asyncio.sleep(2)
            
        if not tool_ready:
            print("Warning: 'get_weather' tool not found. Tests involving this tool will fail.")
        
        # Start dispatcher to feed requests
        await dispatcher(session, args.requests, args.qps)
    
    metrics.report()

if __name__ == "__main__":
    asyncio.run(main())
