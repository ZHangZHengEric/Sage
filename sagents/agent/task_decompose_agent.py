from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, Optional, AsyncGenerator
from sagents.utils.logger import logger
from sagents.tool.tool_manager import ToolManager
from sagents.context.messages.message import MessageChunk, MessageRole,MessageType
from sagents.context.session_context import SessionContext
from sagents.utils.prompt_manager import PromptManager
import json
import uuid
import re
from sagents.tool.tool_schema import convert_spec_to_openai_format


class TaskDecomposeAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "TaskDecomposeAgent"
        self.agent_description = "任务分解智能体，专门负责将复杂任务分解为可执行的子任务"
        logger.debug("TaskDecomposeAgent 初始化完成")

    async def run_stream(self, session_context: SessionContext, tool_manager: Optional[ToolManager] = None, session_id: Optional[str] = None) -> AsyncGenerator[List[MessageChunk], None]:
        # 重新获取系统前缀，使用正确的语言
        current_system_prefix = PromptManager().get_agent_prompt_auto('task_decompose_system_prefix', language=session_context.get_language())

        message_manager = session_context.message_manager
        task_manager = session_context.task_manager

        if 'task_rewrite' in session_context.audit_status:
            recent_message_str = MessageManager.convert_messages_to_str([MessageChunk(
                role=MessageRole.USER.value,
                content = session_context.audit_status['task_rewrite'],
                message_type=MessageType.NORMAL.value
            )])
        else:
            history_messages = message_manager.extract_all_context_messages(recent_turns=5)
            # 根据 active_budget 压缩消息
            budget_info = message_manager.context_budget_manager.budget_info
            if budget_info:
                history_messages = MessageManager.compress_messages(history_messages, min(budget_info.get('active_budget', 8000), 4000))
            recent_message_str = MessageManager.convert_messages_to_str(history_messages)        

        # 准备 todo_write 工具
        tools_json = []
        if tool_manager:
            todo_tool = tool_manager.get_tool('todo_write')
            if todo_tool:
                tools_json.append(convert_spec_to_openai_format(todo_tool, lang=session_context.get_language()))
            else:
                # 如果 tool_manager 中没有，尝试手动加载（虽然不太可能，但为了健壮性）
                try:
                    from sagents.tool.impl.todo_tool import ToDoTool
                    temp_tool = ToDoTool()
                    # 这里我们只是临时用一下 schema，不注册
                    # 但是 convert_spec_to_openai_format 需要 tool_func
                    # 我们暂时跳过，假设 tool_manager 会有
                    logger.warning("TaskDecomposeAgent: todo_write tool not found in tool_manager")
                except ImportError:
                    pass

        available_tools_name = tool_manager.list_all_tools_name() if tool_manager else []
        available_tools_str = ", ".join(available_tools_name) if available_tools_name else "无可用工具"

        prompt = PromptManager().get_agent_prompt_auto('decompose_template', language=session_context.get_language()).format(
            task_description=recent_message_str,
            available_tools_str=available_tools_str,
            agent_description=self.system_prefix,
        )
        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id, language=session_context.get_language(), system_prefix_override=current_system_prefix),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                message_type=MessageType.TASK_DECOMPOSITION.value
            )
        ]
        
        model_config_override = {}
        if tools_json:
            model_config_override['tools'] = tools_json
            model_config_override['tool_choice'] = 'required' # 强制使用工具

        message_id = str(uuid.uuid4())
        
        # 类似 SimpleAgent 的流式处理和工具调用逻辑
        tool_calls: Dict[str, Any] = {}
        last_tool_call_id = None
        
        async for chunk in self._call_llm_streaming(messages=llm_request_message,
                                             session_id=session_id,
                                             step_name="task_decompose",
                                             model_config_override=model_config_override):
            if len(chunk.choices) == 0:
                continue
                
            delta = chunk.choices[0].delta
            
            # 处理工具调用
            if delta.tool_calls:
                self._handle_tool_calls_chunk(chunk, tool_calls, last_tool_call_id or "")
                for tool_call in delta.tool_calls:
                    if tool_call.id:
                        last_tool_call_id = tool_call.id
            
            # 处理内容（如果 LLM 输出思考过程或解释）
            if delta.content:
                 yield [MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content=delta.content,
                    message_id=message_id,
                    message_type=MessageType.TASK_DECOMPOSITION.value
                )]

        # 执行工具调用
        if tool_calls:
            # 发送工具调用消息
            for tool_call in tool_calls.values():
                 yield self._create_tool_call_message(tool_call)

            for tool_call_id, tool_call_info in tool_calls.items():
                function_name = tool_call_info['function']['name']
                arguments = tool_call_info['function']['arguments']
                
                # 构造消息输入上下文（虽然这里可能不需要完整的上下文，但为了接口一致性）
                messages_input = [
                    {'role': 'user', 'content': prompt} 
                ] # 简化版，或者使用 llm_request_message

                async for message_chunk_list in self._execute_tool(
                    tool_call=tool_call_info,
                    tool_manager=tool_manager,
                    messages_input=messages_input,
                    session_id=session_id
                ):
                    # 如果是 todo_write 的结果，我们希望它作为 TASK_DECOMPOSITION 类型返回
                    # 但 _execute_tool 返回的是 TOOL_RESPONSE 类型
                    # 我们可以转换一下，或者让它保持 TOOL_RESPONSE
                    
                    # 之前的逻辑是：
                    # content=f"\n\n任务清单已生成：\n{result}",
                    # message_type=MessageType.TASK_DECOMPOSITION.value
                    
                    # 这里为了保持行为一致，我们可以手动包装一下，或者信任 _execute_tool 的输出
                    # _execute_tool 输出的是 list[MessageChunk]
                    
                    for chunk in message_chunk_list:
                        if chunk.role == MessageRole.TOOL.value:
                            # 我们可以发送一个额外的消息来说明任务已生成
                            yield [MessageChunk(
                                role=MessageRole.ASSISTANT.value,
                                content=f"\n\n任务清单已生成：\n{chunk.content}",
                                message_id=str(uuid.uuid4()),
                                message_type=MessageType.TASK_DECOMPOSITION.value
                            )]
                        else:
                            yield [chunk]
