import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
from sagents.tool.tool_manager import ToolManager
from sagents.utils.serialization import make_serializable


@pytest.mark.asyncio
@pytest.mark.parametrize("mcp", [False, True])
async def test_large_tool_result_encoding_off_loop_and_wire_compatible(monkeypatch, mcp):
    manager = object.__new__(ToolManager)
    result = {"content": [{"text": "中文" * 10000, "other": "unused"}]}
    caller = threading.get_ident()
    threads = []
    name = "_serialize_mcp_result" if mcp else "_serialize_standard_result"
    original = getattr(manager, name)

    def encode(value):
        threads.append(threading.get_ident())
        return original(value)

    monkeypatch.setattr(manager, name, encode)

    async def execute(*args, **kwargs):
        return result

    if mcp:
        manager._mcp_proxy = SimpleNamespace(run_mcp_tool=execute)
        tool = SimpleNamespace(name="test", server_name="test")
        actual = await manager._execute_mcp_tool(tool, "s")
        expected = json.dumps({"content": "中文" * 10000}, ensure_ascii=False, indent=2)
    else:
        tool = SimpleNamespace(name="test", func=execute)
        actual = await manager._execute_standard_tool_async(tool)
        expected = json.dumps({"content": make_serializable(result)}, ensure_ascii=False, indent=2)
    assert actual == expected
    assert threads and all(t != caller for t in threads)
