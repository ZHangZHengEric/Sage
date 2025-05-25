from tkinter import Y
from typing import List, Dict, Any, Optional
from agents.agent.agent_base import AgentBase
from agents.tool.tool_manager import ToolManager
from agents.utils.logger import logger
import uuid
import json
import datetime
class PlanningAgent(AgentBase):
    """Agent responsible for generating next steps based on current state."""
    

    def run_stream(self, messages: List[Dict[str, Any]], tool_manager: Optional[Any] = None, context: Optional[Dict[str, Any]] = None, session_id: str = None):
        """
        Stream Generate next steps plan based on conversation history and context.
        
        Args:
            messages: Conversation history including task analysis
            tool_manager: Tool manager instance providing available tools
            context: Additional execution context
            
        Returns:
            Generator yielding messages with planning results
        """
        logger.info(f"PlanningAgent.run: Starting planning with {len(messages)} messages")
        
        # Extract relevant information from messages
        task_description = self._extract_task_description(messages)
        logger.debug(f"PlanningAgent.run: Extracted task description length: {len(task_description)}")
        # print('task_description',task_description)
        completed_actions = self._extract_completed_actions(messages)
        logger.debug(f"PlanningAgent.run: Extracted completed actions length: {len(completed_actions)}")
        # print('completed_actions',completed_actions)
        
        # Get available tools
        available_tools = tool_manager.list_tools_simplified()  
        logger.debug(f"PlanningAgent.run: Available tools count: {len(available_tools)}")
        available_tools_str = json.dumps(available_tools,ensure_ascii=False,indent=2) if available_tools else '无可用工具'
        current_time = context.get('current_datatime_str', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        file_workspace = context.get('file_workspace', '无')
        logger.debug(f"PlanningAgent.run: Current time: {current_time}, File workspace: {file_workspace}")
        # Generate planning prompt
        if len(self.system_prefix)==0:
            self.system_prefix = """你是一个任务执行计划指定者，你需要根据当前任务和已完成的动作，生成下一个要执行的动作。"""
        system_message = {
                'role':'system',
                'content': self.system_prefix+'''
你的当前工作目录是：{file_workspace}
当前时间是：{current_time}
你当前数据库_id或者知识库_id：{session_id}
'''.format(session_id=session_id,current_time=current_time,file_workspace=file_workspace)
        }

        prompt = """# 任务规划指南

## 当前任务
{task_description}

## 已完成动作
{completed_actions}

## 可用工具
{available_tools_str}

## 规划规则
1. 将复杂任务分解为清晰的接下来要执行的第一个子任务
2. 确保子任务可执行且可衡量
3. 考虑子任务之间的依赖关系
4. 优先使用现有工具
5. 设定明确的成功标准
6. 只输出以下格式的XLM，不要输出其他内容,不要输出```, <tag>标志位必须在单独一行
7. description中不要包含工具的真实名称
8. required_tools至少包含5个可能需要的工具的名称，最多10个。

## 输出格式
```
<next_step_description>
子任务的清晰描述，一段话不要有换行
</next_step_description>
<required_tools>
["tool1_name","tool2_name"]
</required_tools>
<expected_output>
预期结果描述，一段话不要有换行
</expected_output>
<success_criteria>
如何验证完成，一段话不要有换行
</success_criteria>
```
"""
        
        logger.debug("PlanningAgent.run: Generated planning prompt")
        # print(prompt)
        # Call LLM for planning
        logger.info("PlanningAgent.run: Calling LLM for planning")
        chunk_count = 0
        all_content = ""
        message_id = str(uuid.uuid4())
        last_tag_type = None
        
        for chunk in self.model.chat.completions.create(
            messages=[system_message] +[{"role": "user", "content": prompt.format(task_description=task_description, completed_actions=completed_actions, available_tools_str=available_tools_str,current_time=current_time,session_id=session_id)}],
            stream=True,
            **self.model_config
        ):
            if chunk.choices[0].delta.content is not None:
                delta_content = chunk.choices[0].delta.content
                chunk_count += 1
                # 判断delta_content的类型
                tag_type = self._judge_delta_content_type(delta_content,all_content)
                # print(f'delta_content: {delta_content}, tag_type: {tag_type}')
                # 如果是tag 则不返回，因为show_content 是不包含tag的
                if tag_type in ['next_step_description','expected_output']:
                    if tag_type != last_tag_type:
                        yield [{
                            'role': 'assistant',
                            'content': '',
                            'type': 'planning_result',
                          'message_id': message_id,
                          'show_content': '\n\n'
                        }]
                    yield [{
                        'role': 'assistant',
                        'content': '',
                        'type': 'planning_result',
                        'message_id': message_id,
                        'show_content': delta_content
                    }]
                    last_tag_type = tag_type
                all_content += delta_content

        response_json = self.convert_xlm_to_json(all_content)
        result = [{
            'role': 'assistant',
            'content': 'Planning: '+json.dumps(response_json,ensure_ascii=False),
            'type': 'planning_result',
           'message_id': message_id,
           'show_content': ''
        }]
        logger.info("PlanningAgent.run: Planning completed")
        yield result

    def convert_xlm_to_json(self,xlm_content):
        """xlm_content 示例：
        <next_step_description>
        子任务的清晰描述
        </next_step_description>
        <required_tools>
        ["tool1_name","tool2_name"]
        </required_tools>
        <expected_output>
        预期结果描述
        </expected_output>
        <success_criteria>
        如何验证完成
        </success_criteria>

        将xlm_content 转换为json格式
        {
          "next_step": {
              "description": "子任务的清晰描述",
              "required_tools": ["tool1_name","tool2_name"],
              "expected_output": "预期结果描述",
              "success_criteria": "如何验证完成"
            }
        }
        """
        print('plan xml:',xlm_content)
        description = xlm_content.split('<next_step_description>')[1].split('</next_step_description>')[0].strip()
        required_tools = xlm_content.split('<required_tools>')[1].split('</required_tools>')[0].strip()
        expected_output = xlm_content.split('<expected_output>')[1].split('</expected_output>')[0].strip()
        success_criteria = xlm_content.split('<success_criteria>')[1].split('</success_criteria>')[0].strip()
        return {
            "next_step": {
                "description": description,
                "required_tools": required_tools,
                "expected_output": expected_output,
                "success_criteria": success_criteria
            }
        }
                    
            
    def _judge_delta_content_type(self, delta_content,all_content):
        """
        delta_content 是下列字符串的流式结果，可能是其中的一个或者多个字符：
        <next_step_description>
        子任务的清晰描述
        </next_step_description>
        <required_tools>
        所需工具列表
        </required_tools>
        <expected_output>
        预期结果描述
        </expected_output>
        <success_criteria>
        如何验证完成
        </success_criteria>

        判断delta_content的类型，是 next_step_description 还是 required_tools 还是 expected_output 还是 success_criteria 或者<tag>即xml中的标签
        规则：
        1. 当all_content+ delta_content 最后一个字符还处于xlm的标签的部分时，返回标签类型tag
        2. 当all_content+ delta_content 不在xlm的标签中时，返回前一个开始标签的类型
        3. tag一定是单独的一行
        
        return 标签的类型
        """
        # 定义标签类型
        tag_types = ["next_step_description", "required_tools", "expected_output", "success_criteria"]
        # 定义标签的开始和结束
        tag_starts = ["<" + tag + ">" for tag in tag_types]
        tag_ends = ["</" + tag + ">" for tag in tag_types]

        # 先判断当前的最后一行是否是xml的标签例如<next_step_description>、<required_tools>、<expected_output>、<success_criteria>的一部分，如果是，返回标签类型
        lines = (all_content+delta_content).split("\n")
        # print('lines[-1]' ,lines[-1])
        if lines[-1] in '```':
            return "tag"
        for  tag_start in tag_starts:
            if lines[-1] in tag_start and len(lines[-1])>0 :
                return "tag"
        for  tag_end in tag_ends:
            if lines[-1] in tag_end and len(lines[-1])>0 :
                return "tag"
        # 如果不是，返回前一个开始标签的类型
        for line in lines[::-1]:
            for tag_start in tag_starts:
                if tag_start in line :
                    return tag_types[tag_starts.index(tag_start)]

    def _extract_task_description(self, messages):
        """Extract original task description from messages."""
        logger.debug(f"PlanningAgent._extract_task_description: Processing {len(messages)} messages")
        task_description_messages = self._extract_task_description_messages(messages)
        result = self.convert_messages_to_str(task_description_messages)
        logger.debug(f"PlanningAgent._extract_task_description: Generated task description of length {len(result)}")
        return result

    def _extract_completed_actions(self, messages):
        """Extract completed actions from messages."""
        logger.debug(f"PlanningAgent._extract_completed_actions: Processing {len(messages)} messages")
        completed_actions_messages = self._extract_completed_actions_messages(messages)
        result = self.convert_messages_to_str(completed_actions_messages)
        logger.debug(f"PlanningAgent._extract_completed_actions: Generated completed actions of length {len(result)}")
        return result
