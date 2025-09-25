
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

class TaskSummaryAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.SUMMARY_PROMPT_TEMPLATE = """根据以下任务和TaskManager状态及执行结果，用自然语言提供清晰完整的回答。
可以使用markdown格式组织内容。

原始任务: 
{task_description}

TaskManager状态及执行结果:
{task_manager_status_and_results}

## 近期完成动作详情
{execution_results}

你的回答应该:
1. 直接了当的回答原始任务，不做任何解释。
2. 使用清晰详细的语言，但要保证回答的完整性和准确性，保留任务执行过程中的关键结果。
3. 如果允许用户下载文档，那么如果任务执行过程中生成了文档，那么在回答中应该包含文档的地址引用，使用markdown的文件连接格式，方便用户下载。
4. 如果允许用户下载文档，那么对于生成的文档，不仅要提供文档地址，还要提供文档内的关键内容摘要。
5. 如果需要显示图表，图表直接使用```echarts ``` 的markdown代码块进行显示。
6. 尽量不要描述执行过程，不是为了总结执行过程，而是以TaskManager中的任务执行结果为基础，生成一个针对用户任务的完美回答。
7. 不要提及TaskManager，这些都是为了提供最终完美答案的材料，你只需要根据这些材料生成满足原始任务的最终答案即可。
8. 不要出现TaskManager状态及执行结果 以及近期完成动作详情 不存在的数据和内容。
9. 如果任务没有执行成功，应该如实的告诉用户任务没有执行成功，而不是编造一个成功的结果。
"""
        self.agent_name = "TaskSummaryAgent"
        self.agent_description = "任务总结智能体，专门负责总结任务执行结果"
        logger.info("TaskSummaryAgent 初始化完成")

    def run_stream(self, session_context: SessionContext, tool_manager: ToolManager = None, session_id: str = None) -> Generator[List[MessageChunk], None, None]:
        message_manager = session_context.message_manager
        task_manager = session_context.task_manager
        
        # 提取任务描述
        if 'task_rewrite' in session_context.audit_status:
            task_description_messages_str = MessageManager.convert_messages_to_str([MessageChunk(
                role=MessageRole.USER.value,
                content = session_context.audit_status['task_rewrite'],
                message_type=MessageType.NORMAL.value
            )])
        else:
            history_messages = message_manager.extract_all_context_messages(recent_turns=3,max_length=self.max_history_context_length)
            task_description_messages_str = MessageManager.convert_messages_to_str(history_messages)

        completed_actions_messages = message_manager.get_all_execution_messages_after_last_user()
        completed_actions_messages_str = MessageManager.convert_messages_to_str(completed_actions_messages)
        
        task_manager_status_and_results = task_manager.get_all_tasks_summary()

        prompt = self.SUMMARY_PROMPT_TEMPLATE.format(
            task_description=task_description_messages_str,
            task_manager_status_and_results=task_manager_status_and_results,
            execution_results=completed_actions_messages_str,
        )
        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                show_content=prompt,
                message_type=MessageType.FINAL_ANSWER.value
            )
        ]
        
        message_id = str(uuid.uuid4())
        for llm_repsonse_chunk in self._call_llm_streaming(messages=llm_request_message,
                                             session_id=session_id,
                                             step_name="final_answer"):
            if len(llm_repsonse_chunk.choices) == 0:
                continue
            if llm_repsonse_chunk.choices[0].delta.content:
                yield [MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content=llm_repsonse_chunk.choices[0].delta.content,
                    message_id=message_id,
                    show_content=llm_repsonse_chunk.choices[0].delta.content,
                    message_type=MessageType.FINAL_ANSWER.value
                )]
