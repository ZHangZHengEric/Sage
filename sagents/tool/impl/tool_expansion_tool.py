from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..tool_base import tool
from ..tool_expansion import TOOL_EXPAND_TOOLS
from sagents.utils.logger import logger


class ToolExpansionTool:
    """Expand the current LLM-visible tool set within the agent's allowed tools."""

    @tool(
        description_i18n={
            "zh": (
                "扩展当前请求可见的工具集。仅当你尝试调用的工具未出现在当前工具列表中，"
                "但该工具可能属于当前任务所需时使用。只能按准确工具名扩展，且不能突破当前 Agent "
                "被允许使用的工具范围。扩展成功后，请重新调用原本需要的工具。"
            ),
            "en": (
                "Expand the tools visible to the current request. Use this only when a needed tool is missing "
                "from the current tool list. Expansion requires exact tool names and cannot exceed the tools "
                "allowed for the current agent. After expansion succeeds, call the originally needed tool again."
            ),
        },
        param_description_i18n={
            "tool_names": {
                "zh": "需要扩展的准确工具名列表",
                "en": "Exact tool names to expand",
            },
            "session_id": {
                "zh": "会话ID（必填，自动注入）",
                "en": "Session ID (required, auto-injected)",
            },
        },
        param_schema={
            "tool_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Exact tool names to expand",
            },
            "session_id": {"type": "string", "description": "Session ID"},
        },
    )
    async def tool_expand_tools(
        self,
        tool_names: List[str],
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        session_context = self._get_session_context(session_id)
        if not session_context or not getattr(session_context, "tool_manager", None):
            return {
                "success": False,
                "expanded_tools": [],
                "invalid_tools": list(tool_names or []),
                "already_selected_tools": [],
                "error": "Session context or tool manager is not available",
            }

        requested = self._normalize_tool_names(tool_names)
        allowed_tools = set(session_context.tool_manager.list_all_tools_name())
        suggested_tools = list(
            (session_context.audit_status or {}).get("suggested_tools") or []
        )
        selected = set(suggested_tools)
        available_expandable_tools = sorted(
            name
            for name in allowed_tools
            if name and name != TOOL_EXPAND_TOOLS and name not in selected
        )

        expanded_tools: List[str] = []
        invalid_tools: List[str] = []
        already_selected_tools: List[str] = []

        for name in requested:
            if name == TOOL_EXPAND_TOOLS:
                already_selected_tools.append(name)
                continue
            if name not in allowed_tools:
                invalid_tools.append(name)
                continue
            if name in selected:
                already_selected_tools.append(name)
                continue
            suggested_tools.append(name)
            selected.add(name)
            expanded_tools.append(name)

        if expanded_tools:
            session_context.audit_status["suggested_tools"] = suggested_tools
            session_context.audit_status["tools_expanded"] = True

        logger.info(
            "ToolExpansionTool: "
            f"requested={requested} expanded={expanded_tools} invalid={invalid_tools} "
            f"already={already_selected_tools} session={session_id}"
        )

        return {
            "success": bool(expanded_tools),
            "expanded_tools": expanded_tools,
            "invalid_tools": invalid_tools,
            "already_selected_tools": already_selected_tools,
            "available_expandable_tools": [
                name
                for name in available_expandable_tools
                if name not in expanded_tools
            ],
        }

    @staticmethod
    def _normalize_tool_names(tool_names: Optional[List[str]]) -> List[str]:
        if isinstance(tool_names, str):
            tool_names = [tool_names]
        normalized: List[str] = []
        seen = set()
        for item in tool_names or []:
            name = str(item or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            normalized.append(name)
        return normalized

    @staticmethod
    def _get_session_context(session_id: Optional[str]):
        if not session_id:
            return None
        try:
            from sagents.utils.agent_session_helper import get_live_session_context

            return get_live_session_context(session_id, log_prefix="ToolExpansionTool")
        except Exception as exc:
            logger.warning(
                f"ToolExpansionTool: failed to resolve session_context: {exc}"
            )
            return None
