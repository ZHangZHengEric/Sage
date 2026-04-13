from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, AsyncGenerator
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole,MessageType
from sagents.context.session_context import SessionContext
from sagents.utils.prompt_manager import PromptManager
import uuid
import os
from sagents.tool.tool_schema import convert_spec_to_openai_format


class TaskDecomposeAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "TaskDecomposeAgent"
        self.agent_description = "任务分解智能体，专门负责将复杂任务分解为可执行的子任务"
        logger.debug("TaskDecomposeAgent 初始化完成")

    async def run_stream(
        self,
        session_context: SessionContext,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        if not session_context.tool_manager:
            raise ValueError("ToolManager is not initialized in SessionContext")
        session_id = session_context.session_id
        if self._should_abort_due_to_session(session_context):
            return
        tool_manager = session_context.tool_manager
        session_id = session_context.session_id        # 重新获取系统前缀，使用正确的语言
        current_system_prefix = PromptManager().get_agent_prompt_auto('task_decompose_system_prefix', language=session_context.get_language())

        message_manager = session_context.message_manager

        if 'task_rewrite' in session_context.audit_status:
            recent_message_str = MessageManager.convert_messages_to_str([MessageChunk(
                role=MessageRole.USER.value,
                content = session_context.audit_status['task_rewrite'],
                message_type=MessageType.USER_INPUT.value
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
                # 如果 tool_manager 中没有，记录警告日志
                logger.warning("TaskDecomposeAgent: todo_write tool not found in tool_manager")

        available_tools_name = tool_manager.list_all_tools_name() if tool_manager else []
        available_tools_str = ", ".join(available_tools_name) if available_tools_name else "无可用工具"

        prompt = PromptManager().get_agent_prompt_auto('decompose_template', language=session_context.get_language()).format(
            task_description=recent_message_str,
            available_tools_str=available_tools_str,
            agent_description=self.system_prefix,
        )
        llm_request_message = [
            await self.prepare_unified_system_message(session_id=session_id, language=session_context.get_language(), system_prefix_override=current_system_prefix),
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
        tool_calls_messages_id = str(uuid.uuid4())
        content_response_message_id = str(uuid.uuid4())

        # 类似 SimpleAgent 的流式处理和工具调用逻辑
        tool_calls: Dict[str, Any] = {}
        last_tool_call_id = None
        
        async for chunk in self._call_llm_streaming(messages=llm_request_message,
                                             session_id=session_id,
                                             step_name="task_decompose",
                                             model_config_override=model_config_override,
                                             enable_thinking=False):
            if len(chunk.choices) == 0:
                continue
                
            delta = chunk.choices[0].delta
            
            # 处理工具调用
            if delta.tool_calls:
                self._handle_tool_calls_chunk(chunk, tool_calls, last_tool_call_id or "")
                for tool_call in delta.tool_calls:
                    if tool_call.id:
                        last_tool_call_id = tool_call.id

                # 根据环境变量控制是否流式返回工具调用消息
                # 如果 SAGE_EMIT_TOOL_CALL_ON_COMPLETE=true，则参数完整时才返回工具调用消息
                emit_on_complete = os.environ.get("SAGE_EMIT_TOOL_CALL_ON_COMPLETE", "false").lower() == "true"
                if not emit_on_complete:
                    # 流式返回工具调用消息
                    output_messages = [MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        tool_calls=delta.tool_calls,
                        message_id=tool_calls_messages_id,
                        message_type=MessageType.TOOL_CALL.value
                    )]
                    yield output_messages
                else:
                    # yield 一个空的消息块以避免生成器卡住
                    output_messages = [MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content="",
                        message_id=content_response_message_id,
                        message_type=MessageType.EMPTY.value
                    )]
                    yield output_messages

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
            # 构造消息输入上下文
            messages_input = [
                {'role': 'user', 'content': prompt}
            ]

            # 根据环境变量控制 emit_tool_call_message
            # 如果 SAGE_EMIT_TOOL_CALL_ON_COMPLETE=true，则参数完整时才返回工具调用消息
            emit_on_complete = os.environ.get("SAGE_EMIT_TOOL_CALL_ON_COMPLETE", "false").lower() == "true"
            async for messages, _ in self._handle_tool_calls(
                tool_calls=tool_calls,
                tool_manager=tool_manager,
                messages_input=messages_input,
                session_id=session_id or "",
                emit_tool_call_message=emit_on_complete
            ):
                # 处理工具结果，转换为 TASK_DECOMPOSITION 类型
                for chunk in messages:
                    if chunk.role == MessageRole.TOOL.value:
                        # 发送任务清单已生成的消息
                        yield [MessageChunk(
                            role=MessageRole.ASSISTANT.value,
                            content=f"\n\n任务清单已生成：\n{chunk.content}",
                            message_id=str(uuid.uuid4()),
                            message_type=MessageType.TASK_DECOMPOSITION.value
                        )]
                    else:
                        yield [chunk]
