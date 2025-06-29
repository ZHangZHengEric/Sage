"""
PlanningAgent 重构版本

规划智能体，负责基于当前状态生成下一步执行计划。
改进了代码结构、错误处理、日志记录和可维护性。

作者: Eric ZZ
版本: 2.0 (重构版)
"""

import json
import uuid
import datetime
import traceback
import time
from typing import List, Dict, Any, Optional, Generator

from agents.agent.agent_base import AgentBase
from agents.tool.tool_manager import ToolManager
from agents.utils.logger import logger


class PlanningAgent(AgentBase):
    """
    规划智能体
    
    负责基于对话历史和当前状态生成下一步执行计划。
    支持流式输出，实时返回规划结果。
    """

    # 任务规划提示模板常量
    PLANNING_PROMPT_TEMPLATE = """# 任务规划指南

## 完整任务描述
{task_description}

## 任务管理器状态
{task_manager_status}

## 近期完成工作
{completed_actions}

## 可用工具
{available_tools_str}

## 规划规则
1. 根据我们的当前任务以及近期完成工作，为了达到逐步完成任务管理器的未完成子任务或者完整的任务，清晰描述接下来要执行的具体的任务名称。
2. 确保接下来的任务可执行且可衡量
3. 优先使用现有工具
4. 设定明确的成功标准
5. 只输出以下格式的XLM，不要输出其他内容,不要输出```, <tag>标志位必须在单独一行
6. description中不要包含工具的真实名称
7. required_tools至少包含5个可能需要的工具的名称，最多10个。

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

    # 系统提示模板常量
    SYSTEM_PREFIX_DEFAULT = """你是一个任务执行计划指定者，你需要根据当前任务和已完成的动作，生成下一个要执行的动作。"""

    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        """
        初始化规划智能体
        
        Args:
            model: 语言模型实例
            model_config: 模型配置参数
            system_prefix: 系统前缀提示
        """
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "PlanningAgent"
        self.agent_description = "规划智能体，专门负责基于当前状态生成下一步执行计划"
        logger.info("PlanningAgent 初始化完成")

    def run_stream(self, 
                   message_manager: Any,
                   task_manager: Optional[Any] = None,
                   tool_manager: Optional[Any] = None,
                   session_id: Optional[str] = None,
                   system_context: Optional[Dict[str, Any]] = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        流式执行规划任务
        
        Args:
            message_manager: 消息管理器（必需）
            task_manager: 任务管理器
            tool_manager: 工具管理器
            session_id: 会话ID
            system_context: 运行时系统上下文字典，用于自定义推理时的变化信息
            
        Yields:
            List[Dict[str, Any]]: 流式输出的规划消息块
        """
        if not message_manager:
            raise ValueError("PlanningAgent: message_manager 是必需参数")
        
        # 从MessageManager获取优化后的消息
        optimized_messages = message_manager.filter_messages_for_agent(self.__class__.__name__)
        logger.info(f"PlanningAgent: 开始流式规划任务，获取到 {len(optimized_messages)} 条优化消息")
        
        # 使用基类方法收集和记录流式输出，并将结果添加到MessageManager
        for chunk_batch in self._collect_and_log_stream_output(
            self._execute_planning_stream_internal(optimized_messages, tool_manager, session_id, system_context, task_manager)
        ):
            # Agent自己负责将生成的消息添加到MessageManager
            message_manager.add_messages(chunk_batch, agent_name="PlanningAgent")
            yield chunk_batch
    def _execute_planning_stream_internal(self, 
                                        messages: List[Dict[str, Any]], 
                                        tool_manager: Optional[Any],
                                        session_id: str,
                                        system_context: Optional[Dict[str, Any]],
                                        task_manager: Optional[Any] = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        内部规划流式执行方法
        
        Args:
            messages: 包含任务分析的对话历史记录
            tool_manager: 提供可用工具的工具管理器实例
            session_id: 会话ID
            system_context: 系统上下文
            
        Yields:
            List[Dict[str, Any]]: 流式输出的规划结果消息块
        """
        try:
            # 准备规划上下文
            planning_context = self._prepare_planning_context(
                messages=messages,
                tool_manager=tool_manager,
                session_id=session_id,
                system_context=system_context,
                task_manager=task_manager
            )
            
            # 生成规划提示
            prompt = self._generate_planning_prompt(planning_context)
            
            # 执行流式规划
            yield from self._execute_streaming_planning(planning_context)
            
        except Exception as e:
            logger.error(f"PlanningAgent: 规划过程中发生异常: {str(e)}")
            logger.error(f"异常详情: {traceback.format_exc()}")
            yield from self._handle_planning_error(e)

    def _prepare_planning_context(self, 
                                messages: List[Dict[str, Any]],
                                tool_manager: Optional[Any],
                                session_id: str,
                                system_context: Optional[Dict[str, Any]],
                                task_manager: Optional[Any] = None) -> Dict[str, Any]:
        """
        准备任务规划所需的上下文信息
        
        Args:
            messages: 对话消息列表
            tool_manager: 工具管理器
            session_id: 会话ID
            system_context: 系统上下文
            
        Returns:
            Dict[str, Any]: 包含规划所需信息的上下文字典
        """
        logger.debug("PlanningAgent: 准备任务规划上下文")
        
        # 提取任务描述
        task_description = self._extract_task_description(messages)
        logger.debug(f"PlanningAgent: 提取任务描述，长度: {len(task_description)}")
        
        # 提取已完成的操作
        completed_actions = self._extract_completed_actions(messages)
        logger.debug(f"PlanningAgent: 提取已完成操作，长度: {len(completed_actions)}")
        
        # 获取可用工具
        available_tools = tool_manager.list_tools_simplified() if tool_manager else []
        logger.debug(f"PlanningAgent: 可用工具数量: {len(available_tools)}")
        # 只取工具的名称
        available_tools_str = json.dumps([tool['name'] for tool in available_tools], ensure_ascii=False, indent=2) if available_tools else '无可用工具'
        
        # 获取任务管理器状态
        task_manager_status = task_manager.get_status_description() if task_manager else '无任务管理器'
        logger.debug(f"PlanningAgent: 任务管理器状态: {task_manager_status}")
        
        # 获取上下文信息
        current_time = system_context.get('current_datatime_str', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')) if system_context else datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        file_workspace = system_context.get('file_workspace', '无') if system_context else '无'
        
        logger.debug(f"PlanningAgent: 当前时间: {current_time}, 文件工作空间: {file_workspace}")
        
        planning_context = {
            'task_description': task_description,
            'completed_actions': completed_actions,
            'task_manager_status': task_manager_status,
            'available_tools_str': available_tools_str,
            'current_time': current_time,
            'file_workspace': file_workspace,
            'session_id': session_id,
            'system_context': system_context
        }
        
        logger.info("PlanningAgent: 任务规划上下文准备完成")
        return planning_context

    def _generate_planning_prompt(self, context: Dict[str, Any]) -> str:
        """
        生成任务规划提示
        
        Args:
            context: 规划上下文信息
            
        Returns:
            str: 格式化后的规划提示
        """
        logger.debug("PlanningAgent: 生成任务规划提示")
        
        prompt = self.PLANNING_PROMPT_TEMPLATE.format(
            task_description=context['task_description'],
            completed_actions=context['completed_actions'],
            available_tools_str=context['available_tools_str'],
            task_manager_status=context['task_manager_status']
        )
        
        logger.debug("PlanningAgent: 规划提示生成完成")
        return prompt

    def _execute_streaming_planning(self, 
                                  planning_context: Dict[str, Any]) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行流式任务规划
        
        Args:
            planning_context: 规划上下文
            
        Yields:
            List[Dict[str, Any]]: 流式输出的消息块
        """
        logger.info("PlanningAgent: 开始执行流式任务规划")
        
        # 准备系统消息
        system_message = self.prepare_unified_system_message(
            session_id=planning_context.get('session_id'),
            system_context=planning_context.get('system_context')
        )
        
        # 生成规划提示
        prompt = self._generate_planning_prompt(planning_context)
        
        # 准备消息
        messages = [system_message, {"role": "user", "content": prompt}]
        
        # 执行流式处理
        message_id = str(uuid.uuid4())
        chunk_count = 0
        start_time = time.time()
        all_content = ""
        unknown_content = ""
        last_tag_type = None
        
        # 收集所有chunks以便跟踪token使用
        chunks = []
        for chunk in self._call_llm_streaming(messages, session_id=planning_context.get('session_id'), step_name="planning"):
            chunks.append(chunk)
            if len(chunk.choices) == 0:
                continue
            if chunk.choices[0].delta.content:
                delta_content = chunk.choices[0].delta.content
                
                for delta_content_char in delta_content:
                    delta_content_all = unknown_content + delta_content_char
                    # 判断delta_content的类型
                    tag_type = self._judge_delta_content_type(delta_content_all, all_content, ['next_step_description','required_tools','expected_output','success_criteria'])
                    all_content += delta_content_char
                    chunk_count += 1
                    
                    if tag_type == 'unknown':
                        unknown_content = delta_content_all
                        continue
                    else:
                        unknown_content = ''
                        if tag_type in ['next_step_description','expected_output']:
                            if tag_type != last_tag_type:
                                yield self._create_message_chunk(
                                    content='',
                                    message_id=message_id,
                                    show_content='\n\n',
                                    message_type='planning_result'
                                )
                            
                            yield self._create_message_chunk(
                                content='',
                                message_id=message_id,
                                show_content=delta_content_all,
                                message_type='planning_result'
                            )
                        last_tag_type = tag_type
        
        # 跟踪token使用情况
        self._track_streaming_token_usage(chunks, "planning", start_time)
        
        logger.info(f"PlanningAgent: 流式规划完成，共生成 {chunk_count} 个文本块")
        
        # 调用finalize方法处理最终结果
        yield from self._finalize_planning_result(
            all_content=all_content, 
            message_id=message_id
        )

    def _finalize_planning_result(self, 
                                all_content: str, 
                                message_id: str) -> Generator[List[Dict[str, Any]], None, None]:
        """
        完成规划并返回最终结果
        
        Args:
            all_content: 完整的内容
            message_id: 消息ID
            
        Yields:
            List[Dict[str, Any]]: 最终规划结果消息块
        """
        logger.debug("PlanningAgent: 处理最终规划结果")
        
        try:
            response_json = self.convert_xlm_to_json(all_content)
            logger.info("PlanningAgent: 规划完成")
            
            result = [{
                'role': 'assistant',
                'content': 'Planning: ' + json.dumps(response_json, ensure_ascii=False),
                'type': 'planning_result',
                'message_id': message_id,
                'show_content': ''
            }]
            
            yield result
            
        except Exception as e:
            logger.error(f"PlanningAgent: 处理最终结果时发生错误: {str(e)}")
            yield from self._handle_planning_error(e)

    def _handle_planning_error(self, error: Exception) -> Generator[List[Dict[str, Any]], None, None]:
        """
        处理规划过程中的错误
        
        Args:
            error: 发生的异常
            
        Yields:
            List[Dict[str, Any]]: 错误消息块
        """
        yield from self._handle_error_generic(
            error=error,
            error_context="任务规划",
            message_type='planning_result'
        )

    def convert_xlm_to_json(self, xlm_content: str) -> Dict[str, Any]:
        """
        将XML格式内容转换为JSON格式
        
        Args:
            xlm_content: XML格式的内容字符串
            
        Returns:
            Dict[str, Any]: 转换后的JSON字典
            
        Example:
            输入XML格式：
            <next_step_description>子任务的清晰描述</next_step_description>
            <required_tools>["tool1_name","tool2_name"]</required_tools>
            <expected_output>预期结果描述</expected_output>
            <success_criteria>如何验证完成</success_criteria>
            
            输出JSON格式：
            {
                "next_step": {
                    "description": "子任务的清晰描述",
                    "required_tools": ["tool1_name","tool2_name"],
                    "expected_output": "预期结果描述",
                    "success_criteria": "如何验证完成"
                }
            }
        """
        logger.debug("PlanningAgent: 转换XML内容为JSON格式")
        logger.debug(f"PlanningAgent: XML内容: {xlm_content}")
        
        try:
            description = xlm_content.split('<next_step_description>')[1].split('</next_step_description>')[0].strip()
            required_tools = xlm_content.split('<required_tools>')[1].split('</required_tools>')[0].strip()
            expected_output = xlm_content.split('<expected_output>')[1].split('</expected_output>')[0].strip()
            success_criteria = xlm_content.split('<success_criteria>')[1].split('</success_criteria>')[0].strip()
            
            result = {
                "next_step": {
                    "description": description,
                    "required_tools": required_tools,
                    "expected_output": expected_output,
                    "success_criteria": success_criteria
                }
            }
            
            logger.debug(f"PlanningAgent: XML转JSON完成: {result}")
            return result
            
        except Exception as e:
            logger.error(f"PlanningAgent: XML转JSON失败: {str(e)}")
            raise

    def _extract_task_description(self, messages: List[Dict[str, Any]]) -> str:
        """
        从消息中提取原始任务描述
        
        Args:
            messages: 消息列表
            
        Returns:
            str: 任务描述字符串
        """
        logger.debug(f"PlanningAgent: 处理 {len(messages)} 条消息以提取任务描述")
        
        task_description_messages = self._extract_task_description_messages(messages)
        result = self.convert_messages_to_str(task_description_messages)
        
        logger.debug(f"PlanningAgent: 生成任务描述，长度: {len(result)}")
        return result

    def _extract_completed_actions(self, messages: List[Dict[str, Any]]) -> str:
        """
        从消息中提取最近完成的工作
        
        Args:
            messages: 消息列表
            
        Returns:
            str: 最近完成工作的字符串
        """
        logger.debug(f"PlanningAgent: 处理 {len(messages)} 条消息以提取最近完成工作")
        
        # 使用新的方法提取最近完成工作
        recent_messages = self._extract_recent_completed_actions(messages)
        result = self.convert_messages_to_str(recent_messages)
        
        logger.debug(f"PlanningAgent: 生成最近完成工作，长度: {len(result)}")
        return result

    def _extract_recent_completed_actions(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        提取最近一次stage_summary之后的所有消息
        
        Args:
            messages: 消息列表
            
        Returns:
            List[Dict[str, Any]]: 最近完成工作的消息列表
        """
        logger.info(f"PlanningAgent: 从 {len(messages)} 条消息中提取最近完成工作")
        
        recent_messages = []
        found_last_stage_summary = False
        
        # 从最新的消息开始向前查找
        for index, msg in enumerate(reversed(messages)):
            # 检查是否是stage_summary类型的消息
            if msg.get('type') == 'stage_summary':
                
                # 找到最近一次stage_summary消息，提取该消息之后的所有消息
                # index是从0开始的，所以len(messages) - index - 1是stage_summary消息的位置
                # 我们需要从stage_summary消息的下一条消息开始提取
                start_index = len(messages) - index
                recent_messages = messages[start_index:]
                found_last_stage_summary = True
                logger.info(f"PlanningAgent: 找到最近一次stage_summary消息，提取之后 {len(recent_messages)} 条消息")
                break
        
        # 如果没有找到stage_summary类型的消息，则提取所有消息
        if not found_last_stage_summary:
            recent_messages = messages
            logger.info(f"PlanningAgent: 未找到stage_summary类型消息，提取全部 {len(recent_messages)} 条消息")
        
        # 过滤掉task_decomposition类型的消息
        filtered_messages = []
        for msg in recent_messages:
            msg_type = msg.get('type', 'normal')
            if msg_type != 'task_decomposition':
                filtered_messages.append(msg)
            else:
                logger.debug(f"PlanningAgent: 过滤掉task_decomposition消息")
        
        logger.info(f"PlanningAgent: 最终提取 {len(filtered_messages)} 条最近完成工作消息")
        return filtered_messages

    def run(self, 
            messages: List[Dict[str, Any]], 
            tool_manager: Optional[Any] = None,
            session_id: str = None,
            system_context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        执行任务规划（非流式版本）
        
        Args:
            messages: 对话历史记录
            tool_manager: 可选的工具管理器
            session_id: 会话ID
            system_context: 系统上下文
            
        Returns:
            List[Dict[str, Any]]: 任务规划结果消息列表
        """
        logger.info("PlanningAgent: 执行非流式任务规划")
        
        # 调用父类的默认实现，将流式结果合并
        return super().run(
            messages=messages,
            tool_manager=tool_manager,
            session_id=session_id,
            system_context=system_context
        )
