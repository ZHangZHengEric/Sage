from typing import List, Dict, Any, Optional
import json
from agents.agent.agent_base import AgentBase
from agents.utils.logger import logger
import uuid
import datetime
class TaskSummaryAgent(AgentBase):

    def run_stream(self, messages: List[Dict[str, Any]],
                 tool_manager: Optional[Any] = None,
                 context: Optional[Dict[str, Any]] = None,
                 session_id: str = None):
        """
        Stream summary analysis with same output format as run().
        
        Args:
            messages: Conversation history
            tool_manager: Optional tool manager
            context: Additional context
            
        Yields:
            Dict: Same format as run() but streamed
        """
        logger.info(f"TaskSummaryAgent.run_stream: Starting task summary with {len(messages)} messages")
        # Prepare prompt same as run()
        task_description = self._extract_task_description(messages)
        logger.debug(f"TaskSummaryAgent.run_stream: Extracted task description of length {len(task_description)}")
        completed_actions = self._extract_completed_actions(messages)
        logger.debug(f"TaskSummaryAgent.run_stream: Extracted completed actions of length {len(completed_actions)}")
        if len(self.system_prefix)==0:
            self.system_prefix = """你是一个任务总结者，你需要根据原始任务和执行历史，生成清晰完整的回答。"""
        current_time  = context.get('current_time',datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        file_workspace = context.get('file_workspace','无')
        system_message = {
                'role':'system',
                'content': self.system_prefix+'''
你的当前工作目录是：{file_workspace}
当前时间是：{current_time}
你当前数据库_id或者知识库_id：{session_id}
'''.format(session_id=session_id,current_time=current_time,file_workspace=file_workspace)
        }

        prompt = """根据以下任务和执行历史，用自然语言提供清晰完整的回答。
可以使用markdown格式组织内容。

任务: 
{task_description}

执行历史:
{completed_actions}

你的回答应该:
1. 直接回答原始任务。
2. 使用清晰详细的语言，但要保证回答的完整性和准确性，保留执行过程中的关键结果。
3. 不要引用没有出现在执行历史中的文件。
"""
        logger.debug("TaskSummaryAgent.run_stream: Generated summary prompt")
        
        # Stream response from LLM
        logger.info("TaskSummaryAgent.run_stream: Calling LLM with streaming enabled")
        full_response = ""
        chunk_count = 0
        message_id = str(uuid.uuid4())
        for chunk in self.model.chat.completions.create(
            messages=[system_message] +[{"role": "user", "content": prompt.format(task_description=task_description, completed_actions=completed_actions)}],
            stream=True,
            **self.model_config
        ):
            if chunk.choices[0].delta.content is not None:
                delta_content = chunk.choices[0].delta.content
                chunk_count += 1
                yield [{
                    'role': 'assistant',
                    'content': delta_content,
                    'type': 'final_answer',
                    "message_id":message_id,
                    "show_content": delta_content
                }]
        logger.info(f"TaskSummaryAgent.run_stream: Streamed {chunk_count} chunks from LLM with total response length {len(full_response)}")

    
    
    def _extract_task_description(self, messages):
        """Extract original task description from messages."""
        logger.debug(f"TaskSummaryAgent._extract_task_description: Processing {len(messages)} messages")
        task_description_messages = self._extract_task_description_messages(messages)
        result = self.convert_messages_to_str(task_description_messages)
        logger.debug(f"TaskSummaryAgent._extract_task_description: Generated task description of length {len(result)}")
        return result

    def _extract_completed_actions(self, messages):
        """Extract completed actions from messages."""
        logger.debug(f"TaskSummaryAgent._extract_completed_actions: Processing {len(messages)} messages")
        completed_actions_messages = self._extract_completed_actions_messages(messages)
        result = self.convert_messages_to_str(completed_actions_messages)
        logger.debug(f"TaskSummaryAgent._extract_completed_actions: Generated completed actions of length {len(result)}")
        return result
        