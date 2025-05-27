from typing import List, Dict, Any, Optional, Generator
import json
import uuid
import logging
import re
from ..agent_base import AgentBase
import datetime

logger = logging.getLogger(__name__)

class TaskDecomposeAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        
    
    def run_stream(self, messages: List[Dict[str, Any]], 
                 tool_manager: Optional[Any] = None,
                 context: Optional[Dict[str, Any]] = None,
                 session_id: str = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        流式版本的任务分解
        """
        logger.info(f"{self.__class__.__name__}.run_stream: Starting streaming task decomposition")
        
        # 提取任务描述
        task_description = self._extract_task_description_messages(messages)
        task_description_str = self.convert_messages_to_str(task_description)
        logger.debug(f"{self.__class__.__name__}.run_stream: Extracted task description of length {len(task_description)}")
        
        current_time = context.get('current_time',datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        file_workspace = context.get('file_workspace','无')
        if len(self.system_prefix)==0:
            self.system_prefix = """你是一个任务分解者，你需要根据用户需求，将复杂任务分解为清晰可执行的子任务。"""
        system_message = {
                'role':'system',
                'content': self.system_prefix+'''
你的当前工作目录是：{file_workspace}
当前时间是：{current_time}
你当前数据库_id或者知识库_id：{session_id}
'''.format(session_id=session_id,current_time=current_time,file_workspace=file_workspace)
        }


        # 生成任务分解提示,输出子任务的描述和是否必须完成的标志
        prompt = """# 任务分解指南

## 用户需求
{task_description}

## 分解要求
1. 将复杂需求分解为清晰可执行的子任务
2. 确保每个子任务都是原子性的
3. 考虑任务之间的依赖关系，输出的列表必须是有序的，按照优先级从高到低排序，优先级相同的任务按照依赖关系排序
4. 输出格式必须严格遵守以下要求
5. 如果有任务Thinking的过程，子任务要与Thinking的处理逻辑一致
6. 子任务数量不要超过10个，较简单的子任务可以合并为一个子任务

## 输出格式
```
<task_item>
子任务1描述
</task_item>
<task_item>
子任务2描述
</task_item>
```
"""
        
        logger.debug(f"{self.__class__.__name__}.run_stream: Generated streaming decomposition prompt")
        
        # 流式调用LLM
        logger.info(f"{self.__class__.__name__}.run_stream: Calling LLM with streaming enabled")
        full_response = ""
        message_id = str(uuid.uuid4())
        last_tag_type = 'tag'
        yield [{
            'role': 'assistant',
            'content': '',
            'type': 'task_decomposition',
            'message_id': message_id,
            'show_content': '接下来执行如下的安排：\n\n'
        }]
        new_input_messages = []
        new_input_messages.append(system_message)
        new_input_user_message = {
            'role':'user',
            'content': prompt.format(task_description=task_description_str)
        }
        new_input_messages.append(new_input_user_message)
        unknown_content = ''
        for chunk in self.model.chat.completions.create(
            messages=new_input_messages,
            stream=True,
            **self.model_config
        ):
            if chunk.choices[0].delta.content is not None:
                delta_content = chunk.choices[0].delta.content
                
                for delta_content_char in delta_content:
                    delta_content_all = unknown_content+ delta_content_char
                    # 判断delta_content的类型
                    tag_type = self._judge_delta_content_type(delta_content_all,full_response,tag_type=['task_item'])
                    # print(delta_content_all,tag_type)
                    full_response += delta_content_char
                    if tag_type == 'unknown':
                        unknown_content = delta_content_all
                        continue
                    else:
                        unknown_content = ''
                        # 如果是task_item标签内容则返回
                        if tag_type == 'task_item':
                            if last_tag_type != 'task_item':
                                yield [{
                                    'role': 'assistant',
                                    'content': '',
                                    'type': 'task_decomposition',
                                'message_id': message_id,
                                'show_content': '\n- '
                                }]
                            yield [{
                                'role': 'assistant',
                                'content': '',
                                'type': 'task_decomposition',
                                'message_id': message_id,
                                'show_content': delta_content_all
                            }]
                        last_tag_type = tag_type
        # 解析完整响应
        tasks = self._convert_xlm_to_json(full_response)
        
        # 返回最终结果
        yield [{
            'role': 'assistant',
            'content': '任务拆解规划：\n'+json.dumps({"tasks": tasks}, ensure_ascii=False),
            'type': 'task_decomposition',
            'message_id': message_id,
            'show_content': ''
        }]
        
        logger.info(f"{self.__class__.__name__}.run_stream: Streaming task decomposition completed")
    
    def _convert_xlm_to_json(self, content: str) -> List[Dict[str, Any]]:
        """
        将任务列表从XML格式转换为JSON格式
        """
        tasks = []
        # print(f"content:{content}" )
        task_items = re.findall(r'<task_item>(.*?)</task_item>', content, re.DOTALL)

        for item in task_items:
            task = {
                "description": item.strip(),
            }
            tasks.append(task)

        return tasks

    def _extract_tasks_from_response(self, content: str) -> List[Dict[str, Any]]:
        """
        从LLM响应中提取任务列表
        """
        try:
            # 尝试从markdown代码块中提取JSON
            json_str = self._extract_json_from_markdown(content)
            
            # 尝试解析为JSON
            tasks_data = json.loads(json_str)
            
            if isinstance(tasks_data, dict) and "tasks" in tasks_data:
                return tasks_data["tasks"]
            elif isinstance(tasks_data, list):
                return tasks_data
            else:
                logger.warning(f"{self.__class__.__name__}: Unexpected tasks format in response")
                return []
        except json.JSONDecodeError as e:
            logger.error(f"{self.__class__.__name__}: Failed to parse tasks from response: {str(e)}")
            return []