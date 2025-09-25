import traceback
from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, Optional, Generator
from sagents.utils.logger import logger
from sagents.tool.tool_manager import ToolManager
from sagents.context.messages.message import MessageChunk, MessageRole,MessageType
from sagents.context.session_context import SessionContext
from sagents.context.tasks.task_base import TaskBase
from sagents.context.tasks.task_manager import TaskManager
import json
import uuid,re
from copy import deepcopy
from openai import OpenAI

class TaskRouterAgent(AgentBase):
    def __init__(self, model: Optional[OpenAI] = None, model_config: Dict[str, Any] = ..., system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.ROUTER_PROMPT_TEMPLATE = """
你是一个任务路由智能体，你的任务是根据用户的任务描述，将任务路由到不同的智能体以及是否需要深度思考。不同的智能体与深度思考没有直接的关系，只是为了更好的完成任务。

选择智能体的规则：
- 如果用户的任务描述需要复杂的计算或逻辑处理，比如需要调用至少两次外部工具（比如多次搜索信息），选择多智能体。
- 如果用户的任务描述简单明了，比如只需要调用一次外部工具或者不调用外部工具，选择单智能体。
- 当用户表达之前的任务执行的有问题时，选择多智能体。

深度思考判断规则：
- 当用户的任务表达简单清晰，不需要复杂的逻辑推理，则深度思考为false。
- 当用户的任务表达复杂，需要复杂的逻辑推理，则深度思考为true。
- 当用户的任务表达模糊不清晰，不确定是否需要复杂的逻辑推理，则深度思考为true。
- 当用户表达之前的任务执行的有问题时，深度思考为true。

当前的智能体列表：
1. 多智能体
2. 单智能体

当前的工具列表：
{tool_list}

用户的任务描述：
{task_desc}

请根据用户的任务描述，路由到合适的智能体。

输出格式为json，key为agent_name，value为智能体的名称，deep_think为是否需要深度思考
示例：
{{
    "agent_name": "多智能体",
    "deep_think": false
}}
"""
        self.agent_name = "TaskRouterAgent"
        self.agent_description = "任务路由智能体，专门负责根据用户的任务描述路由到合适的智能体"
        logger.info("TaskRouterAgent 初始化完成")
    def run_stream(self, session_context: SessionContext, tool_manager: ToolManager = None, session_id: str = None) -> Generator[List[MessageChunk], None, None]:
        message_manager = session_context.message_manager
        history_messages = message_manager.extract_all_context_messages(recent_turns=3,max_length=self.max_history_context_length)
        task_desc = MessageManager.convert_messages_to_dict_for_request(history_messages)

        available_tools_name = tool_manager.list_all_tools_name() if tool_manager else []
        available_tools_str = ", ".join(available_tools_name) if available_tools_name else "无可用工具"

        prompt = self.ROUTER_PROMPT_TEMPLATE.format(tool_list=available_tools_str, task_desc=task_desc)
        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                show_content=prompt,
                message_type=MessageType.TASK_ROUTER.value
            )
        ]
        all_task_router_chunks_content=  ''
        message_id = str(uuid.uuid4())
        for llm_repsonse_chunk in self._call_llm_streaming(
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
        except:
            logger.warning(f"TaskRouterAgent: 路由结果解析失败，使用默认值")
            logger.warning(f"TaskRouterAgent: 路由结果解析失败，原始内容：{all_task_router_chunks_content}")
            task_router_result = {"agent_name": "单智能体", "deep_think": False}
        session_context.audit_status['router_agent'] = task_router_result["agent_name"]
        session_context.audit_status['deep_thinking'] = task_router_result["deep_think"]
        logger.info(f"TaskRouterAgent: 路由结果: {task_router_result}")
