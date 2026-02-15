from sagents.utils.prompt_manager import PromptManager
from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, AsyncGenerator, Optional
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import SessionContext
from sagents.tool.tool_manager import ToolManager
import json
import uuid

class TaskObservationAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "ObservationAgent"
        self.agent_description = "观测智能体，专门负责基于当前状态生成下一步执行计划"
        logger.debug("TaskObservationAgent 初始化完成")

    async def run_stream(self, session_context: SessionContext, tool_manager: Optional[ToolManager] = None, session_id: Optional[str] = None) -> AsyncGenerator[List[MessageChunk], None]:
        # 重新获取系统前缀，使用正确的语言
        current_system_prefix = PromptManager().get_agent_prompt_auto('task_observation_system_prefix', language=session_context.get_language())

        message_manager = session_context.message_manager
        

        history_messages = message_manager.extract_all_context_messages(recent_turns=3)
        # 根据 active_budget 压缩消息
        budget_info = message_manager.context_budget_manager.budget_info
        if budget_info:
            history_messages = MessageManager.compress_messages(history_messages, min(budget_info.get('active_budget', 8000), 8000))
        history_messages_str = MessageManager.convert_messages_to_str(history_messages)

        # 获取近期执行结果
        # recent_execution_results_messages = message_manager.extract_after_last_observation_messages()
        # recent_execution_results_messages_str = MessageManager.convert_messages_to_str(recent_execution_results_messages)

        # 合并为 task_description
        # task_description_messages_str = f"{history_messages_str}\n\nRecent Execution Results:\n{recent_execution_results_messages_str}"

        # 构建 Prompt
        prompt = PromptManager().get_agent_prompt_auto('observation_template', language=session_context.get_language()).format(
            task_description=history_messages_str,
            agent_description=self.system_prefix
        )

        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id, language=session_context.get_language(), system_prefix_override=current_system_prefix),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                message_type=MessageType.OBSERVATION.value
            )
        ]

        # 准备工具 - 只使用 todo_write
        tools_json = []
        if tool_manager:
            # 获取所有工具并筛选 todo_write
            all_tools = tool_manager.get_openai_tools(lang=session_context.get_language())
            todo_write_tool = next((t for t in all_tools if t['function']['name'] == 'todo_write'), None)
            
            if todo_write_tool:
                tools_json.append(todo_write_tool)

        message_id = str(uuid.uuid4())
        all_content = ''
        
        # 调用 LLM 并处理响应（包括工具调用）
        # 这里我们使用类似 SimpleAgent 的逻辑，处理流式输出和工具调用
        # 由于 ObservationAgent 通常只进行一次分析和状态更新，我们不需要复杂的循环
        
        async for chunk in self._call_llm_and_process_response(
            messages=llm_request_message,
            tools_json=tools_json,
            tool_manager=tool_manager,
            session_context=session_context,
            session_id=session_id,
            step_name="observation"
        ):
            # 过滤掉工具调用的中间消息，只保留文本内容作为 observation 输出
            # 或者，我们可以让用户看到工具调用（更新任务状态），这通常是有帮助的
            # 但为了保持 observation 的纯净，我们可能只想输出分析文本
            
            # 这里我们直接透传 chunk，因为 AgentBase 的 _call_llm_and_process_response 已经处理好了格式
            # 但是要注意 message_type，我们需要保持一致性
            for msg in chunk:
                if msg.role == MessageRole.ASSISTANT.value and msg.content:
                    all_content += msg.content
                # 强制设置 message_type 为 OBSERVATION
                msg.message_type = MessageType.OBSERVATION.value
            yield chunk

        # 保存简单的文本观测结果
        if "all_observations" not in session_context.audit_status:
            session_context.audit_status["all_observations"] = []
        
        session_context.audit_status["all_observations"].append({
            "analysis": all_content,
            "timestamp": str(uuid.uuid4()) # 简单的时间戳或ID
        })

        # 检查是否所有任务都已完成
        # 重新获取最新的 todo_list (因为工具调用可能更新了它)
        latest_todo_list = session_context.system_context.get('todo_list', [])
        if latest_todo_list:
            all_completed = all(todo.get('completed', False) for todo in latest_todo_list)
            if all_completed:
                logger.info(f"ObservationAgent: 检测到所有任务均已完成 (共 {len(latest_todo_list)} 个)")
                session_context.audit_status['task_completed'] = True
            else:
                session_context.audit_status['task_completed'] = False
                # 计算完成进度
                completed_count = sum(1 for todo in latest_todo_list if todo.get('completed', False))
                logger.info(f"ObservationAgent: 任务进度: {completed_count}/{len(latest_todo_list)}")

    async def _call_llm_and_process_response(
        self, 
        messages: List[MessageChunk], 
        tools_json: List[Dict], 
        tool_manager: ToolManager, 
        session_context: SessionContext, 
        session_id: str, 
        step_name: str
    ) -> AsyncGenerator[List[MessageChunk], None]:
        """
        辅助方法：调用 LLM，处理流式文本输出，并自动执行工具调用
        """
        # 第一次调用 LLM
        response_message = MessageChunk(role=MessageRole.ASSISTANT.value, content="")
        tool_calls = []
        model_config_override = {'tools': tools_json if tools_json else None}
        async for chunk in self._call_llm_streaming(
            messages=messages,
            session_id=session_id,
            step_name=step_name,
            model_config_override=model_config_override
        ):
            # 处理 delta
            if chunk.choices and chunk.choices[0].delta:
                delta = chunk.choices[0].delta
                if delta.content:
                    response_message.content += delta.content
                    yield [MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content=delta.content,
                        message_id=response_message.message_id,
                        message_type=MessageType.OBSERVATION.value
                    )]
                
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        if len(tool_calls) <= tc.index:
                            tool_calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                        if tc.id:
                            tool_calls[tc.index]["id"] += tc.id
                        if tc.function.name:
                            tool_calls[tc.index]["function"]["name"] += tc.function.name
                        if tc.function.arguments:
                            tool_calls[tc.index]["function"]["arguments"] += tc.function.arguments

        # 如果有工具调用，执行它们
        if tool_calls:
            # 记录工具调用消息
            response_message.tool_calls = tool_calls
            
            messages.append(response_message)
            
            # 发送工具调用消息
            for tool_call in tool_calls:
                yield self._create_tool_call_message(tool_call)

            for tool_call in tool_calls:
                function_name = tool_call["function"]["name"]
                arguments = tool_call["function"]["arguments"]
                tool_call_id = tool_call["id"]
                
                logger.info(f"ObservationAgent: 执行工具 {function_name}")
                
                # 执行工具
                # 使用基类的 _execute_tool 方法
                # 构造符合 _execute_tool 要求的 tool_call 结构
                # _execute_tool 需要 tool_call 字典，包含 function: {name, arguments}
                # 这里 accumulated tool_calls 已经是这个结构了
                
                # 构造 messages_input (虽然 _execute_tool 可能不需要它来执行工具，但为了接口一致)
                messages_input = messages
                
                async for chunk in self._execute_tool(
                    tool_call=tool_call,
                    tool_manager=tool_manager,
                    messages_input=messages_input,
                    session_id=session_id
                ):
                    yield chunk
