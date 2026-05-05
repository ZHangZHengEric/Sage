"""
记忆召回 Agent

基于用户输入和历史对话，分析并召回最相关的文件记忆。
使用 search_memory 工具搜索 Agent 工作空间中的相关文件。
"""

import json
import traceback
import uuid
from typing import Any, Dict, List, Optional, AsyncGenerator

from sagents.agent.agent_base import AgentBase
from sagents.agent.lightweight_intent import (
    extract_latest_user_text,
    should_skip_preflight_for_lightweight_prompt,
)
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.context.session_context import SessionContext
from sagents.utils.logger import logger
from sagents.utils.prompt_manager import PromptManager


def _ensure_search_memory_available(session_context: SessionContext) -> Any:
    """
    确保 search_memory 工具在可用工具列表中
    
    如果 tool_manager 是 ToolProxy 且 search_memory 不在白名单中，
    则创建一个新的 ToolProxy 包含 search_memory
    
    Args:
        session_context: 会话上下文
        
    Returns:
        可用的 tool_manager
    """
    tool_manager = session_context.tool_manager
    if not tool_manager:
        return None
    
    # 检查是否是 ToolProxy
    from sagents.tool.tool_proxy import ToolProxy
    from sagents.tool.tool_manager import ToolManager
    
    if isinstance(tool_manager, ToolProxy):
        # 检查 search_memory 是否可用
        available_tools = set(tool_manager.list_all_tools_name())
        if 'search_memory' not in available_tools:
            # 获取底层 ToolManager 并添加 search_memory
            base_manager = tool_manager.tool_manager
            if isinstance(base_manager, ToolManager):
                # 检查底层 manager 是否有 search_memory
                if 'search_memory' in base_manager.list_all_tools_name():
                    # 创建新的 ToolProxy，包含原有工具 + search_memory
                    new_available_tools = list(available_tools) + ['search_memory']
                    logger.info("MemoryRecallAgent: 添加 search_memory 到可用工具列表")
                    return ToolProxy(base_manager, new_available_tools)
    
    return tool_manager


class MemoryRecallAgent(AgentBase):
    """
    记忆召回 Agent

    负责分析用户请求和对话上下文，召回最相关的文件记忆。
    必须使用 search_memory 工具进行搜索。
    """

    def __init__(self, model: Any, model_config: Optional[Dict[str, Any]] = None, system_prefix: str = ""):
        if model_config is None:
            model_config = {}
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "MemoryRecallAgent"
        self.agent_description = "记忆召回智能体，专门负责根据用户需求搜索并召回工作空间中最相关的文件记忆"
        logger.debug("MemoryRecallAgent 初始化完成")

    async def run_stream(
        self,
        session_context: SessionContext,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        """
        运行记忆召回分析

        Args:
            session_context: 会话上下文

        Yields:
            List[MessageChunk]: 召回结果消息（包含 tool_call 和 tool 角色消息）
        """
        
        session_id = session_context.session_id
        message_manager = session_context.message_manager
        tool_manager = session_context.tool_manager
        lightweight_messages = message_manager.extract_all_context_messages(recent_turns=1)
        latest_user_text = extract_latest_user_text(lightweight_messages)
        if should_skip_preflight_for_lightweight_prompt(latest_user_text):
            logger.info(
                "MemoryRecallAgent: 跳过轻量请求的记忆召回，latest_user_text=%s",
                latest_user_text,
            )
            yield []
            return
        # 如果 search_memory 不可用，则不进行记忆召回
        if 'search_memory' not in tool_manager.list_all_tools_name():
            logger.warning("MemoryRecallAgent: search_memory 工具不可用，无法进行记忆召回")
            yield []
            return
        
        logger.info(f"MemoryRecallAgent: 开始为会话 {session_id} 召回记忆")

        # 获取历史消息
        history_messages = message_manager.extract_all_context_messages(recent_turns=3)
        
        # 根据 active_budget 压缩消息
        budget_info = message_manager.context_budget_manager.budget_info
        if budget_info:
            history_messages = MessageManager.compress_messages(
                history_messages, 
                max(budget_info.get('active_budget', 8000), 2000)
            )

        # 分析并召回记忆，返回 tool call 和 tool result 消息
        async for chunks in self._recall_memories_stream(
            messages_input=history_messages,
            session_context=session_context
        ):
            yield chunks

    async def _recall_memories_stream(
        self,
        messages_input: List[MessageChunk],
        session_context: SessionContext
    ) -> AsyncGenerator[List[MessageChunk], None]:
        """
        分析并召回相关记忆，以流式方式返回 tool call 和 tool result

        Args:
            messages_input: 消息列表
            session_context: 会话上下文

        Yields:
            List[MessageChunk]: tool_call 和 tool 角色消息
        """
        logger.info("MemoryRecallAgent: 开始分析并召回记忆")

        try:
            # 准备消息
            clean_messages = MessageManager.convert_messages_to_dict_for_request(messages_input)
            
            # 生成搜索查询
            search_query = await self._generate_search_query(
                messages=clean_messages,
                session_context=session_context
            )
            
            if not search_query:
                logger.warning("MemoryRecallAgent: 未能生成搜索查询")
                yield []
                return
            
            logger.info(f"MemoryRecallAgent: 生成的搜索查询: {search_query}")
            
            # 生成 tool_call_id
            tool_call_id = f"call_memory_recall_{str(uuid.uuid4())[:8]}"
            
            # 1. Yield tool_call 消息 (assistant 角色)
            tool_call_chunk = MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content=None,
                tool_calls=[{
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": "search_memory",
                        "arguments": json.dumps({
                            "query": search_query,
                            "top_k": 5
                        }, ensure_ascii=False)
                    }
                }],
                message_type=MessageType.TOOL_CALL.value,
                agent_name=self.agent_name
            )
            yield [tool_call_chunk]
            
            # 2. 执行搜索
            search_results = await self._search_memory(
                query=search_query,
                session_context=session_context
            )
            
            logger.info(f"MemoryRecallAgent: 搜索完成，找到 {len(search_results)} 条结果")
            
            # 3. Yield tool 角色消息（搜索结果）
            tool_result_content = {
                "status": "success" if search_results else "no_results",
                "query": search_query,
                "results_count": len(search_results),
                "results": search_results
            }
            
            tool_result_chunk = MessageChunk(
                role=MessageRole.TOOL.value,
                content=json.dumps(tool_result_content, ensure_ascii=False),
                tool_call_id=tool_call_id,
                message_type=MessageType.TOOL_CALL_RESULT.value,
                agent_name=self.agent_name,
            )
            yield [tool_result_chunk]
            
            # 将召回结果存入 session_context 供后续使用
            # session_context.audit_status['recalled_memories'] = search_results
            
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f"MemoryRecallAgent: 召回记忆时发生错误: {str(e)}")
            
            # 返回错误信息作为 tool result
            error_chunk = MessageChunk(
                role=MessageRole.TOOL.value,
                content=json.dumps({
                    "status": "error",
                    "error": str(e)
                }, ensure_ascii=False),
                tool_call_id=f"call_memory_recall_{str(uuid.uuid4())[:8]}",
                message_type=MessageType.ERROR.value,
                agent_name=self.agent_name
            )
            yield [error_chunk]

    async def _generate_search_query(
        self,
        messages: List[Dict[str, Any]],
        session_context: SessionContext
    ) -> str:
        """
        基于消息生成搜索查询

        Args:
            messages: 消息列表
            session_context: 会话上下文

        Returns:
            str: 搜索查询字符串
        """
        logger.debug("MemoryRecallAgent: 生成搜索查询")

        # 生成提示
        memory_query_template = PromptManager().get_agent_prompt_auto(
            'memory_recall_template',
            language=session_context.get_language()
        )
        
        prompt = memory_query_template.format(
            messages=json.dumps(messages, ensure_ascii=False, indent=2)
        )
        
        llm_request_messages = [
            *await self.prepare_unified_system_messages(
                session_id=session_context.session_id,
                language=session_context.get_language(),
                include_sections=['role_definition', 'system_context']
            ),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                message_type=MessageType.GUIDE.value
            )
        ]

        # 调用LLM生成搜索查询
        search_query = await self._get_search_query(llm_request_messages, session_context.session_id)
        
        # 如果search_query为空，返回空字符串（代表不需要搜索记忆）
        if not search_query:
            logger.debug("MemoryRecallAgent: 搜索查询为空，跳过记忆搜索")
            return ""
        
        return search_query

    async def _get_search_query(
        self, 
        llm_request_messages: List[MessageChunk], 
        session_id: str
    ) -> str:
        """
        调用LLM获取搜索查询

        Args:
            llm_request_messages: LLM请求消息列表
            session_id: 会话ID

        Returns:
            str: 搜索查询字符串
        """
        logger.debug("MemoryRecallAgent: 调用LLM获取搜索查询")

        response = self._call_llm_streaming(
            messages=llm_request_messages,
            session_id=session_id,
            step_name="memory_recall",
            model_config_override={
                'max_tokens': 128,
                'model_type': 'fast',  # 使用快速模型
                'response_format': {'type': 'json_object'}  # 要求JSON返回
            },
            enable_thinking=False
        )

        # 收集流式响应内容
        all_content = ""
        async for chunk in response:
            if len(chunk.choices) == 0:
                continue
            if chunk.choices[0].delta.content:
                all_content += chunk.choices[0].delta.content

        try:
            # 尝试解析JSON
            result_clean = MessageChunk.extract_json_from_markdown(all_content)
            result = json.loads(result_clean)
            
            # 支持两种返回格式：字符串或包含query字段的字典
            if isinstance(result, str):
                return result.strip()
            elif isinstance(result, dict):
                query = result.get('query', '')
                if query:
                    return query.strip()
            
            return ""
        except json.JSONDecodeError:
            # 如果不是JSON，直接使用文本内容（去除markdown标记）
            clean_text = all_content.strip()
            if clean_text.startswith('```'):
                lines = clean_text.split('\n')
                if len(lines) > 2:
                    clean_text = '\n'.join(lines[1:-1])
            return clean_text.strip()

    async def _search_memory(
        self,
        query: str,
        session_context: SessionContext
    ) -> List[Dict[str, Any]]:
        """
        调用 search_memory 工具搜索记忆

        Args:
            query: 搜索查询
            session_context: 会话上下文

        Returns:
            List[Dict[str, Any]]: 搜索结果列表
        """
        logger.debug(f"MemoryRecallAgent: 调用 search_memory 工具，查询: {query}")

        try:
            # 获取 tool_manager 并确保 search_memory 可用
            tool_manager = _ensure_search_memory_available(session_context)
            if not tool_manager:
                logger.warning("MemoryRecallAgent: tool_manager 不可用")
                return []
            
            # 调用 search_memory 工具（使用 run_tool_async 方法）
            result_raw = await tool_manager.run_tool_async(
                'search_memory',
                session_id=session_context.session_id,
                query=query,
                top_k=5
            )
            
            # run_tool_async 返回的是 JSON 字符串，需要解析
            if isinstance(result_raw, str):
                result = json.loads(result_raw)
                logger.debug(f"MemoryRecallAgent: Parsed result from JSON: {result}")
                # 有些工具返回 {"content": {...}} 的包装格式
                if 'content' in result:
                    content = result['content']
                    logger.info(f"MemoryRecallAgent: content type: {type(content)}, content: {content[:200] if isinstance(content, str) else content}")
                    if isinstance(content, dict):
                        result = content
                    elif isinstance(content, str):
                        # content 是 JSON 字符串，需要再次解析
                        result = json.loads(content)
                    logger.debug(f"MemoryRecallAgent: Unwrapped content: {result}")
            elif isinstance(result_raw, dict):
                result = result_raw
                logger.debug(f"MemoryRecallAgent: Result is dict: {result}")
            else:
                logger.warning(f"MemoryRecallAgent: 未知的返回类型: {type(result_raw)}")
                return []
            
            logger.info(f"MemoryRecallAgent: Final result keys: {result.keys() if isinstance(result, dict) else 'N/A'}, status: {result.get('status') if isinstance(result, dict) else 'N/A'}")
            
            if result.get('status') == 'success':
                # 获取长期记忆和会话历史
                long_term_memory = result.get('long_term_memory', [])
                session_history = result.get('session_history', [])
                
                # 合并所有记忆
                all_memories = []
                
                # 添加长期记忆
                for item in long_term_memory:
                    all_memories.append({
                        "type": "file",
                        "path": item.get('path', ''),
                        "snippets": item.get('snippets', [])
                    })
                
                # 添加会话历史
                for item in session_history:
                    all_memories.append({
                        "type": "history",
                        "role": item.get('role', ''),
                        "content_preview": item.get('content_preview', ''),
                        "timestamp": item.get('timestamp')
                    })
                
                logger.info(f"MemoryRecallAgent: 成功召回 {len(all_memories)} 条记忆 (文件: {len(long_term_memory)}, 历史: {len(session_history)})")
                return all_memories
            else:
                error_msg = result.get('message', 'Unknown error')
                logger.warning(f"MemoryRecallAgent: 搜索失败: {error_msg}")
                return []
                
        except Exception as e:
            logger.error(f"MemoryRecallAgent: 调用 search_memory 工具时出错: {str(e)}")
            return []
