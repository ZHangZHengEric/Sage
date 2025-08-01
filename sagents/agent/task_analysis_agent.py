import traceback
from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, Optional, Generator
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole,MessageType
from sagents.context.session_context import SessionContext
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_base import AgentToolSpec
import json
import uuid
from copy import deepcopy

class TaskAnalysisAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.ANALYSIS_PROMPT_TEMPLATE = """请仔细分析以下对话，并以自然流畅的语言解释你的思考过程：
对话记录：
{conversation}

当前有以下的工具可以使用：
{available_tools}



请按照以下步骤进行分析：
首先，我需要理解用户的核心需求。从对话中可以提取哪些关键信息？用户真正想要实现的目标是什么？

接下来，我会逐步分析这个任务。具体来说，需要考虑以下几个方面：
- 任务的背景和上下文
- 需要解决的具体问题 
- 可能涉及的数据或信息来源 
- 潜在的解决方案路径

在分析过程中，我会思考：
- 哪些信息是已知的、可以直接使用的
- 哪些信息需要进一步验证或查找
- 可能存在的限制或挑战
- 最优的解决策略是什么

最后，我会用清晰、自然的语言总结分析结果，包括：
- 对任务需求的详细解释
- 具体的解决步骤和方法
- 需要特别注意的关键点
- 任何可能的备选方案

请用完整的段落形式表达你的分析，就像在向同事解释你的思考过程一样自然流畅。直接输出分析，不要添加额外的解释或注释，以及质问用户。尽可能口语化。不要说出工具的原始名称以及数据库或者知识库的ID。
"""
        self.SYSTEM_PREFIX_FIXED = """你是一个任务分析智能体，专门负责分析任务并将其分解为组件。请仔细理解用户需求，提供清晰、自然的分析过程。"""
        self.agent_name = "TaskAnalysisAgent"
        self.agent_description = "任务分析智能体，专门负责分析任务并将其分解为组件"
        logger.info("TaskAnalysisAgent 初始化完成")

    def run_stream(self, session_context: SessionContext, tool_manager: Optional[Any] = None, session_id: str = None) -> Generator[List[MessageChunk], None, None]:
                # 从会话管理中，获取消息管理实例
        message_manager = session_context.message_manager
        # 从消息管理实例中，获取满足context 长度限制的消息
        history_messages = message_manager.filter_messages(context_length_limited=10000,
                                                          accept_message_type=[],
                                                          recent_turns=10)
        yield from self._execute_analysis_stream_internal(history_messages, tool_manager, session_id)

    def _execute_analysis_stream_internal(self, messages: List[MessageChunk], tool_manager: ToolManager, session_id: str) -> Generator[List[MessageChunk], None, None]:
        logger.info("TaskAnalysisAgent: 开始执行流式任务分析")

        # 只保留 最后一条 user 之后的消息
        recent_message = []
        for index in range(len(messages)-1,-1,-1):
            if messages[index].role == MessageRole.USER.value:
                recent_message = messages[index:]
                break
        
        # recent_message 中只保留 user 以及final answer
        recent_message = [message for message in recent_message if message.role == MessageRole.USER.value or message.role == MessageRole.FINAL_ANSWER.value]
        recent_message_str = MessageManager.convert_messages_to_str(recent_message)
        
        available_tools = tool_manager.list_tools_simplified() if tool_manager else []
        # 只提取工具名称，不显示描述
        tool_names = [tool['name'] for tool in available_tools]
        available_tools_str = ", ".join(tool_names) if tool_names else "无可用工具"
        logger.debug(f"TaskAnalysisAgent: 可用工具数量: {len(available_tools)}")

        
        prompt = self.ANALYSIS_PROMPT_TEMPLATE.format(
            conversation=recent_message_str,
            available_tools=available_tools_str,
        )

        # 为整个分析流程生成统一的message_id
        message_id = str(uuid.uuid4())
        yield [MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="Thinking: ",
            message_id=message_id,
            show_content="",
            message_type=MessageType.TASK_ANALYSIS.value
        )]

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

        for llm_repsonse_chunk in self._call_llm_streaming(
            messages=llm_request_message,
            session_id=session_id,
            step_name="task_analysis",
        ):
            # print(llm_repsonse_chunk)
            if len(llm_repsonse_chunk.choices) == 0:
                continue
            if llm_repsonse_chunk.choices[0].delta.content:
                if len(llm_repsonse_chunk.choices[0].delta.content) > 0:
                    yield [MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content=llm_repsonse_chunk.choices[0].delta.content,
                        message_id=message_id,
                        show_content=llm_repsonse_chunk.choices[0].delta.content,
                        message_type=MessageType.TASK_ANALYSIS.value
                    )]
            elif hasattr(llm_repsonse_chunk.choices[0].delta, 'reasoning_content') and llm_repsonse_chunk.choices[0].delta.reasoning_content is not None:
                yield [MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content="",
                        message_id=message_id,
                        show_content=llm_repsonse_chunk.choices[0].delta.reasoning_content,
                        message_type=MessageType.TASK_ANALYSIS.value
                    )]
            