from math import log
from tkinter import Y
from typing import List, Dict, Any, Optional
import json
import datetime

from click.core import F
from agents.agent.agent_base import AgentBase
from agents.tool.tool_manager import ToolManager
from agents.utils.logger import logger
import traceback
import os
from copy import deepcopy
import uuid
class DirectExecutorAgent(AgentBase):
    """Agent responsible for executing subtasks using tools or LLM directly."""
    agent_description = """DirectExecutorAgent: Executes subtasks using tools or LLM directly.
This agent does not use ReAct or other reasoning strategies.
It executes subtasks directly based on the provided context and tools. That will be faster for tasks that require no reasoning or early processing.
"""
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
        
        # 构造基础的依赖信息
        messages_input = deepcopy(messages)
        current_time = context.get('current_time',datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        file_workspace = context.get('file_workspace','无')
        
        # 构造基础的系统提示信息
        messages_input = [
            {
                'role':'system',
                'content': '''你是一个智能助手，你要根据用户的需求，为用户提供帮助，回答用户的问题或者满足用户的需求。
你的当前工作目录是：{file_workspace}
当前时间是：{current_time}
你当前数据库_id或者知识库_id：{session_id}

注意以下的执行规则：
1. 如果不需要使用工具，直接返回中文内容。
2. 如果是要生成计划、方案、内容创作等大篇幅文字，请使用file_write函数工具将内容保存到文件中，文件内容是函数的参数，格式使用markdown。
3. 如果需要编写代码，请使用file_write函数工具，代码内容是函数的参数。
4. 如果是输出报告或者总结，请使用file_write函数工具，报告内容是函数的参数，格式使用markdown。
5. 只能在工作目录下读写文件。如果用户没有提供文件路径，你应该在工作目录下创建一个新文件。
6. 当认为任务已经完成时，不在输出任何内容，直接返回空字符串。
7. 先执行tool_call，再执行普通的LLM输出。
8. 最后要给用户输出你认为最完整置信度最高的回答，重点是为用户提供帮助，回答用户的问题或者满足用户的需求。而不是遇到问题，拒绝完成任务。
'''.format(session_id=session_id,current_time=current_time,file_workspace=file_workspace),
                "type": "system",
                "message_id": str(uuid.uuid4())}
        ]+messages_input
        
        # 默认不提供任何建议工具
        suggested_tools = []
        try:
            # Parse tool response content
            suggested_tools = self.get_suggested_tools(messages_input, tool_manager, context,session_id=session_id)
            # Call LLM with the updated messages
            suggested_tools.append('complete_task')

            tools_json = tool_manager.get_openai_tools()
            tools_suggest_json = [ tool for tool in tools_json if tool['function']['name'] in suggested_tools]
            if len(tools_suggest_json) >0 :
                tools_json = tools_suggest_json


            logger.info(f"ExecutorAgent.run: Calling LLM with {len(tools_json)} suggested tools")
            tools_json_name = [ tool['function']['name'] for tool in tools_json]
            logger.debug(f"ExecutorAgent.run: tools_json: {tools_json_name}")
            
            # 开始循环请求LLM，直到LLM 不产生心的assistant 消息为止
            all_new_response_chunks = []
            loop_count = 0
            while True:
                loop_count += 1
                logger.info(f"ExecutorAgent.run: Loop count: {loop_count}")
                if loop_count > 10:
                    logger.warning(f"ExecutorAgent.run: Loop count exceeds 10, breaking loop")
                    break
                # 将 all_new_response_chunks 进行合并，并进行clean 获得新的输入
                messages_input = self._merge_messages(messages_input, all_new_response_chunks)
                all_new_response_chunks = []
                clean_message_input = self.clean_messages(messages_input)
                
                logger.info(f"ExecutorAgent.run: Prepared {len(clean_message_input)} messages for LLM")
                # print('执行任务的输入messages',json.dumps(clean_message_input,ensure_ascii=False,indent=2))

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
                        for tool_call in chunk.choices[0].delta.tool_calls:
                            if tool_call.id is not None:
                                last_tool_call_id = tool_call.id                            
                            if last_tool_call_id not in tool_calls:
                                logger.info(f"ExecutorAgent.run: New tool call detected: {last_tool_call_id},tool name: {tool_call.function.name} ")
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
                                    logger.info(f"ExecutorAgent.run: Updating tool call: {last_tool_call_id},tool name: {tool_call.function.name} ")
                                    tool_calls[last_tool_call_id]['function']['name'] = tool_call.function.name
                                if tool_call.function.arguments:
                                    tool_calls[last_tool_call_id]['function']['arguments'] += tool_call.function.arguments
                    elif chunk.choices[0].delta.content:
                        if len(tool_calls) > 0:
                            # 有工具调用，不再收集文字信息
                            logger.info(f"ExecutorAgent.run: LLM response includes {len(tool_calls)} tool calls and content, stop collecting text content")
                            break
                        if len(chunk.choices[0].delta.content)>0:
                            output_messages=[{
                                'role': 'assistant',
                                'content': chunk.choices[0].delta.content,
                                "type": "do_subtask_result",
                                "message_id": unused_tool_content_message_id,
                                "show_content":chunk.choices[0].delta.content
                            }]
                            all_new_response_chunks.extend(output_messages)
                            yield output_messages
                
                
                # 判断是否有工具调用
                call_task_complete = False
                if len(tool_calls) > 0:
                    logger.info(f"ExecutorAgent.run: LLM response includes {len(tool_calls)} tool calls")
                    logger.info(f"ExecutorAgent.run: tool calls {tool_calls}")
                    # 处理所有工具调用
                    for tool_call_id, tool_call in tool_calls.items():
                        logger.info(f"ExecutorAgent.run: Executing tool {tool_call['function']['name']}")
                        logger.info(f"ExecutorAgent.run: parameters {tool_call['function']['arguments']}")
                        # 发送工具调用消息
                        if tool_call['function']['name'] == 'complete_task':
                            logger.info(f"ExecutorAgent.run: complete_task, stop execution")
                            call_task_complete = True
                            break
                        output_messages = [{
                            'role': 'assistant',
                            'tool_calls': [{'id':tool_call['id'],'type':tool_call['type'],'function':{'name':tool_call['function']['name'],'arguments':tool_call['function']['arguments']}}],
                            "type": "tool_call",
                            "message_id": str(uuid.uuid4()),
                            "show_content":"调用工具："+tool_call['function']['name']+'\n\n'
                        }]
                        all_new_response_chunks.extend(output_messages)
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
                        all_new_response_chunks.append(processed_response)
                        yield [processed_response]
                    
                else:
                    # 返回换行消息
                    if len(all_new_response_chunks)>0:
                        output_messages=[{
                            'role': 'assistant',
                            'content': '',
                            "type": "do_subtask_result",
                            "message_id": unused_tool_content_message_id,
                            "show_content":'\n'
                        }]
                        all_new_response_chunks.extend(output_messages)
                        yield output_messages
                if call_task_complete:
                    logger.info(f"ExecutorAgent.run: complete_task, stop execution")
                    break
                if len(all_new_response_chunks)<10:
                    print('all_new_response_chunks',json.dumps(all_new_response_chunks,ensure_ascii=False,indent=2))
                if len(all_new_response_chunks) == 0:
                    logger.info(f"ExecutorAgent.run: No more response chunks, stopping execution")
                    break
                # 如果all_new_response_chunks 内部的item 没有tool_calls 且content 字段，没有任何内容，就停止执行
                if all([item.get('tool_calls',None) is None and (item.get('content',None) is None or item.get('content',None)=='')  for item in all_new_response_chunks]):
                    logger.info(f"ExecutorAgent.run: No more response chunks, stopping execution")
                    break
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
    def get_suggested_tools(self, messages: List[Dict[str, Any]],
                tool_manager: Optional[ToolManager] = None,
                context: Optional[Dict[str, Any]] = None,
                session_id: str = None) -> List[str]:
        """
        基于用户的输入，以及历史的对话，获取解决用户请求用到的所有可能的工具。
        Args:
            messages: 对话历史
            tool_manager: 工具管理器
            context: 额外的上下文信息
            session_id: 会话id
        Returns:
            所有可能的工具列表
        """
        logger.info(f"ExecutorAgent.get_suggested_tools: Starting tool suggestion with session_id: {session_id}")
        if not messages:
            logger.warning("ExecutorAgent.get_suggested_tools: No messages provided, returning empty list")
            return []
        available_tools = tool_manager.list_tools_simplified()  
        available_tools_str = json.dumps(available_tools,ensure_ascii=False,indent=2) if available_tools else '无可用工具'
        
        prompt = '''你是一个智能助手，你要根据用户的需求，为用户提供帮助，回答用户的问题或者满足用户的需求。
你当前数据库_id或者知识库_id：{session_id}
你要根据历史的对话以及用户的请求，获取解决用户请求用到的所有可能的工具。

## 可用工具
{available_tools_str}

## 用户的对话历史以及新的请求
{messages}

输出格式：
```json
[
    "工具名称1",
    "工具名称2",
    ...
]
```
注意：
1. 工具名称必须是可用工具中的名称。
2. 返回所有可能用到的工具名称，对于不可能用到的工具，不要返回。
3. 可能的工具最多返回7个。
'''     
        # 移除掉messages 中的type 和show content等字段，形成一个新的messages，但是不要修改原来的对象
        new_messages = [
            {
                'role':msg.get('role',None),
                'content':msg.get('content',None),
                'tool_call_id':msg.get('tool_call_id',None),
                'tool_calls':msg.get('tool_calls',None)
            } for msg in messages
        ]
        # 去掉 new_messages中的为none 的key
        for msg in new_messages:
            for key in list(msg.keys()):
                if msg[key] is None:
                    del msg[key]
       
        messages_input = [
            {
                'role':'user',
                'content': prompt.format(session_id=session_id,available_tools_str=available_tools_str,messages=json.dumps(new_messages,ensure_ascii=False,indent=2))
            }
        ]
        logger.debug(f"ExecutorAgent.get_suggested_tools: Calling LLM with {len(messages_input)} messages")
        response = self.model.chat.completions.create(
            messages=messages_input,
            **self.model_config
        )
        logger.debug(f"ExecutorAgent.get_suggested_tools: Received response from LLM")
        try:
            result_clean = self._extract_json_from_markdown(response.choices[0].message.content)
            suggested_tools = json.loads(result_clean)
            logger.info(f"ExecutorAgent.get_suggested_tools: Suggested tools: {suggested_tools}")
            return suggested_tools
        except json.JSONDecodeError:
            logger.warning("ExecutorAgent.get_suggested_tools: JSON decode error when processing tool response")
            return []