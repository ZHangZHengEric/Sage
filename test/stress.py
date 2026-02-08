import asyncio
import time
import uuid
import argparse
import aiohttp
import statistics

# =====================
# Configuration
# =====================
API_URL = "http://localhost:8080/api/stream"


# =====================
# Metrics
# =====================
class Metrics:
    def __init__(self):
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.ttfts = []
        self.total_times = []
        self.errors = []

    def report(self, elapsed: float, concurrency: int):
        print("\n=== Load Test Results ===")
        print(f"Total Requests:      {self.total_requests}")
        print(f"Successful (200):    {self.successful_requests}")
        print(f"Failed:              {self.failed_requests}")

        success_rate = (self.successful_requests / self.total_requests) * 100
        print(f"Success Rate:        {success_rate:.2f}%")

        actual_qps = self.successful_requests / elapsed
        print(f"Actual Throughput:   {actual_qps:.2f} req/s")

        print(f"Concurrency:         {concurrency}")
        print(f"Test Duration:       {elapsed:.2f}s")

        if self.ttfts:
            print(f"TTFT avg:            {statistics.mean(self.ttfts):.3f}s")
            print(f"TTFT p95:            {statistics.quantiles(self.ttfts, n=20)[18]:.3f}s")



metrics = Metrics()


# =====================
# Single Request (SSE)
# =====================
async def run_session(session: aiohttp.ClientSession, user_idx: int):
    session_id = str(uuid.uuid4())

    payload = {
        "messages": [{"role": "user", "content": "北京天气怎么样？"}],
        "session_id": session_id,
        "user_id": f"stress_user_{user_idx}",
        "available_tools": ["get_weather"],
        "system_prefix": "你是一个专业的天气助手，能够调用get_weather回答用户关于天气的问题。",
        "multi_agent": False,
        "deep_thinking": False,
    }

    start_time = time.time()
    ttft = None

    try:
        metrics.total_requests += 1

        async with session.post(API_URL, json=payload) as response:
            if response.status != 200:
                text = await response.text()
                metrics.failed_requests += 1
                metrics.errors.append(f"HTTP {response.status}: {text[:100]}")
                return

            async for line in response.content:
                if line and ttft is None:
                    ttft = time.time() - start_time
                    metrics.ttfts.append(ttft)

            total_time = time.time() - start_time
            metrics.total_times.append(total_time)
            metrics.successful_requests += 1

    except Exception as e:
        metrics.failed_requests += 1
        metrics.errors.append(str(e))


# =====================
# Concurrent Dispatcher
# =====================
async def dispatcher_concurrent(
    session: aiohttp.ClientSession,
    total_requests: int,
    concurrency: int,
):
    sem = asyncio.Semaphore(concurrency)
    req_counter = 0
    lock = asyncio.Lock()

    async def worker(worker_id: int):
        nonlocal req_counter
        while True:
            async with lock:
                if req_counter >= total_requests:
                    return
                idx = req_counter
                req_counter += 1

            async with sem:
                await run_session(session, idx)

    workers = [asyncio.create_task(worker(i)) for i in range(concurrency)]

    await asyncio.gather(*workers)


# =====================
# Main
# =====================
async def main():
    parser = argparse.ArgumentParser(description="Sage Stream API Concurrent Load Test")
    parser.add_argument("--requests", type=int, default=1000, help="Total requests")
    parser.add_argument(
        "--concurrency", type=int, default=20, help="Max concurrent requests"
    )
    parser.add_argument("--url", type=str, default="http://localhost:8080/api/stream")
    parser.add_argument(
        "--timeout", type=int, default=600, help="Request timeout seconds"
    )
    args = parser.parse_args()

    global API_URL
    API_URL = args.url

    print("\n=== Concurrent Load Test ===")
    print(f"Target URL:      {API_URL}")
    print(f"Total Requests: {args.requests}")
    print(f"Concurrency:    {args.concurrency}")
    print(f"Timeout:        {args.timeout}s")

    timeout = aiohttp.ClientTimeout(total=args.timeout)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        # ---------------------
        # Health Check
        # ---------------------
        print("\nWaiting for server readiness...")
        start_wait = time.time()
        ready = False
        while time.time() - start_wait < 60:
            try:
                async with session.get(
                    API_URL.replace("/stream", "/health"), timeout=2
                ) as resp:
                    if resp.status == 200:
                        ready = True
                        print(f"Server ready after {time.time() - start_wait:.2f}s")
                        break
            except Exception:
                pass
            await asyncio.sleep(1)

        if not ready:
            print("Server not ready, aborting.")
            return

        # ---------------------
        # Register MCP
        # ---------------------
        print("\nEnsuring Mock MCP registered...")
        mcp_payload = {
            "name": "mock-weather",
            "protocol": "sse",
            "sse_url": "http://mock-mcp:9001/sse",
        }

        try:
            async with session.post(
                API_URL.replace("/stream", "/mcp/add"), json=mcp_payload
            ) as resp:
                if resp.status == 200:
                    print("Mock MCP registered")
                else:
                    async with session.post(
                        API_URL.replace("/stream", "/mcp/mock-weather/refresh")
                    ) as r:
                        print(f"Mock MCP refresh status: {r.status}")
        except Exception as e:
            print(f"MCP setup error: {e}")

        # ---------------------
        # Wait for Tool
        # ---------------------
        print("\nWaiting for get_weather tool...")
        tools_url = API_URL.replace("/api/stream", "/api/tools")
        start_wait = time.time()
        while time.time() - start_wait < 60:
            try:
                async with session.get(tools_url, timeout=2) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        tools = data.get("data", {}).get("tools", [])
                        names = [t.get("name") for t in tools]
                        if "get_weather" in names:
                            print("Tool get_weather is available")
                            break
            except Exception:
                pass
            await asyncio.sleep(2)

        # ----------------
        # ---------------------
        # Run Load Test
        # ---------------------
        print("\nStarting concurrent load test...")
        start_test = time.time()

        await dispatcher_concurrent(
            session=session,
            total_requests=args.requests,
            concurrency=args.concurrency,
        )

        elapsed = time.time() - start_test
        print(f"\nLoad test finished in {elapsed:.2f}s")
        
        metrics.report(elapsed, args.concurrency)


if __name__ == "__main__":
    asyncio.run(main())
