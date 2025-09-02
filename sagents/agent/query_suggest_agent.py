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

class QuerySuggestAgent(AgentBase):
    def __init__(self, model: Optional[OpenAI] = None, model_config: Dict[str, Any] = ..., system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.QUERY_SUGGEST_PROMPT = """
# 建议生成指南
你的任务是根据上述的对话，生成接下来用户可能会问的问题，或者可能帮助用户解决相关更加深入的事情。

## 用户对话
{task_description}

## 要求
1. 建议的问题或者方向要与用户对话相关。
2. 建议的问题或者方向要具有一定的深度，能够帮助用户解决问题。
3. 建议的问题或者方向要具有一定的广度，能够帮助用户探索不同的角度。
4. 只生成3条建议。
5. 每条建议要简洁，不超过20个字符。
6. 建议是站在用户的角度。

## 输出格式
```
<suggest_item>
用户可能会问的问题1或者可以深入探索的方向1
</suggest_item>
<suggest_item>
用户可能会问的问题2或者可以深入探索的方向2
</suggest_item>
<suggest_item>
用户可能会问的问题3或者可以深入探索的方向3
</suggest_item>
```
"""
        self.agent_name = "QuerySuggestAgent"
        self.agent_description = "查询建议智能体，专门负责根据用户对话生成接下来用户可能会问的问题，或者可能帮助用户解决相关更加深入的事情。"
        logger.info("QuerySuggestAgent 初始化完成")

    def run_stream(self, session_context: SessionContext, tool_manager: ToolManager = None, session_id: str = None) -> Generator[List[MessageChunk], None, None]:
        message_manager = session_context.message_manager

        conversation_messages = message_manager.extract_all_context_messages(recent_turns=2,max_length=self.max_history_context_length,last_turn_user_only=False)
        recent_message_str = MessageManager.convert_messages_to_str(conversation_messages)
        prompt = self.QUERY_SUGGEST_PROMPT.format(
            task_description=recent_message_str
        )
        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                show_content=prompt,
                message_type=MessageType.QUERY_SUGGEST.value
            )
        ]
        message_id = str(uuid.uuid4())
        unknown_content = ''
        full_response = ''
        for llm_repsonse_chunk in self._call_llm_streaming(messages=llm_request_message,
                                             session_id=session_id,
                                             step_name="query_suggest"):
            if len(llm_repsonse_chunk.choices) == 0:
                continue
            if llm_repsonse_chunk.choices[0].delta.content:
                delta_content = llm_repsonse_chunk.choices[0].delta.content
                
                for delta_content_char in delta_content:
                    delta_content_all = unknown_content+ delta_content_char
                    delta_content_type = self._judge_delta_content_type(delta_content_all, full_response, ['suggest_item'])
                    
                    full_response += delta_content_char
                    if delta_content_type == 'unknown':
                        unknown_content = delta_content_all
                        continue
                    else:
                        unknown_content = ''
                        if delta_content_type == 'suggest_item':
                            if last_tag_type != 'suggest_item':
                                yield [MessageChunk(
                                    role=MessageRole.ASSISTANT.value,
                                    content='',
                                    message_id=message_id,
                                    show_content='\n- ',
                                    message_type=MessageType.QUERY_SUGGEST.value
                                )]
                            
                            yield [MessageChunk(
                                role=MessageRole.ASSISTANT.value,
                                content="",
                                message_id=message_id,
                                show_content=delta_content_all,
                                message_type=MessageType.QUERY_SUGGEST.value
                            )]
                        last_tag_type = delta_content_type

        yield from self._finalize_query_suggest_result(full_response, message_id)

    def _finalize_query_suggest_result(self, full_response: str, message_id: str) -> Generator[List[MessageChunk], None, None]:
        logger.debug("QuerySuggestAgent: 处理最终查询建议结果")
        try:
            # 解析查询建议列表
            suggest_items = self._convert_xlm_to_json(full_response)
            logger.info(f"QuerySuggestAgent: 成功生成 {len(suggest_items)} 条查询建议")
            # 生成查询建议消息
            yield [MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content=json.dumps(suggest_items),
                message_id=message_id,
                show_content='',
                message_type=MessageType.QUERY_SUGGEST.value
            )]
        except Exception as e:
            logger.error(f"QuerySuggestAgent: 处理最终查询建议结果失败，错误信息: {str(e)}")
            logger.error(traceback.format_exc())
            yield [MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content="",
                message_id=message_id,
                show_content="查询建议生成失败",
                message_type=MessageType.QUERY_SUGGEST.value
            )]
    def _convert_xlm_to_json(self, xml_str: str) -> List[str]:
        # 使用正则表达式提取 <suggest_item> 标签中的内容
        pattern = r'<suggest_item>(.*?)</suggest_item>'
        suggest_items = re.findall(pattern, xml_str, re.DOTALL)
        logger.debug(f"QuerySuggestAgent: 原始XML字符串: {xml_str}")
        logger.debug(f"QuerySuggestAgent: 提取的建议列表: {suggest_items}")
        suggests = []
        for suggest_item in suggest_items:
            suggests.append({
                "suggest": suggest_item.strip()
            })
        logger.debug(f"QuerySuggestAgent: 成功提取 {len(suggests)} 条查询建议")
        return suggests

        
        