from typing import List, Dict, Any, Optional
import json
import datetime
from agents.agent.agent_base import AgentBase
from agents.utils.logger import logger
import traceback
import uuid
class TaskAnalysisAgent(AgentBase):
    """Agent responsible for analyzing tasks and breaking them into components."""
    
    def run_stream(self, messages: List[Dict[str, Any]], 
                 tool_manager: Optional[Any] = None,
                 context: Optional[Dict[str, Any]] = None,
                 session_id: str = None):
        """
        Stream task analysis with same output format as run().
        
        Args:
            messages: Conversation history
            tool_manager: Optional tool manager
            context: Additional context
            
        Yields:
            List: Same format as run() but streamed
        """
        logger.info(f"TaskAnalysisAgent.run_stream: Starting task analysis with {len(messages)} messages")
        # Prepare prompt same as run()
        conversation = self._extract_task_description_messages(messages)
        conversation = self.convert_messages_to_str(conversation)
        available_tools = tool_manager.list_tools_simplified()  
        logger.info(f"TaskAnalysisAgent.run_stream: Prepared conversation context of length {len(conversation)}")
        
        prompt = """请仔细分析以下对话，并以自然流畅的语言解释你的思考过程：
对话记录：
{conversation}

当前有以下的工具可以使用：
{available_tools}

当前你可访问的数据库或者知识库的ID是：
{session_id}

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
当前时间是 {current_datatime_str}
"""

        logger.debug("TaskAnalysisAgent.run_stream: Generated analysis prompt")
        print('streaming task analysis agent')
        message_id = str(uuid.uuid4())
        yield [{
            'role': 'assistant',
            'content': "Thinking: ",
            'type': 'task_analysis_result',
            'message_id': message_id,
            'show_content':""
        }]
        try:
            # Stream response from LLM
            logger.info("TaskAnalysisAgent.run_stream: Calling LLM with streaming enabled")
            chunk_count = 0
            for chunk in self.model.chat.completions.create(
                messages=[{"role": "user", "content": prompt.format(
                    conversation=conversation,
                    available_tools=available_tools,
                    current_datatime_str=context.get('current_datatime_str', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                    session_id=session_id)}],
                stream=True,
                **self.model_config
            ):
                if chunk.choices[0].delta.content:
                    delta_content =  chunk.choices[0].delta.content
                    chunk_count += 1
                    yield [{
                        'role': 'assistant',
                        'content':  delta_content,
                        'type': 'task_analysis_result',
                        'message_id': message_id,
                        "show_content": delta_content
                    }]
            logger.info(f"TaskAnalysisAgent.run_stream: Streamed {chunk_count} chunks from LLM")
            # 在返回一条换行消息
            yield [{
                'role': 'assistant',
                'content':  "",
                'type': 'task_analysis_result',
                'message_id': message_id,
                "show_content": "\n"
            }]
        except Exception as e:
            logger.error(f"TaskAnalysisAgent.run_stream: Exception during streaming: {str(e)}")
            logger.error(traceback.format_exc())
            print(traceback.format_exc())
            yield [{
                'role': 'tool',
                'content': f"\n思考失败 {str(e)}",
                'type': 'task_analysis_result',
                'message_id': message_id,
                "show_content": f"\n思考失败 {str(e)}"

            }]
