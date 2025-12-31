from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from sagents.utils.prompt_manager import PromptManager
from typing import Any, Dict, List, Optional, AsyncGenerator
from sagents.utils.logger import logger
from sagents.tool.tool_manager import ToolManager
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import SessionContext

import json
import uuid
from openai import AsyncOpenAI


class TaskRouterAgent(AgentBase):
    def __init__(self, model: Optional[AsyncOpenAI] = None, model_config: Optional[Dict[str, Any]] = None, system_prefix: str = ""):
        if model_config is None:
            model_config = {}
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "TaskRouterAgent"
        self.agent_description = "任务路由智能体，专门负责根据用户的任务描述路由到合适的智能体"
        logger.info("TaskRouterAgent 初始化完成")

    async def run_stream(self, session_context: SessionContext, tool_manager: Optional[ToolManager] = None, session_id: Optional[str] = None) -> AsyncGenerator[List[MessageChunk], None]:
        message_manager = session_context.message_manager
        history_messages = message_manager.extract_all_context_messages(recent_turns=3)
        task_desc = MessageManager.convert_messages_to_dict_for_request(history_messages)

        available_tools_name = tool_manager.list_all_tools_name() if tool_manager else []
        available_tools_str = ", ".join(available_tools_name) if available_tools_name else "无可用工具"

        router_template = PromptManager().get_agent_prompt_auto("router_template", language=session_context.get_language())
        prompt = router_template.format(tool_list=available_tools_str, task_desc=task_desc)
        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id, language=session_context.get_language()),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                show_content=prompt,
                message_type=MessageType.TASK_ROUTER.value
            )
        ]
        all_task_router_chunks_content = ''
        message_id = str(uuid.uuid4())
        async for llm_repsonse_chunk in self._call_llm_streaming(
            messages=llm_request_message,
            session_id=session_id,
            step_name="task_router"
        ):
            if len(llm_repsonse_chunk.choices) == 0:
                continue
            if llm_repsonse_chunk.choices[0].delta.content:
                if len(llm_repsonse_chunk.choices[0].delta.content) > 0:
                    all_task_router_chunks_content += llm_repsonse_chunk.choices[0].delta.content
                    yield [MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content="",
                        message_id=message_id,
                        show_content="",
                        message_type=MessageType.TASK_ROUTER.value
                    )]
            elif hasattr(llm_repsonse_chunk.choices[0].delta, 'reasoning_content') and llm_repsonse_chunk.choices[0].delta.reasoning_content is not None:
                yield [MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="",
                    message_id=message_id,
                    show_content="",
                    message_type=MessageType.TASK_ANALYSIS.value
                )]
        try:
            task_router_result = json.loads(MessageChunk.extract_json_from_markdown(all_task_router_chunks_content))
        except Exception:
            logger.warning("TaskRouterAgent: 路由结果解析失败，使用默认值")
            logger.warning(f"TaskRouterAgent: 路由结果解析失败，原始内容：{all_task_router_chunks_content}")
            task_router_result = {"agent_name": "单智能体", "deep_think": False}
        session_context.audit_status['router_agent'] = task_router_result["agent_name"]
        session_context.audit_status['deep_thinking'] = task_router_result["deep_think"]
        logger.info(f"TaskRouterAgent: 路由结果: {task_router_result}")
