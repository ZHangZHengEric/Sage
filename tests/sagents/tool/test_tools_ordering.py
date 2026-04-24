"""验证 tools_json 的顺序在 ToolManager / ToolProxy 中保持稳定。

prompt cache key 在 Anthropic / 阿里云等多家 provider 上都对 ``tools`` 字段顺序
敏感，这里要保证排序后顺序不变、且与字典序一致。
"""
from __future__ import annotations

from sagents.tool.tool_base import tool
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_proxy import ToolProxy


class _OutOfOrderTools:
    @tool()
    def zeta(self, x: str = ""):
        """z"""
        return x

    @tool()
    def alpha(self, x: str = ""):
        """a"""
        return x

    @tool()
    def mike(self, x: str = ""):
        """m"""
        return x


def test_tool_manager_returns_tools_in_alphabetical_order():
    tm = ToolManager(isolated=True, is_auto_discover=False)
    tm.register_tools_from_object(_OutOfOrderTools())
    names = [t["function"]["name"] for t in tm.get_openai_tools()]
    assert names == sorted(names)


def test_tool_proxy_returns_tools_in_alphabetical_order():
    tm = ToolManager(isolated=True, is_auto_discover=False)
    tm.register_tools_from_object(_OutOfOrderTools())
    proxy = ToolProxy(tool_managers=[tm])
    names = [t["function"]["name"] for t in proxy.get_openai_tools()]
    assert names == sorted(names)


def test_tool_manager_order_is_stable_across_calls():
    tm = ToolManager(isolated=True, is_auto_discover=False)
    tm.register_tools_from_object(_OutOfOrderTools())
    a = [t["function"]["name"] for t in tm.get_openai_tools()]
    b = [t["function"]["name"] for t in tm.get_openai_tools()]
    assert a == b
