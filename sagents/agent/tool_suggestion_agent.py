"""
工具使用推荐 Agent

基于用户输入和历史对话，分析并推荐最适合的工具组合。
将推荐结果存入 session_context.audit_status 中供后续使用。
"""

import json
import time
import traceback
import uuid
from typing import Any, Dict, List, Optional, AsyncGenerator

from sagents.agent.agent_base import AgentBase
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.context.session_context import SessionContext
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_proxy import ToolProxy
from sagents.utils.logger import logger
from sagents.utils.prompt_manager import PromptManager


class ToolSuggestionAgent(AgentBase):
    """
    工具使用推荐 Agent

    负责分析用户请求和对话上下文，推荐最适合的工具组合。
    推荐结果会存入 session_context.audit_status['suggested_tools'] 中。
    """

    def __init__(self, model: Any, model_config: Optional[Dict[str, Any]] = None, system_prefix: str = ""):
        if model_config is None:
            model_config = {}
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "ToolSuggestionAgent"
        self.agent_description = "工具使用推荐智能体，专门负责根据用户需求推荐最合适的工具组合"
        logger.debug("ToolSuggestionAgent 初始化完成")

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

        history_messages = message_manager.extract_all_context_messages(recent_turns=1)
        # 根据 active_budget 压缩消息
        budget_info = message_manager.context_budget_manager.budget_info
        if budget_info:
            history_messages = MessageManager.compress_messages(history_messages, max(budget_info.get('active_budget', 8000),2000))
        available_tools = tool_manager.list_tools_simplified(lang=language)

            
        
        if len(available_tools) <= 15:
            logger.info("ToolSuggestionAgent: 可用工具数量小于等于15个，返回所有工具")
            tool_names = [tool['name'] for tool in available_tools if tool['name'] != 'complete_task']
            session_context.audit_status['suggested_tools'] = tool_names
        else:
            tool_names = await self._analyze_tool_suggestions(
                messages_input=history_messages,
                session_context=session_context
            )
            logger.info(f"ToolSuggestionAgent: 为会话 {session_id} 推荐的工具为 {tool_names}")
            session_context.audit_status['suggested_tools'] = tool_names
        yield []
        

    async def _analyze_tool_suggestions(
        self,
        messages_input: List[MessageChunk],
        session_context: SessionContext
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
            # 如果是 ToolProxy 且处于 fibre 模式，动态添加 fibre 特有工具
            if isinstance(session_context.tool_manager, ToolProxy):
                if session_context.agent_config.get("agent_mode", "fibre") == "fibre":
                    session_context.tool_manager.allow_tools([
                        "sys_spawn_agent",
                        "sys_delegate_task",
                        "sys_finish_task",
                    ])

            available_tools = session_context.tool_manager.list_tools_simplified(lang=session_context.get_language())
            # 准备工具列表字符串，包含ID和名称，以及描述的前100个字符
            available_tools_str = "\n".join([
                f"{i+1}. {tool['name']} - {tool['description'][:50]+'...' if len(tool['description']) > 50 else tool['description']}"
                for i, tool in enumerate(available_tools)
            ]) if available_tools else '无可用工具'

            # 准备消息
            logger.info(f"ToolSuggestionAgent: messages_input 的token长度为{MessageManager.calculate_messages_token_length(messages_input)}")
            clean_messages = MessageManager.convert_messages_to_dict_for_request(messages_input)

            # 生成提示
            tool_suggestion_template = PromptManager().get_agent_prompt_auto(
                'tool_suggestion_template',
                language=session_context.get_language()
            )
            prompt = tool_suggestion_template.format(
                available_tools_str=available_tools_str,
                messages=json.dumps(clean_messages, ensure_ascii=False, indent=2)
            )
            llm_request_messages = [
                *await self.prepare_unified_system_messages(session_id=session_context.session_id,
                                language=session_context.get_language(),
                                include_sections = ['role_definition', 'system_context', 'available_skills']),
                MessageChunk(
                    role=MessageRole.USER.value,
                    content=prompt,
                    message_id=str(uuid.uuid4()),
                    message_type=MessageType.GUIDE.value
                )
            ]
            # 调用LLM获取建议，最大重试3次
            max_retries = 3
            retry_count = 0
            suggested_tool_ids = []

            while retry_count < max_retries:
                suggested_tool_ids = await self._get_tool_suggestions(llm_request_messages, session_context.session_id)
                if suggested_tool_ids:
                    break
                retry_count += 1
                logger.warning(f"ToolSuggestionAgent: 第{retry_count}次尝试未获取到建议，继续重试...")

            # 如果仍未获取到建议工具，使用全量工具列表
            if not suggested_tool_ids:
                logger.warning(f"ToolSuggestionAgent: 最大重试{max_retries}次后仍未获取到建议工具，使用全量工具列表")
                suggested_tool_ids = [str(i+1) for i in range(len(available_tools))]

            # 将工具ID转换为工具名称
            suggested_tool_names = []
            for tool_id in suggested_tool_ids:
                try:
                    index = int(tool_id) - 1
                    if 0 <= index < len(available_tools):
                        suggested_tool_names.append(available_tools[index]['name'])
                except (ValueError, IndexError):
                    pass

            # 确保有必要的工具
            sm = session_context.effective_skill_manager
            if sm is not None and sm.list_skills():
                necessary_tools = [
                    'file_read', 'execute_python_code', 'execute_javascript_code',
                    'execute_shell_command', 'file_write', 'file_update', 'load_skill'
                ]
                for tool_name in necessary_tools:
                    if tool_name not in suggested_tool_names:
                        suggested_tool_names.append(tool_name)
    
            # 添加系统工具
            system_tools = ['sys_spawn_agent', 'sys_delegate_task', 'sys_finish_task', 'send_message_through_im','search_memory']
            for tool_name in system_tools:
                if tool_name not in suggested_tool_names:
                    for tool in available_tools:
                        if tool['name'] == tool_name:
                            suggested_tool_names.append(tool_name)
                            break

            # 移除complete_task工具
            if 'complete_task' in suggested_tool_names:
                suggested_tool_names.remove('complete_task')

            # 去重
            suggested_tool_names = list(set(suggested_tool_names))

            logger.info(f"ToolSuggestionAgent: 分析完成，推荐工具: {suggested_tool_names}")
            return suggested_tool_names

        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f"ToolSuggestionAgent: 分析工具推荐时发生错误: {str(e)}")
            return []

    async def _get_tool_suggestions(self, llm_request_messages: List[MessageChunk], session_id: str, require_json: bool = True) -> List[str]:
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
            model_config_override["response_format"] = {"type": "json_object"}

        response = self._call_llm_streaming(
            messages=messages_input,
            session_id=session_id,
            step_name="tool_suggestion",
            enable_thinking=False,
            model_config_override=model_config_override
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
                int(item) for item in suggested_tool_ids
                if isinstance(item, (int, str)) and str(item).isdigit()
            ]
            return suggested_tool_ids
        except json.JSONDecodeError:
            logger.warning("ToolSuggestionAgent: 解析工具建议响应时JSON解码错误")
            return []
