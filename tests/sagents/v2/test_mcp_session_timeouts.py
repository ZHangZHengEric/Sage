"""Transport read deadlines must not reintroduce SDK limits on long tools."""

from typing import cast

from mcp.shared._httpx_utils import McpHttpClientFactory

import asyncio
from contextlib import asynccontextmanager

import pytest

from sagents.v2.tool.plugins._shared.mcp_session import sdk_session
from sagents.v2.tool.plugins.mcp import McpServerConfig


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["sse", "streamable_http"])
@pytest.mark.parametrize("deadline", [None, 7200])
async def test_sdk_transport_read_timeout_matches_execution_policy(monkeypatch, protocol, deadline):
    import httpx
    import mcp
    import mcp.client.sse
    import mcp.client.streamable_http

    observed = {}

    @asynccontextmanager
    async def transport(url, **kwargs):
        observed.update(kwargs)
        # Both SDK transports build this HTTPX timeout, including for a JSON
        # response to a long-running POST rather than only for SSE events.
        timeout = httpx.Timeout(kwargs["timeout"], read=kwargs["sse_read_timeout"])
        assert timeout.connect == 30
        assert timeout.read == (7200 if deadline is None else deadline)
        yield (None, None) if protocol == "sse" else (None, None, lambda: None)

    @asynccontextmanager
    async def session(read, write):
        class Session:
            async def initialize(self):
                pass

        yield Session()

    monkeypatch.setattr(mcp, "ClientSession", session)
    monkeypatch.setattr(mcp.client.sse, "sse_client", transport)
    monkeypatch.setattr(mcp.client.streamable_http, "streamablehttp_client", transport)
    async with sdk_session(McpServerConfig(
        name="long-work", protocol=protocol, url="http://127.0.0.1/mcp",
        call_timeout_seconds=deadline,
    )):
        pass
    assert observed["sse_read_timeout"] == (7200 if deadline is None else deadline)


@pytest.mark.parametrize("value", [float("inf"), float("nan"), 0, -1])
def test_call_timeout_must_be_finite_and_positive(value):
    with pytest.raises(ValueError):
        McpServerConfig(name="bounded", protocol="sse", url="https://example.test", call_timeout_seconds=value)


def test_default_call_timeout_is_two_hours_and_can_be_overridden():
    assert McpServerConfig(name="default", protocol="sse", url="https://example.test").call_timeout_seconds == 7200
    assert McpServerConfig(name="custom", protocol="sse", url="https://example.test", call_timeout_seconds=14400).call_timeout_seconds == 14400


@pytest.mark.asyncio
async def test_sdk_initialization_stays_bounded_without_execution_deadline(monkeypatch):
    import mcp
    import mcp.client.sse

    @asynccontextmanager
    async def transport(*args, **kwargs):
        yield None, None

    @asynccontextmanager
    async def session(*args):
        class Session:
            async def initialize(self):
                await asyncio.Event().wait()

        yield Session()

    monkeypatch.setattr(mcp, "ClientSession", session)
    monkeypatch.setattr(mcp.client.sse, "sse_client", transport)
    with pytest.raises(TimeoutError):
        async with sdk_session(McpServerConfig(
            name="unresponsive", protocol="sse", url="http://127.0.0.1/mcp",
            timeout_seconds=0.01,
        )):
            pytest.fail("uninitialized session was exposed")


@pytest.mark.asyncio
async def test_real_http_sdk_waits_for_long_json_tool_response(monkeypatch):
    import json

    import httpx
    import mcp.client.streamable_http

    original = mcp.client.streamable_http.streamablehttp_client

    async def handle(request):
        message = json.loads(request.content)
        if "id" not in message:
            return httpx.Response(202)
        if message["method"] == "initialize":
            result = {
                "protocolVersion": message["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "slow", "version": "1"},
            }
        elif message["method"] == "tools/list":
            result = {"tools": [{"name": "generate", "inputSchema": {"type": "object"}}]}
        else:
            await asyncio.sleep(0.1)
            # Inspect the actual timeout on the SDK's tool POST, rather than
            # only checking the arguments passed into its transport factory.
            assert request.extensions["timeout"]["read"] == 7200
            result = {"content": [{"type": "text", "text": "done"}]}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)

    def transport(*args, **kwargs):
        return original(*args, **kwargs, httpx_client_factory=cast(McpHttpClientFactory, client_factory))

    monkeypatch.setattr(mcp.client.streamable_http, "streamablehttp_client", transport)
    async with sdk_session(McpServerConfig(
        name="slow", protocol="streamable_http", url="http://127.0.0.1/mcp",
        timeout_seconds=5,
    )) as session:
        result = await session.call_tool("generate", {})
        assert result.content[0].text == "done"


@pytest.mark.asyncio
async def test_pool_waiter_cancellation_does_not_cancel_shared_startup():
    from sagents.v2.tool import McpSessionPool

    started, initialize, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    opens = []

    @asynccontextmanager
    async def factory(config):
        opens.append(config.name)
        started.set()
        await initialize.wait()
        try:
            yield object()
        finally:
            closed.set()

    config = McpServerConfig(name="shared", protocol="stdio", command="fake")
    async with McpSessionPool(session_factory=factory) as pool:
        async def borrow():
            async with pool(config):
                return "ready"
        first = asyncio.create_task(borrow())
        await started.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(borrow())
        initialize.set()
        assert await second == "ready"
        assert opens == ["shared"]
        assert not closed.is_set()
    assert closed.is_set()


@pytest.mark.asyncio
async def test_pool_idle_eviction_waits_for_all_leases_and_keeps_owner_task():
    import anyio
    from sagents.v2.tool import McpSessionPool

    closed = asyncio.Event()

    @asynccontextmanager
    async def factory(config):
        owner = asyncio.current_task()
        with anyio.CancelScope():
            try:
                yield object()
            finally:
                assert asyncio.current_task() is owner
                closed.set()

    config = McpServerConfig(name="shared", protocol="stdio", command="fake")
    async with McpSessionPool(session_factory=factory, idle_timeout_seconds=0.02) as pool:
        async with pool(config):
            async with pool(config):
                pass
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(closed.wait(), 0.05)
        await asyncio.wait_for(closed.wait(), 1)


@pytest.mark.asyncio
async def test_pool_acquisition_timeout_is_independent_of_call_deadline():
    from sagents.v2.tool import McpSessionPool

    stopped = asyncio.Event()

    @asynccontextmanager
    async def factory(config):
        try:
            await asyncio.Event().wait()
            yield object()
        finally:
            stopped.set()

    config = McpServerConfig(name="stuck", protocol="stdio", command="fake",
                             timeout_seconds=0.02, call_timeout_seconds=7200)
    async with McpSessionPool(session_factory=factory) as pool:
        with pytest.raises(TimeoutError):
            async with pool(config):
                pytest.fail("uninitialized session exposed")
        await asyncio.wait_for(stopped.wait(), 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("force", [False, True])
async def test_pool_shutdown_drains_or_forces_active_lease_without_cancelling_borrower(force):
    from sagents.v2.tool import McpSessionPool

    entered, closed, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    @asynccontextmanager
    async def factory(config):
        try:
            yield object()
        finally:
            closed.set()

    config = McpServerConfig(name="active", protocol="stdio", command="fake")
    pool = await McpSessionPool(session_factory=factory, shutdown_timeout_seconds=0.05,
                                cleanup_timeout_seconds=0.2).__aenter__()
    async def borrow():
        async with pool(config):
            entered.set()
            await release.wait()
        return "completed"
    task = asyncio.create_task(borrow())
    await entered.wait()
    closing = asyncio.create_task(pool.aclose())
    if force:
        await asyncio.wait_for(closed.wait(), 1)
        assert not task.done()
    else:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(closed.wait(), 0.02)
    release.set()
    assert await task == "completed"
    await closing
    assert closed.is_set()
    with pytest.raises(RuntimeError, match="closing"):
        async with pool(config):
            pytest.fail("closed pool accepted lease")


@pytest.mark.asyncio
async def test_pool_close_cancellation_keeps_shared_cleanup_running():
    import anyio
    from sagents.v2.tool import McpSessionPool

    cleaning, finish, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    @asynccontextmanager
    async def factory(config):
        with anyio.CancelScope():
            try:
                yield object()
            finally:
                cleaning.set()
                await finish.wait()
                closed.set()

    pool = await McpSessionPool(session_factory=factory).__aenter__()
    async with pool(McpServerConfig(name="close", protocol="stdio", command="fake")):
        pass
    close = asyncio.create_task(pool.aclose())
    await cleaning.wait()
    close.cancel()
    with pytest.raises(asyncio.CancelledError):
        await close
    finish.set()
    await pool.aclose()
    assert closed.is_set()
    assert pool.cleanup_errors == ()


@pytest.mark.asyncio
async def test_pool_close_wakes_startup_waiters_and_exits_anyio_in_owner():
    import anyio
    from sagents.v2.tool import McpSessionPool

    started, closed = asyncio.Event(), asyncio.Event()

    @asynccontextmanager
    async def factory(config):
        owner = asyncio.current_task()
        with anyio.CancelScope():
            try:
                started.set()
                await asyncio.Event().wait()
                yield object()
            finally:
                assert asyncio.current_task() is owner
                closed.set()

    pool = await McpSessionPool(session_factory=factory).__aenter__()
    async def borrow():
        async with pool(McpServerConfig(name="startup", protocol="stdio", command="fake")):
            pytest.fail("startup succeeded")
    task = asyncio.create_task(borrow())
    await started.wait()
    await pool.aclose()
    with pytest.raises(RuntimeError, match="closing"):
        await task
    assert closed.is_set()


@pytest.mark.asyncio
async def test_pool_cleanup_timeout_does_not_cross_anyio_scopes():
    import anyio
    from sagents.v2.tool import McpSessionPool

    closed = asyncio.Event()

    @asynccontextmanager
    async def factory(config):
        owner = asyncio.current_task()
        with anyio.CancelScope():
            try:
                yield object()
            finally:
                try:
                    await asyncio.Event().wait()
                finally:
                    assert asyncio.current_task() is owner
                    closed.set()

    async with McpSessionPool(session_factory=factory, cleanup_timeout_seconds=0.02) as pool:
        async with pool(McpServerConfig(name="cleanup", protocol="stdio", command="fake")):
            pass
    assert closed.is_set()
    assert "cleanup_timeout" in pool.cleanup_errors


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["reuse", "initialize_cancel", "delete_timeout"])
async def test_pool_real_http_sdk_lifecycle(monkeypatch, mode):
    import json
    import httpx
    import mcp.client.streamable_http
    from sagents.v2.tool import McpSessionPool

    original = mcp.client.streamable_http.streamablehttp_client
    methods = []
    started, stopped = asyncio.Event(), asyncio.Event()

    async def handle(request):
        if request.method == "GET":
            return httpx.Response(405)
        if request.method == "DELETE":
            methods.append("DELETE")
            if mode == "delete_timeout":
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
            return httpx.Response(200)
        message = json.loads(request.content)
        methods.append(message["method"])
        if "id" not in message:
            return httpx.Response(202)
        if message["method"] == "initialize":
            started.set()
            if mode == "initialize_cancel":
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
            result = {"protocolVersion": message["params"]["protocolVersion"],
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "pool", "version": "1"}}
        elif message["method"] == "tools/list":
            result = {"tools": []}
        else:
            result = {"content": [{"type": "text", "text": "done"}]}
        return httpx.Response(200, headers={"mcp-session-id": "test-session"},
                              json={"jsonrpc": "2.0", "id": message["id"], "result": result})

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)

    def transport(*args, **kwargs):
        return original(*args, **kwargs, httpx_client_factory=cast(McpHttpClientFactory, client_factory))

    monkeypatch.setattr(mcp.client.streamable_http, "streamablehttp_client", transport)
    config = McpServerConfig(name="http", protocol="streamable_http", url="http://mcp.test/mcp")
    pool = await McpSessionPool(shutdown_timeout_seconds=0.2, cleanup_timeout_seconds=0.05).__aenter__()
    async def borrow():
        async with pool(config) as session:
            return await session.list_tools()
    if mode == "initialize_cancel":
        task = asyncio.create_task(borrow())
        await started.wait()
        await asyncio.wait_for(pool.aclose(), 1)
        with pytest.raises(RuntimeError, match="closing"):
            await task
        assert stopped.is_set()
    else:
        await borrow()
        for _ in range(2):
            async with pool(config) as session:
                assert (await session.call_tool("echo", {})).content[0].text == "done"
        await asyncio.wait_for(pool.aclose(), 1)
        assert methods.count("initialize") == 1
        assert methods.count("tools/call") == 2
        assert methods.count("DELETE") == 1
        if mode == "delete_timeout":
            assert stopped.is_set()
            assert "cleanup_timeout" in pool.cleanup_errors
        else:
            assert pool.cleanup_errors == ()


@pytest.mark.asyncio
async def test_pool_real_stdio_reuses_process_and_terminates_it(tmp_path):
    import os
    import sys
    from sagents.v2.tool import McpSessionPool

    server = tmp_path / "server.py"
    pid_file = tmp_path / "pid"
    server.write_text('''import json, os, sys
from pathlib import Path
Path(sys.argv[1]).write_text(str(os.getpid()))
initializes = 0
for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:
        continue
    if message["method"] == "initialize":
        initializes += 1
        result = {"protocolVersion": message["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "1"}}
    elif message["method"] == "tools/list":
        result = {"tools": []}
    else:
        result = {"content": [{"type": "text", "text": str(initializes)}]}
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
''')
    config = McpServerConfig(name="stdio", protocol="stdio", command=sys.executable,
                             args=(str(server), str(pid_file)))
    async with McpSessionPool() as pool:
        async with pool(config) as session:
            await session.list_tools()
        pid = int(pid_file.read_text())
        for _ in range(2):
            async with pool(config) as session:
                assert (await session.call_tool("echo", {})).content[0].text == "1"
            assert int(pid_file.read_text()) == pid
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert pool.cleanup_errors == ()


@pytest.mark.asyncio
async def test_pool_forced_shutdown_prevents_further_dispatch_on_existing_lease():
    from sagents.v2.tool import McpSessionPool

    cleaning, finish = asyncio.Event(), asyncio.Event()
    dispatches = []

    class Session:
        async def call_tool(self, *args):
            dispatches.append(args)

    @asynccontextmanager
    async def factory(config):
        try:
            yield Session()
        finally:
            cleaning.set()
            await finish.wait()

    pool = await McpSessionPool(session_factory=factory, shutdown_timeout_seconds=0.01).__aenter__()
    async with pool(McpServerConfig(name="force", protocol="stdio", command="fake")) as session:
        close = asyncio.create_task(pool.aclose())
        await cleaning.wait()
        try:
            with pytest.raises(RuntimeError, match="closed"):
                await session.call_tool("write", {})
            assert dispatches == []
        finally:
            finish.set()
            await close


@pytest.mark.asyncio
async def test_pool_shutdown_wakes_waiter_for_retired_active_session():
    from sagents.v2.tool import McpSessionPool

    @asynccontextmanager
    async def factory(config):
        yield object()

    config = McpServerConfig(name="retired", protocol="stdio", command="fake")
    pool = await McpSessionPool(session_factory=factory).__aenter__()
    waiting = asyncio.Event()
    async def borrow():
        waiting.set()
        async with pool(config):
            pytest.fail("retired entry lent out")
    async with pool(config):
        with pytest.raises(ValueError):
            async with pool(config):
                raise ValueError("retire")
        task = asyncio.create_task(borrow())
        await waiting.wait()  # Borrower runs to its first wait after setting this.
        close = asyncio.create_task(pool.aclose())
        try:
            with pytest.raises(RuntimeError, match="closing"):
                await asyncio.wait_for(task, 0.1)
        finally:
            task.cancel()
    await close


@pytest.mark.asyncio
async def test_pool_startup_timeout_allows_cooperative_async_cleanup():
    from sagents.v2.tool import McpSessionPool

    finished = asyncio.Event()
    @asynccontextmanager
    async def factory(config):
        try:
            await asyncio.Event().wait()
            yield object()
        finally:
            await asyncio.sleep(0.01)
            finished.set()
    async with McpSessionPool(session_factory=factory, cleanup_timeout_seconds=1) as pool:
        with pytest.raises(TimeoutError):
            async with pool(McpServerConfig(name="startup", protocol="stdio", command="fake", timeout_seconds=0.02)):
                pytest.fail("uninitialized session exposed")
    assert finished.is_set()
    assert pool.cleanup_errors == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("startup", [True, False, "invalid"])
async def test_pool_stdio_cleanup_preserves_descendants_even_after_host_deadline(tmp_path, startup):
    import os
    import signal
    import sys
    import psutil
    from sagents.v2.tool import McpSessionPool

    if sys.platform == "win32":
        pytest.skip("POSIX process-group termination contract")
    pid_file = tmp_path / "child"
    script = tmp_path / "descendants.py"
    script.write_text('''import json, subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
Path(sys.argv[1]).write_text(str(child.pid))
if sys.argv[2] == "startup":
    time.sleep(60)
else:
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" in msg:
            result = {"protocolVersion": msg["params"]["protocolVersion"], "capabilities": {}, "serverInfo": {"name": "child", "version": "1"}}
            if sys.argv[2] == "invalid":
                result = {}
            print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
    time.sleep(60)
''')
    config = McpServerConfig(name="descendants", protocol="stdio", command=sys.executable,
                             args=(str(script), str(pid_file), "invalid" if startup == "invalid" else ("startup" if startup else "ready")),
                             timeout_seconds=0.3)
    child = None
    try:
        async with McpSessionPool(shutdown_timeout_seconds=0.02, cleanup_timeout_seconds=0.02) as pool:
            if startup:
                with pytest.raises(TimeoutError):
                    async with pool(config):
                        pytest.fail("unexpected initialization")
            else:
                async with pool(config):
                    pass
            child = psutil.Process(int(pid_file.read_text()))
        # Host returns promptly, while SDK process-tree teardown is retained.
        assert "cleanup_incomplete" in pool.cleanup_errors
        async with asyncio.timeout(6):
            while child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                await asyncio.sleep(0.02)
    finally:
        if child is not None and child.is_running():
            try:
                os.kill(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.asyncio
async def test_pool_http_partial_initialize_bounds_session_termination(monkeypatch):
    import httpx
    import mcp.client.streamable_http
    from sagents.v2.tool import McpSessionPool

    original = mcp.client.streamable_http.streamablehttp_client
    terminating, stopped = asyncio.Event(), asyncio.Event()

    class StalledBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.Event().wait()
            yield b""

    async def handle(request):
        if request.method == "DELETE":
            terminating.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        return httpx.Response(200, headers={"mcp-session-id": "partial", "content-type": "application/json"},
                              stream=StalledBody())

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    def transport(*args, **kwargs):
        return original(*args, **kwargs, httpx_client_factory=cast(McpHttpClientFactory, client_factory))
    monkeypatch.setattr(mcp.client.streamable_http, "streamablehttp_client", transport)
    config = McpServerConfig(name="partial", protocol="streamable_http", url="http://mcp.test/mcp",
                             timeout_seconds=0.03)
    async with McpSessionPool(shutdown_timeout_seconds=0.05, cleanup_timeout_seconds=0.03) as pool:
        with pytest.raises(TimeoutError):
            async with pool(config):
                pytest.fail("partial initialization exposed")
        await asyncio.wait_for(terminating.wait(), 1)
    assert stopped.is_set()
    assert "cleanup_timeout" in pool.cleanup_errors
