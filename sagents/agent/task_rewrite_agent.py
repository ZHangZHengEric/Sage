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

class TaskRewriteAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = "", max_model_len: int = 64000):
        super().__init__(model, model_config, system_prefix, max_model_len)
        self.REWRITE_PROMPT_TEMPLATE ="""# 用户请求重写指南
## 任务描述
根据用户的历史对话以及最新的请求，重写用户最新的请求，目的是在不阅读历史对话的情况下，通过阅读重写后的请求，也能准确的明确用户的意图。

## 任务要求
1. 重写后的请求，要详细精确的描述用户的需求，不能有模糊的地方。
2. 如果新的请求与历史对话相关，要整合历史对话的信息到重写后的请求中。
3. 如果有必要需要对对话的历史进行总结，加入到重写后的请求中。
4. 如果对话历史中的信息（如相关的id或者指代信息等），对于新的请求有帮助，要整合到重写后的请求中。
5. 不要回答用户的问题，仅仅是把用户的问题进行重写，变得更加精确。
6. 如果用户的请求，与历史对话没有直接的关联，则直接输出最新请求，当做重写后的请求。
7. 重写后的请求，要与用户的历史对话保持一致的风格和语言。

## 输出格式要求
1. json格式
2. 字段：rewrite_request
示例：
{{
    "rewrite_request": "xx"
}}

## 对话历史
{dialogue_history}

## 最新请求
{latest_request}

## 重写后的请求
"""
        self.SYSTEM_PREFIX_FIXED = """你是一个智能AI助手，专门负责重写用户的请求。你需要根据用户的历史对话以及最新的请求，重写用户最新的请求。禁止回答用户的请求，只能重写用户的请求。"""
        self.agent_name = "TaskRewriteAgent"
        self.agent_description = "任务请求重写智能体，专门负责重写用户的请求"
        logger.info("TaskRewriteAgent 初始化完成")
    
    def run_stream(self, session_context: SessionContext, tool_manager: ToolManager = None, session_id: str = None) -> Generator[List[MessageChunk], None, None]:
        message_manager = session_context.message_manager
        history_messages = message_manager.extract_all_context_messages(recent_turns=3,max_length=self.max_history_context_length)
        dialogue_history = MessageManager.convert_messages_to_dict_for_request(history_messages)

        last_user_message = message_manager.get_last_user_message()
        if last_user_message is None:
            return []
        latest_request = last_user_message.content
        
        prompt = self.REWRITE_PROMPT_TEMPLATE.format(dialogue_history=dialogue_history, latest_request=latest_request)
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
        all_rewrite_chunks_content=  ''
        for llm_repsonse_chunk in self._call_llm_streaming(
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
