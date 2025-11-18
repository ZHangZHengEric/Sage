
from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, Optional, Generator
from sagents.utils.logger import logger
from sagents.tool.tool_manager import ToolManager
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import SessionContext
from sagents.utils.prompt_manager import PromptManager
import json
import uuid
import re
from copy import deepcopy


class TaskRewriteAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = "", max_model_len: int = 64000):
        super().__init__(model, model_config, system_prefix, max_model_len)
        self.SYSTEM_PREFIX_FIXED = PromptManager().get_agent_prompt("TaskRewriteAgent", "task_rewrite_system_prefix", "zh", "")
        self.agent_name = "TaskRewriteAgent"
        self.agent_description = "任务请求重写智能体，专门负责重写用户的请求"
        logger.info("TaskRewriteAgent 初始化完成")

    async def run_stream(self, session_context: SessionContext, tool_manager: ToolManager = None, session_id: str = None) -> Generator[List[MessageChunk], None, None]:
        # 重新获取系统前缀，使用正确的语言
        self.SYSTEM_PREFIX_FIXED = PromptManager().get_agent_prompt("TaskRewriteAgent", "task_rewrite_system_prefix", session_context.get_language(), "")

        message_manager = session_context.message_manager
        history_messages = message_manager.extract_all_context_messages(recent_turns=3, max_length=self.max_history_context_length)
        dialogue_history = MessageManager.convert_messages_to_dict_for_request(history_messages)

        last_user_message = message_manager.get_last_user_message()
        if last_user_message is None:
            yield []
            return
        latest_request = last_user_message.content

        rewrite_template = PromptManager().get_agent_prompt_auto("rewrite_template", language=session_context.get_language())
        prompt = rewrite_template.format(dialogue_history=dialogue_history, latest_request=latest_request)
        message_id = str(uuid.uuid4())
        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                show_content=prompt,
                message_type=MessageType.TASK_ANALYSIS.value
            )
        ]
        all_rewrite_chunks_content = ''
        async for llm_repsonse_chunk in self._call_llm_streaming(
            messages=llm_request_message,
            session_id=session_id,
            step_name="request_rewrite"
        ):
            if len(llm_repsonse_chunk.choices) == 0:
                continue
            if llm_repsonse_chunk.choices[0].delta.content:
                if len(llm_repsonse_chunk.choices[0].delta.content) > 0:
                    all_rewrite_chunks_content += llm_repsonse_chunk.choices[0].delta.content
                    yield [MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content=llm_repsonse_chunk.choices[0].delta.content,
                        message_id=message_id,
                        show_content="",
                        message_type=MessageType.REWRITE.value
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
            rewrite_request = json.loads(MessageChunk.extract_json_from_markdown(all_rewrite_chunks_content))['rewrite_request']
        except:
            rewrite_request = all_rewrite_chunks_content
        session_context.audit_status['task_rewrite'] = rewrite_request
        logger.info(f"TaskRewriteAgent: 重写后的请求: {rewrite_request}")
