from tkinter import Y
from typing import List, Dict, Any, Optional
import json
import datetime

from click.core import F
from agents.agent.agent_base import AgentBase
from agents.tool.tool_manager import ToolManager
from agents.tool.tool_base import AgentToolSpec
from agents.utils.logger import logger
import traceback
import os
from copy import deepcopy
import uuid
class ExecutorAgent(AgentBase):
    """Agent responsible for executing subtasks using tools or LLM directly."""
    agent_description = "ExecutorAgent: Executes subtasks using tools or LLM directly."

    def run_stream(self, messages: List[Dict[str, Any]], 
                   tool_manager: Optional[ToolManager] = None,
                   context: Optional[Dict[str, Any]] = None,
                   session_id: str = None):
        """
        Stream execute subtasks using tool calling or direct LLM generation.
        
        Args:
            messages: Conversation history containing subtasks
            tool_manager: Tool manager for executing tool-based subtasks
            context: Additional execution context
            
        Returns:
            List of message dicts containing execution results
        """
        logger.info(f"ExecutorAgent.run: Starting execution with session_id: {session_id}")
        if not messages:
            logger.warning("ExecutorAgent.run: No messages provided, returning empty list")
            return []
        task_description_messages = self._extract_task_description_messages(messages)    
        completed_actions_messages = self._extract_completed_actions_messages(messages)
        last_subtask_message = self._get_last_sub_task(messages)
        messages_input = deepcopy(messages)
        
        
        # 带有星期几的当前时间字符串
        current_time = context.get('current_time',datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        file_workspace = context.get('file_workspace','无')
        if len(self.system_prefix)==0:
            self.system_prefix = '''你是个任务执行助手，你需要根据任务描述，执行任务。'''
        system_message = {
                'role':'system',
                'content': self.system_prefix+'''
你的当前工作目录是：{file_workspace}
当前时间是：{current_time}
你当前数据库_id或者知识库_id：{session_id}
'''.format(session_id=session_id,current_time=current_time,file_workspace=file_workspace)
        }
        logger.info(f"ExecutorAgent.run: system_message: {system_message}")
        messages_input = [system_message]+messages_input
        request_do_subtask_prompt = '''Do the following subtask:{next_subtask_description}.
the expected output is:{next_expected_output}

注意以下的任务执行规则：
1. 如果不需要使用工具，直接返回中文内容。你的文字输出都要是markdown格式。
2. 如果是要生成计划、方案、内容创作，代码等大篇幅文字，请使用file_write函数工具将内容分多次保存到文件中，文件内容是函数的参数，格式使用markdown。
3. 如果需要编写代码，请使用file_write函数工具，代码内容是函数的参数。
4. 如果是输出报告或者总结，请使用file_write函数工具，报告内容是函数的参数，格式使用markdown。
5. 只能在工作目录下读写文件。如果用户没有提供文件路径，你应该在这个目录下创建一个新文件。
6. 调用工具时，不要在其他的输出文字,你一次只能执行一个任务。
7. 输出的文字中不要暴露你的工作目录，id信息以及你的工具名称。
8. 如果使用file_write创建文件，一定要在工作目录下创建文件，要求文件路径是绝对路径。
'''
        
        # 默认不提供任何建议工具
        suggested_tools = []
        
        try:
            # Parse tool response content
            try:
                logger.debug("ExecutorAgent.run: Parsing last subtask message")
                last_subtask_message_content = last_subtask_message['content']
                if last_subtask_message_content.startswith('Planning: '):
                    last_subtask_message_content = last_subtask_message_content[len('Planning: '):]
                next_subtask_dict = json.loads(last_subtask_message_content.strip('```json\n').strip('```'))
                next_subtask_description = next_subtask_dict['next_step']['description']
                next_expected_output = next_subtask_dict['next_step']['expected_output']
                suggested_tools = next_subtask_dict['next_step'].get('required_tools', [])
                logger.info(f"ExecutorAgent.run: Parsed subtask with description: {next_subtask_description}")
                logger.debug(f"ExecutorAgent.run: Required tools: {suggested_tools}")
                request_do_subtask_message = {
                    'role': 'assistant',
                    "content": request_do_subtask_prompt.format(next_subtask_description=next_subtask_description,next_expected_output=next_expected_output),
                    "type": "do_subtask",
                    "message_id": str(uuid.uuid4()),
                    "show_content":""
                }
                # print('request_do_subtask_message:',request_do_subtask_message)
                messages_input.append(request_do_subtask_message)
                output_messages = [request_do_subtask_message]
                yield output_messages
            except json.JSONDecodeError:
                # Handle parsing error
                # Fallback to using the original content if JSON parsing fails
                logger.error("ExecutorAgent.run: Failed to parse subtask message as JSON")
                print('next subtask dict 解析失败')
                output_messages = []
                raise json.JSONDecodeError("Failed to parse subtask message as JSON", doc=last_subtask_message_content, pos=0)
                        
            # Call LLM with the updated messages
            
            clean_message_input = []
            for msg in messages_input:
                if 'tool_calls' in msg and msg['tool_calls'] is not None:
                    clean_message_input.append({
                        'role': msg['role'],
                        'tool_calls': msg['tool_calls']
                    })
                elif 'content' in msg:
                    if 'tool_call_id' in msg:
                        clean_message_input.append({
                            'role': msg['role'],
                            'content': msg['content'],
                            'tool_call_id': msg['tool_call_id']
                        })
                    else:
                        clean_message_input.append({
                            'role': msg['role'],
                            'content': msg['content']
                        })
            
            logger.debug(f"ExecutorAgent.run: Prepared {len(clean_message_input)} messages for LLM")
            print('执行任务的输入messages',json.dumps(clean_message_input,ensure_ascii=False,indent=2))
            
            tools_json = tool_manager.get_openai_tools()
            tools_suggest_json = [ tool for tool in tools_json if tool['function']['name'] in suggested_tools]
            if len(tools_suggest_json) >0 :
                tools_json = tools_suggest_json

            logger.info(f"ExecutorAgent.run: Calling LLM with {len(tools_json)} suggested tools")
            tools_json_name = [ tool['function']['name'] for tool in tools_json]
            logger.debug(f"ExecutorAgent.run: tools_json: {tools_json_name}")
            response = self.model.chat.completions.create(
                tools = tools_json if len(tools_json) > 0 else None,
                messages=clean_message_input,
                **self.model_config,
                stream=True
            )
            # 对流式的返回的内容，进行收集，如果一旦有工具调用，就收集所有的工具调用信息，不在收集文字信息。如果没有工具调用，就流式返回文字信息。
            tool_calls = {}   # 用于收集工具调用信息
            unused_tool_content_message_id = str(uuid.uuid4())
            last_tool_call_id = None
            for chunk in response:
                if chunk.choices[0].delta.tool_calls:
                    tool_calls_delta = chunk.choices[0].delta.tool_calls
                    for tool_call in chunk.choices[0].delta.tool_calls:
                        if tool_call.id is not None and len(tool_call.id)>0:
                            last_tool_call_id = tool_call.id                            
                        if last_tool_call_id not in tool_calls:
                            logger.debug(f"ExecutorAgent.run: New tool call detected: {last_tool_call_id}，tool call name: {tool_call.function.name}")
                            tool_calls[last_tool_call_id] = {
                                'id':last_tool_call_id,
                                'type': tool_call.type,
                                'function': {
                                    'name': tool_call.function.name,
                                    'arguments': tool_call.function.arguments
                                }
                            }
                        else:
                            if tool_call.function.name:
                                tool_calls[last_tool_call_id]['function']['name'] = tool_call.function.name
                            if tool_call.function.arguments:
                                tool_calls[last_tool_call_id]['function']['arguments'] += tool_call.function.arguments
                elif chunk.choices[0].delta.content:
                    if len(tool_calls) > 0:
                        # 有工具调用，不再收集文字信息
                        logger.debug(f"ExecutorAgent.run: LLM response includes {len(tool_calls)} tool calls and content, stop collecting text content")
                        break
                    output_messages=[{
                        'role': 'assistant',
                        'content': chunk.choices[0].delta.content,
                        "type": "do_subtask_result",
                        "message_id": unused_tool_content_message_id,
                        "show_content":chunk.choices[0].delta.content
                    }]
                    yield output_messages
            
            # 判断是否有工具调用
            if len(tool_calls) > 0:
                logger.info(f"ExecutorAgent.run: LLM response includes {len(tool_calls)} tool calls")
                logger.info(f"ExecutorAgent.run: tool calls {tool_calls}")
                # 处理所有工具调用
                for tool_call_id, tool_call in tool_calls.items():
                    logger.info(f"ExecutorAgent.run: Executing tool {tool_call['function']['name']}")
                    
                    # 检查工具是否是agent_tool
                    tool = tool_manager.get_tool(tool_call['function']['name'])
                    if tool is None:
                        logger.error(f"ExecutorAgent.run: Tool {tool_call['function']['name']} not found")
                        return []
                    if isinstance(tool, AgentToolSpec):
                        output_messages = [{
                            "role":"assistant",
                            "content":"该任务交接给了{tool.name}，进行执行",
                            "show_content":"该任务交接给了{tool.name}，进行执行",
                            "message_id":str(uuid.uuid4()),
                            "type":"tool_call",
                        }]
                        yield output_messages
                    else:
                        # 发送工具调用消息
                        output_messages = [{
                            'role': 'assistant',
                            'tool_calls': [{'id':tool_call['id'],'type':tool_call['type'],'function':{'name':tool_call['function']['name'],'arguments':tool_call['function']['arguments']}}],
                            "type": "tool_call",
                            "message_id": str(uuid.uuid4()),
                            "show_content":"调用工具："+tool_call['function']['name']+'\n\n'
                        }]
                        yield output_messages
                    
                    # 解析并执行工具调用
                    arguments = json.loads(tool_call['function']['arguments'])
                    logger.info(f"ExecutorAgent.run: Executing tool {tool_call['function']['name']}")
                    tool_response = tool_manager.run_tool(tool_call['function']['name'],messages=messages_input ,session_id=session_id, **arguments)
                    
                    # 处理工具响应
                    logger.debug(f"ExecutorAgent.run: Received tool response, processing")
                    logger.info(f"ExecutorAgent.run: tool response {tool_response}")
                    processed_response = self.process_tool_response(tool_response,tool_call_id)
                    # 逐个返回工具调用的结果
                    yield processed_response
                
            else:
                # 返回换行消息
                output_messages=[{
                    'role': 'assistant',
                    'content': '',
                    "type": "do_subtask_result",
                    "message_id": unused_tool_content_message_id,
                    "show_content":'\n'
                }]
                yield output_messages
        except Exception as e:
            logger.error(f"ExecutorAgent.run: Exception during execution: {str(e)}")
            logger.error(traceback.format_exc())
            print(traceback.format_exc())
            return []

    def process_tool_response(self, tool_response: str,tool_call_id: str) -> Dict[str, Any]:
        """
        Process tool execution response.
        
        Args:
            tool_response: Tool execution response
            
        Returns:
            Processed result message
        """
        logger.debug(f"ExecutorAgent.process_tool_response: Processing tool response for tool_call_id {tool_call_id}")
        try:
            tool_response_dict = json.loads(tool_response)
            if "content" in tool_response_dict:
                result = [{
                    'role': 'tool',
                    'content': tool_response,
                    'tool_call_id': tool_call_id,
                    "message_id": str(uuid.uuid4()),
                    "type": "tool_call_result",
                    "show_content":'\n```json\n'+json.dumps(tool_response_dict['content'],ensure_ascii=False,indent=2)+'\n```\n'
                }]
            elif 'messages' in tool_response_dict:
                result = tool_response_dict['messages']
            logger.debug("ExecutorAgent.process_tool_response: Processed tool response successfully")
            return result
        except json.JSONDecodeError:
            logger.warning("ExecutorAgent.process_tool_response: JSON decode error when processing tool response")
            return {
                'role': 'tool',
                'content': '\n'+tool_response+'\n',
                'tool_call_id': tool_call_id,
                "message_id": str(uuid.uuid4()),
                "type": "tool_call_result",
                "show_content": "工具调用失败\n\n"
            }

    def _get_last_sub_task(self,messages):
        logger.debug(f"ExecutorAgent._get_last_sub_task: Finding last subtask from {len(messages)} messages")
        for i in range(len(messages)-1,-1,-1):
            if messages[i]['role'] == 'assistant' and messages[i].get('type',None) == 'planning_result':
                logger.debug(f"ExecutorAgent._get_last_sub_task: Found last subtask at index {i}")
                return messages[i]
        logger.warning("ExecutorAgent._get_last_sub_task: No planning_result message found")
        return None