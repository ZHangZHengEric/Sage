from typing import List, Dict, Any, Optional
from agents.agent.agent_base import AgentBase
from agents.utils.logger import logger
import json
import uuid
import datetime

class ObservationAgent(AgentBase):
    """Agent responsible for analyzing task progress and completion status."""
    
    def run_stream(self, messages: List[Dict[str, Any]],
            tool_manager: Optional[Any] = None,
            context: Optional[Dict[str, Any]] = None,
            session_id: str = None ) :
        """
        Stream Analyze task execution and determine completion status.

        Args:
            messages: Conversation history including execution results
            context: Additional execution context
            session_id: Optional session identifier
        Yields:
            Streamed messages with observation analysis
        """
        logger.info(f"ObservationAgent.stream_run: Starting observation analysis with {len(messages)} messages")

        # Extract relevant information from messages
        task_description = self._extract_task_description_to_str(messages)
        logger.debug(f"ObservationAgent.stream_run: Extracted task description of length {len(task_description)}")
        execution_results = self._extract_execution_results_to_str(messages)
        logger.debug(f"ObservationAgent.stream_run: Extracted execution results of length {len(execution_results)}")

        # Generate analysis prompt
        prompt = """# 任务执行分析指南

## 当前任务
{task_description}

## 已完成动作
{execution_results}

## 分析要求
1. 评估当前执行是否满足任务要求
2. 判断是否需要用户提供更多信息，尽可能减少用户输入，不要打扰用户，按照你对事情的完整理解，尽可能全面的完成事情
   - 如果需要，生成具体询问用户的语句
   - 如果经过多次尝试，大于10次，仍然无法完成任务，建议用户提供更多信息或者告知用户无法完成任务。
3. 确定任务是否已完成，后续不需要做其他的尝试。
4. 提供后续建议(如有)
5. 评估任务整体完成百分比，范围0-100,

## 特殊规则
1. 上一步完成了如果数据搜索，后续建议要包含，对搜索结果进行进一步的理解和处理，并且不能认为是任务完成。
2. analysis中不要带有工具的真实名称
3. 只输出以下格式的XLM，不要输出其他内容,不要输出```

## 输出格式
```
<needs_more_input>
boolea类型，true表示需要用户提供更多信息，false表示不需要用户提供更多信息
</needs_more_input>
<finish_percent>
任务完成百分比，范围0-100，100表示任务彻底完成，与is_completed不冲突。
</finish_percent>
<is_completed>
boolean类型,true表示任务已经执行完毕，不需要再做其他的尝试，false表示任务未完成，还需要做尝试。
</is_completed>
<analysis>
详细分析，一段话不要有换行
</analysis>
<suggestions>
["建议1", "建议2"]
</suggestions>
<user_query>
当needs_more_input为true时需要询问用户的具体问题，否则为空字符串
</user_query>
```"""
        logger.debug("ObservationAgent.stream_run: Generated analysis prompt")
        # print(prompt)
        # Call LLM and parse response
        all_content = ""
        message_id = str(uuid.uuid4())
        last_tag_type = None
        
        if len(self.system_prefix)==0:
            self.system_prefix = """你是一个智能AI助手，你的任务是分析任务的执行情况，并提供后续建议。"""
        current_time = context.get('current_time',datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        file_workspace = context.get('file_workspace','无')
        system_message = {
                'role':'system',
                'content': self.system_prefix+'''
你的当前工作目录是：{file_workspace}
当前时间是：{current_time}
你当前数据库_id或者知识库_id：{session_id}
'''.format(session_id=session_id,current_time=current_time,file_workspace=file_workspace)
        }
        unknown_content = ''
        for chunk in self.model.chat.completions.create(
            messages=[system_message]+[{"role": "user", "content": prompt.format(task_description=task_description, execution_results=execution_results)}],
            stream=True,
            **self.model_config
        ):
            if chunk.choices[0].delta.content is not None:
                delta_content = chunk.choices[0].delta.content
                for delta_content_char in delta_content:
                    delta_content_all = unknown_content+ delta_content_char
                # 判断delta_content的类型
                    tag_type = self._judge_delta_content_type(delta_content_all,all_content,tag_type=['needs_more_input','finish_percent','is_completed','analysis','suggestions','user_query'])
                    print(f'delta_content: {delta_content}, tag_type: {tag_type}')
                    all_content += delta_content_char
                    if tag_type == 'unknown':
                        unknown_content = delta_content_all
                        continue
                    else:
                        unknown_content = ''
                        if tag_type in ['analysis']:
                            if tag_type != last_tag_type:
                                yield [{
                                    'role': 'assistant',
                                    'content': '',
                                    'type': 'observation_result',
                                'message_id': message_id,
                                'show_content': '\n\n'
                                }]
                            yield [{
                                'role': 'assistant',
                                'content': '',
                                'type': 'observation_result',
                                'message_id': message_id,
                                'show_content': delta_content_all
                            }]
                        last_tag_type = tag_type

        response_json = self.convert_xlm_to_json(all_content)
        result = [{
            'role': 'assistant',
            'content': 'Observation: '+json.dumps(response_json,ensure_ascii=False),
            'type': 'observation_result',
            'message_id': message_id,
            'show_content': '\n'
        }]
        yield result

    def convert_xlm_to_json(self,xlm_content):
        """xlm_content 示例：
        <needs_more_input>
        boolea类型，true表示需要用户提供更多信息，false表示不需要用户提供更多信息
        </needs_more_input>
        <finish_percent>
        任务完成百分比，范围0-100，100表示任务完成
        </finish_percent>
        <is_completed>
        boolean类型,true表示任务已完成，false表示任务未完成
        </is_completed>
        <analysis>
        详细分析，一段话不要有换行
        </analysis>
        <suggestions>
        ["建议1", "建议2"]
        </suggestions>
        <user_query>
        当needs_more_input为true时需要询问用户的具体问题，否则为空字符串
        </user_query>

        将xlm_content 转换为json格式
        {
          "needs_more_input": <boolean>,
          "finish_percent": <int>,
          "is_completed": <boolean>,
          "analysis": "<详细分析>",
          "suggestions": ["建议1", "建议2"],
          "user_query": "<当needs_more_input为true时需要询问用户的具体问题>"
        }
        """
        # 提取needs_more_input,并转换为boolean类型
        needs_more_input = xlm_content.split('<needs_more_input>')[1].split('</needs_more_input>')[0].strip()
        if needs_more_input.lower() == 'true':
            needs_more_input = True
        else:
            needs_more_input = False
        # 提取finish_percent,并转换为int类型
        finish_percent = xlm_content.split('<finish_percent>')[1].split('</finish_percent>')[0].strip()
        finish_percent = int(finish_percent)
        # 提取is_completed,并转换为boolean类型
        is_completed = xlm_content.split('<is_completed>')[1].split('</is_completed>')[0].strip()
        if is_completed.lower() == 'true':
            is_completed = True
        else:
            is_completed = False
        # 提取analysis
        analysis = xlm_content.split('<analysis>')[1].split('</analysis>')[0].strip()
        # 提取suggestions,并转换为list类型
        suggestions = xlm_content.split('<suggestions>')[1].split('</suggestions>')[0].strip()
        try:
            suggestions = eval(suggestions)
        except:
            try:
                suggestions = json.loads(suggestions)
            except:
                suggestions = [suggestions]
        # 提取user_query
        user_query = xlm_content.split('<user_query>')[1].split('</user_query>')[0].strip()
        # 构建json
        response_json = {
            "needs_more_input": needs_more_input,
            "finish_percent": finish_percent,
            "is_completed": is_completed,
            "analysis": analysis,   
            "suggestions": suggestions,
            "user_query": user_query   
        }
        logger.info(f"ObservationAgent.convert_xlm_to_json response_json: {response_json}")
        return response_json
    
    def _extract_task_description_to_str(self, messages):
        """Extract completed actions from messages."""
        logger.debug(f"ObservationAgent._extract_task_description: Processing {len(messages)} messages")
        task_description_messages = self._extract_task_description_messages(messages)
        result = self.convert_messages_to_str(task_description_messages)
        logger.debug(f"ObservationAgent._extract_task_description: Generated task description of length {len(result)}")
        return result
        

    def _extract_execution_results_to_str(self, messages):
        """Extract completed actions from messages."""
        logger.debug(f"ObservationAgent._extract_execution_results: Processing {len(messages)} messages")
        completed_actions_messages = self._extract_completed_actions_messages(messages)
        result = self.convert_messages_to_str(completed_actions_messages)
        logger.debug(f"ObservationAgent._extract_execution_results: Generated execution results of length {len(result)}")
        return result
