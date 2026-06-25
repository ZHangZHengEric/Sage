"""
工具使用推荐 Agent

基于用户输入和历史对话，分析并推荐最适合的工具组合。
将推荐结果存入 session_context.audit_status 中供后续使用。
"""

import json
import os
import traceback
import uuid
from copy import copy
from typing import Any, Dict, List, Optional, AsyncGenerator

from sagents.agent.agent_base import AgentBase
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.context.session_context import SessionContext
from sagents.tool.tool_proxy import ToolProxy
from sagents.tool.tool_baseline import augment_with_baseline_tools
from sagents.utils.llm_request_utils import redact_base64_data_urls_in_value
from sagents.utils.logger import logger
from sagents.utils.prompt_manager import PromptManager

DEFAULT_TOOL_SUGGESTION_DIRECT_THRESHOLD = 15
TOOL_SUGGESTION_DIRECT_THRESHOLD_ENV = "SAGE_TOOL_SUGGESTION_DIRECT_THRESHOLD"
TOOL_SUGGESTION_CONTEXT_TURNS = 5


def get_tool_suggestion_direct_threshold() -> int:
    raw_value = os.environ.get(TOOL_SUGGESTION_DIRECT_THRESHOLD_ENV)
    if raw_value is None or raw_value.strip() == "":
        return DEFAULT_TOOL_SUGGESTION_DIRECT_THRESHOLD
    try:
        threshold = int(raw_value)
    except ValueError:
        logger.warning(
            f"ToolSuggestionAgent: invalid {TOOL_SUGGESTION_DIRECT_THRESHOLD_ENV}={raw_value!r}, "
            f"using default {DEFAULT_TOOL_SUGGESTION_DIRECT_THRESHOLD}"
        )
        return DEFAULT_TOOL_SUGGESTION_DIRECT_THRESHOLD
    if threshold < 0:
        logger.warning(
            f"ToolSuggestionAgent: negative {TOOL_SUGGESTION_DIRECT_THRESHOLD_ENV}={threshold}, "
            f"using default {DEFAULT_TOOL_SUGGESTION_DIRECT_THRESHOLD}"
        )
        return DEFAULT_TOOL_SUGGESTION_DIRECT_THRESHOLD
    return threshold


class ToolSuggestionAgent(AgentBase):
    """
    工具使用推荐 Agent

    负责分析用户请求和对话上下文，推荐最适合的工具组合。
    推荐结果会存入 session_context.audit_status['suggested_tools'] 中。
    """

    def __init__(
        self,
        model: Any,
        model_config: Optional[Dict[str, Any]] = None,
        system_prefix: str = "",
    ):
        if model_config is None:
            model_config = {}
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "ToolSuggestionAgent"
        self.agent_description = (
            "工具使用推荐智能体，专门负责根据用户需求推荐最合适的工具组合"
        )
        logger.debug("ToolSuggestionAgent 初始化完成")

    @staticmethod
    def _extract_text_content(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text)
                elif item.get("type") == "image_url":
                    parts.append("[image attached]")
                else:
                    item_type = item.get("type") or "unknown"
                    parts.append(f"[{item_type} attachment]")
            return "\n".join(parts)
        return ""

    @classmethod
    def _text_only_message(cls, msg: MessageChunk) -> Optional[MessageChunk]:
        text = cls._extract_text_content(msg.get_content()).strip()
        if not text:
            return None
        text_msg = copy(msg)
        text_msg.content = text
        text_msg.tool_calls = None
        text_msg.tool_call_id = None
        return text_msg

    @classmethod
    def _extract_tool_selection_context_messages(
        cls, message_manager: Any
    ) -> List[MessageChunk]:
        active_messages = MessageManager.build_inference_view(
            message_manager.messages,
            session_id=message_manager.session_id,
            apply_rule_compression=False,
        )

        chats: List[List[MessageChunk]] = []
        current_chat: List[MessageChunk] = []
        for msg in active_messages:
            if msg.is_user_input_message():
                if current_chat:
                    chats.append(current_chat)
                current_chat = [msg]
            elif current_chat:
                current_chat.append(msg)
        if current_chat:
            chats.append(current_chat)

        compact_messages: List[MessageChunk] = []
        for chat in chats[-TOOL_SUGGESTION_CONTEXT_TURNS:]:
            tool_call_names: Dict[str, str] = {}
            user_msg = cls._text_only_message(chat[0])
            if user_msg is not None:
                compact_messages.append(user_msg)

            for msg in chat[1:]:
                tool_names = cls._extract_tool_names(msg)
                if tool_names:
                    for tool_call in msg.tool_calls or []:
                        if not isinstance(tool_call, dict):
                            continue
                        call_id = tool_call.get("id")
                        function = tool_call.get("function")
                        if isinstance(call_id, str) and isinstance(function, dict):
                            name = function.get("name")
                            if isinstance(name, str) and name:
                                tool_call_names[call_id] = name
                    compact_messages.append(
                        MessageChunk(
                            role=MessageRole.ASSISTANT.value,
                            content="[tools used: " + ", ".join(tool_names) + "]",
                            message_type=MessageType.ASSISTANT_TEXT.value,
                        )
                    )
                    continue

                if msg.role == MessageRole.TOOL.value:
                    tool_name = (
                        tool_call_names.get(msg.tool_call_id or "")
                        or cls._tool_result_name(msg)
                    )
                    compact_messages.append(
                        MessageChunk(
                            role=MessageRole.TOOL.value,
                            content=f"[tool result omitted: {tool_name}]",
                            tool_call_id=msg.tool_call_id or str(uuid.uuid4()),
                            message_type=MessageType.TOOL_CALL_RESULT.value,
                        )
                    )
                    continue

                if msg.is_assistant_text_message():
                    assistant_msg = cls._text_only_message(msg)
                    if assistant_msg is not None:
                        compact_messages.append(assistant_msg)

        return compact_messages

    @staticmethod
    def _extract_tool_names(msg: MessageChunk) -> List[str]:
        tool_names: List[str] = []
        for tool_call in msg.tool_calls or []:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            if isinstance(function, dict):
                name = function.get("name")
                if isinstance(name, str) and name:
                    tool_names.append(name)
        return tool_names

    @staticmethod
    def _tool_result_name(msg: MessageChunk) -> str:
        metadata = msg.metadata if isinstance(msg.metadata, dict) else {}
        tool_name = metadata.get("tool_name") or metadata.get("name")
        if isinstance(tool_name, str) and tool_name:
            return tool_name
        return msg.tool_call_id or "unknown"

    @classmethod
    def _format_tool_messages_for_prompt(cls, messages: List[MessageChunk]) -> str:
        lines: List[str] = []
        tool_call_names: Dict[str, str] = {}

        for msg in messages:
            tool_names = cls._extract_tool_names(msg)
            if tool_names:
                for tool_call in msg.tool_calls or []:
                    if not isinstance(tool_call, dict):
                        continue
                    call_id = tool_call.get("id")
                    function = tool_call.get("function")
                    if isinstance(call_id, str) and isinstance(function, dict):
                        name = function.get("name")
                        if isinstance(name, str) and name:
                            tool_call_names[call_id] = name
                lines.append("assistant: [tools used: " + ", ".join(tool_names) + "]")
                continue

            if msg.role == MessageRole.TOOL.value:
                existing_text = cls._extract_text_content(msg.get_content()).strip()
                if existing_text.startswith("[tool result omitted:"):
                    lines.append(f"tool: {existing_text}")
                    continue
                tool_name = (
                    tool_call_names.get(msg.tool_call_id or "")
                    or cls._tool_result_name(msg)
                )
                lines.append(f"tool: [tool result omitted: {tool_name}]")
                continue

            text = cls._extract_text_content(msg.get_content()).strip()
            if not text:
                continue
            if len(text) > 2000:
                text = text[:2000] + f"\n...[truncated, original chars: {len(text)}]"
            lines.append(f"{msg.role}: {text}")

        return "\n\n".join(lines)

    @staticmethod
    def _build_skill_context(session_context: SessionContext) -> str:
        lines: List[str] = []
        system_context = getattr(session_context, "system_context", {}) or {}
        active_skills = system_context.get("active_skills")
        if active_skills:
            lines.append("<active_skills>")
            for skill in active_skills:
                if not isinstance(skill, dict):
                    continue
                name = str(skill.get("skill_name") or "unknown")
                content = str(skill.get("skill_content") or "")
                if len(content) > 500:
                    content = content[:500] + f"\n...[truncated, original chars: {len(content)}]"
                lines.append(f"- {name}: {content}")
            lines.append("</active_skills>")

        skill_manager = getattr(session_context, "effective_skill_manager", None)
        if skill_manager:
            if hasattr(skill_manager, "load_new_skills"):
                try:
                    skill_manager.load_new_skills()
                except Exception as exc:
                    logger.warning(f"ToolSuggestionAgent: failed to load new skills: {exc}")
            if hasattr(skill_manager, "list_skill_info"):
                skill_infos = sorted(
                    skill_manager.list_skill_info(),
                    key=lambda skill: getattr(skill, "name", ""),
                )
                if skill_infos:
                    lines.append("<available_skills>")
                    for skill in skill_infos:
                        name = getattr(skill, "name", "unknown")
                        description = str(getattr(skill, "description", "") or "")
                        if len(description) > 80:
                            description = description[:80] + "..."
                        lines.append(f"- {name}: {description}")
                    lines.append("</available_skills>")

        return "\n".join(lines)

    async def run_stream(
        self,
        session_context: SessionContext,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        """
        运行工具推荐分析

        Args:
            session_context: 会话上下文
            tool_manager: 工具管理器

        Yields:
            List[MessageChunk]: 推荐结果消息
        """

        session_id = session_context.session_id
        tool_manager = session_context.tool_manager
        message_manager = session_context.message_manager

        logger.info(f"ToolSuggestionAgent: 开始为会话 {session_id} 分析工具推荐")
        language = session_context.get_language()

        history_messages = self._extract_tool_selection_context_messages(message_manager)
        # 根据 active_budget 压缩消息
        budget_info = message_manager.context_budget_manager.budget_info
        if budget_info:
            history_messages = MessageManager.build_token_budget_view(
                history_messages,
                max(budget_info.get("active_budget", 8000), 3000),
                recent_messages_count=8,
            )
        available_tools = tool_manager.list_tools_simplified(lang=language)  # pyright: ignore[reportOptionalMemberAccess]

        direct_threshold = get_tool_suggestion_direct_threshold()
        if len(available_tools) <= direct_threshold:
            logger.info(
                f"ToolSuggestionAgent: 可用工具数量小于等于{direct_threshold}个，返回所有工具"
            )
            tool_names = [
                tool["name"]
                for tool in available_tools
                if tool["name"] != "complete_task"
            ]
            session_context.audit_status["suggested_tools"] = tool_names
        else:
            tool_names = await self._analyze_tool_suggestions(
                messages_input=history_messages, session_context=session_context
            )
            logger.info(
                f"ToolSuggestionAgent: 为会话 {session_id} 推荐的工具为 {tool_names}"
            )
            session_context.audit_status["suggested_tools"] = tool_names
        yield []

    async def _analyze_tool_suggestions(
        self, messages_input: List[MessageChunk], session_context: SessionContext
    ) -> List[str]:
        """
        分析并获取工具推荐

        Args:
            messages_input: 消息列表
            session_context: 会话上下文

        Returns:
            List[str]: 建议工具名称列表
        """
        logger.info("ToolSuggestionAgent: 开始分析工具推荐")

        try:
            # 如果是 ToolProxy 且处于 fibre/team 模式，动态添加对应系统工具
            if isinstance(session_context.tool_manager, ToolProxy):
                agent_mode = session_context.agent_config.get("agent_mode", "fibre")
                if agent_mode == "fibre":
                    session_context.tool_manager.allow_tools(
                        [
                            "sys_spawn_agent",
                            "sys_delegate_task",
                        ]
                    )
                elif agent_mode == "team":
                    session_context.tool_manager.allow_tools(
                        [
                            "sys_team_delegate_task",
                        ]
                    )

            available_tools = session_context.tool_manager.list_tools_simplified(  # pyright: ignore[reportOptionalMemberAccess]
                lang=session_context.get_language()
            )
            # 准备工具列表字符串，包含ID和名称，以及描述的前100个字符
            available_tools_str = (
                "\n".join(
                    [
                        f"{i + 1}. {tool['name']} - {tool['description'][:50] + '...' if len(tool['description']) > 50 else tool['description']}"
                        for i, tool in enumerate(available_tools)
                    ]
                )
                if available_tools
                else "无可用工具"
            )

            # 准备消息
            logger.info(
                f"ToolSuggestionAgent: messages_input 的token长度为{MessageManager.calculate_messages_token_length(messages_input)}"
            )
            prompt_messages = redact_base64_data_urls_in_value(
                self._format_tool_messages_for_prompt(messages_input)
            )

            # 生成提示
            tool_suggestion_template = PromptManager().get_agent_prompt_auto(
                "tool_suggestion_template", language=session_context.get_language()
            )
            prompt = tool_suggestion_template.format(
                available_tools_str=available_tools_str,
                messages=prompt_messages,
            )
            system_messages = await self.prepare_unified_system_messages(
                session_id=session_context.session_id,
                language=session_context.get_language(),
                include_sections=[
                    "role_definition",
                ],
            )
            skill_context = self._build_skill_context(session_context)
            if skill_context:
                system_messages.append(
                    MessageChunk(
                        role=MessageRole.SYSTEM.value,
                        content=skill_context,
                        message_type=MessageType.SYSTEM.value,
                        agent_name=self.agent_name,
                        metadata={"cache_segment": "semi_stable"},
                    )
                )
            llm_request_messages = system_messages + [
                MessageChunk(
                    role=MessageRole.USER.value,
                    content=prompt,
                    message_id=str(uuid.uuid4()),
                    message_type=MessageType.GUIDE.value,
                )
            ]
            # 调用LLM获取建议，最大重试3次
            max_retries = 3
            retry_count = 0
            suggested_tool_ids = []

            while retry_count < max_retries:
                suggested_tool_ids = await self._get_tool_suggestions(
                    llm_request_messages, session_context.session_id
                )
                if suggested_tool_ids:
                    break
                retry_count += 1
                logger.warning(
                    f"ToolSuggestionAgent: 第{retry_count}次尝试未获取到建议，继续重试..."
                )

            # 如果仍未获取到建议工具，使用全量工具列表
            if not suggested_tool_ids:
                logger.warning(
                    f"ToolSuggestionAgent: 最大重试{max_retries}次后仍未获取到建议工具，使用全量工具列表"
                )
                suggested_tool_ids = [str(i + 1) for i in range(len(available_tools))]

            # 将工具ID转换为工具名称
            suggested_tool_names = []
            for tool_id in suggested_tool_ids:
                try:
                    index = int(tool_id) - 1
                    if 0 <= index < len(available_tools):
                        suggested_tool_names.append(available_tools[index]["name"])
                except (ValueError, IndexError):
                    pass

            # 确保有必要的工具
            sm = session_context.effective_skill_manager
            if sm is not None and sm.list_skills():
                necessary_tools = [
                    "file_read",
                    "execute_python_code",
                    "execute_javascript_code",
                    "execute_shell_command",
                    "file_write",
                    "file_update",
                    "load_skill",
                ]
                for tool_name in necessary_tools:
                    if tool_name not in suggested_tool_names:
                        suggested_tool_names.append(tool_name)

            # 添加系统工具
            system_tools = [
                "sys_spawn_agent",
                "sys_delegate_task",
                "sys_team_delegate_task",
                "send_message_through_im",
                "search_memory",
            ]
            for tool_name in system_tools:
                if tool_name not in suggested_tool_names:
                    for tool in available_tools:
                        if tool["name"] == tool_name:
                            suggested_tool_names.append(tool_name)
                            break

            suggested_tool_names = augment_with_baseline_tools(
                suggested_tool_names, [tool["name"] for tool in available_tools]
            )

            # 移除complete_task工具
            if "complete_task" in suggested_tool_names:
                suggested_tool_names.remove("complete_task")

            # 去重
            suggested_tool_names = list(set(suggested_tool_names))

            logger.info(
                f"ToolSuggestionAgent: 分析完成，推荐工具: {suggested_tool_names}"
            )
            return suggested_tool_names

        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f"ToolSuggestionAgent: 分析工具推荐时发生错误: {str(e)}")
            return []

    async def _get_tool_suggestions(
        self,
        llm_request_messages: List[MessageChunk],
        session_id: str,
        require_json: bool = True,
    ) -> List[str]:
        """
        调用LLM获取工具建议

        Args:
            llm_request_messages: LLM请求消息列表
            session_id: 会话ID
            require_json: 是否要求返回JSON格式，默认为True

        Returns:
            List[str]: 建议工具ID列表
        """
        logger.debug("ToolSuggestionAgent: 调用LLM获取工具建议")

        messages_input = llm_request_messages

        # 构建模型配置覆盖项
        model_config_override = {"model_type": "fast"}  # 使用快速模型
        if require_json:
            model_config_override["response_format"] = {"type": "json_object"}  # pyright: ignore[reportArgumentType]

        response = self._call_llm_streaming(
            messages=messages_input,  # pyright: ignore[reportArgumentType]
            session_id=session_id,
            step_name="tool_suggestion",
            enable_thinking=False,
            model_config_override=model_config_override,
        )

        # 收集流式响应内容
        all_content = ""
        async for chunk in response:
            if len(chunk.choices) == 0:
                continue
            if chunk.choices[0].delta.content:
                all_content += chunk.choices[0].delta.content

        try:
            result_clean = MessageChunk.extract_json_from_markdown(all_content)
            suggested_tool_ids = json.loads(result_clean)
            # 过滤非数字项，确保返回数字列表
            suggested_tool_ids = [
                int(item)
                for item in suggested_tool_ids
                if isinstance(item, (int, str)) and str(item).isdigit()
            ]
            return suggested_tool_ids  # pyright: ignore[reportReturnType]
        except json.JSONDecodeError:
            logger.warning("ToolSuggestionAgent: 解析工具建议响应时JSON解码错误")
            return []
