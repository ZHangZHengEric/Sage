"""sagents package public re-exports.

保持懒加载，避免仅导入 ``sagents.context.*`` 时提前加载 ToolManager/MCP 依赖。
"""

__all__ = ["SAgent"]


def __getattr__(name: str):
    if name == "SAgent":
        from sagents.sagents import SAgent

        return SAgent
    raise AttributeError(name)
