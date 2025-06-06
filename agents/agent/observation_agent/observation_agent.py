"""
ObservationAgent 重构版本

观察智能体，负责分析任务执行进度和完成状态。
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
from agents.utils.logger import logger


class ObservationAgent(AgentBase):
    """
    观察智能体
    
    负责分析任务执行进度，评估完成状态，并提供后续建议。
    支持流式输出，实时返回分析结果。
    """

    # 分析提示模板常量
    ANALYSIS_PROMPT_TEMPLATE = """# 任务执行分析指南

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

    # 系统提示模板常量
    SYSTEM_PREFIX_DEFAULT = """你是一个智能AI助手，你的任务是分析任务的执行情况，并提供后续建议。"""
    
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        """
        初始化观察智能体
        
        Args:
            model: 语言模型实例
            model_config: 模型配置参数
            system_prefix: 系统前缀提示
        """
        super().__init__(model, model_config, system_prefix)
        self.agent_description = "观察智能体，专门负责分析任务执行进度和完成状态"
        logger.info("ObservationAgent 初始化完成")

    def run_stream(self, 
                   messages: List[Dict[str, Any]], 
                   tool_manager: Optional[Any] = None,
                   session_id: str = None,
                   system_context: Optional[Dict[str, Any]] = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        流式执行观察分析
        
        分析任务执行情况并确定完成状态，实时返回分析结果。
        
        Args:
            messages: 对话历史记录，包含执行结果
            tool_manager: 可选的工具管理器
            session_id: 可选的会话标识符
            system_context: 系统上下文
            
        Yields:
            List[Dict[str, Any]]: 流式输出的观察分析消息块
        """
        logger.info(f"ObservationAgent: 开始流式观察分析，消息数量: {len(messages)}")
        
        # 使用基类方法收集和记录流式输出
        yield from self._collect_and_log_stream_output(
            self._execute_observation_stream_internal(messages, tool_manager, session_id, system_context)
        )

    def _execute_observation_stream_internal(self, 
                                           messages: List[Dict[str, Any]],
                                           tool_manager: Optional[Any],
                                           session_id: str,
                                           system_context: Optional[Dict[str, Any]]) -> Generator[List[Dict[str, Any]], None, None]:
        """
        内部观察流式执行方法
        
        Args:
            messages: 对话历史记录，包含执行结果
            tool_manager: 可选的工具管理器
            session_id: 可选的会话标识符
            system_context: 系统上下文
            
        Yields:
            List[Dict[str, Any]]: 流式输出的观察分析消息块
        """
        try:
            # 准备分析上下文
            analysis_context = self._prepare_observation_context(
                messages=messages,
                session_id=session_id
            )
            
            # 生成分析提示
            prompt = self._generate_observation_prompt(analysis_context)
            
            # 执行流式观察分析
            yield from self._execute_streaming_observation(prompt, session_id, system_context)
            
        except Exception as e:
            logger.error(f"ObservationAgent: 观察分析过程中发生异常: {str(e)}")
            logger.error(f"异常详情: {traceback.format_exc()}")
            yield from self._handle_observation_error(e)

    def _prepare_observation_context(self, 
                                   messages: List[Dict[str, Any]],
                                   session_id: str) -> Dict[str, Any]:
        """
        准备观察分析所需的上下文信息
        
        Args:
            messages: 对话消息列表
            session_id: 会话ID
            
        Returns:
            Dict[str, Any]: 包含观察分析所需信息的上下文字典
        """
        logger.debug("ObservationAgent: 准备观察分析上下文")
        
        # 提取任务描述
        task_description = self._extract_task_description_to_str(messages)
        logger.debug(f"ObservationAgent: 提取任务描述，长度: {len(task_description)}")
        
        # 提取执行结果
        execution_results = self._extract_execution_results_to_str(messages)
        logger.debug(f"ObservationAgent: 提取执行结果，长度: {len(execution_results)}")
        
        observation_context = {
            'task_description': task_description,
            'execution_results': execution_results
        }
        
        logger.info("ObservationAgent: 观察分析上下文准备完成")
        return observation_context

    def _generate_observation_prompt(self, context: Dict[str, Any]) -> str:
        """
        生成观察分析提示
        
        Args:
            context: 观察分析上下文信息
            
        Returns:
            str: 格式化后的观察分析提示
        """
        logger.debug("ObservationAgent: 生成观察分析提示")
        
        prompt = self.ANALYSIS_PROMPT_TEMPLATE.format(
            task_description=context['task_description'],
            execution_results=context['execution_results']
        )
        
        logger.debug("ObservationAgent: 观察分析提示生成完成")
        return prompt

    def _execute_streaming_observation(self, 
                                     prompt: str,
                                     session_id: str,
                                     system_context: Optional[Dict[str, Any]]) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行流式观察分析
        
        Args:
            prompt: 分析提示
            session_id: 会话ID
            system_context: 系统上下文
            
        Yields:
            List[Dict[str, Any]]: 流式输出的消息块
        """
        logger.info("ObservationAgent: 开始执行流式观察分析")
        
        # 准备系统消息
        system_message = self.prepare_unified_system_message(
            session_id=session_id,
            system_context=system_context
        )
        
        # 使用基类的流式处理和token跟踪（简化版本）
        message_id = str(uuid.uuid4())
        chunk_count = 0
        all_content = ""
        
        # 收集流式响应内容
        start_time = time.time()
        chunks = []
        
        # 状态管理
        unknown_content = ''
        last_tag_type = 'tag'
        
        for chunk in self._call_llm_streaming([system_message, {"role": "user", "content": prompt}]):
            chunks.append(chunk)
            if len(chunk.choices) == 0:
                continue
            if chunk.choices[0].delta.content:
                delta_content = chunk.choices[0].delta.content
                
                for delta_content_char in delta_content:
                    delta_content_all = unknown_content + delta_content_char
                    tag_type = self._judge_delta_content_type(delta_content_all, all_content, tag_type=['needs_more_input','finish_percent','is_completed','analysis','suggestions','user_query'])
                    # print(f'delta_content: {delta_content}, tag_type: {tag_type}')
                    all_content += delta_content_char
                    chunk_count += 1
                    if tag_type == 'unknown':
                        unknown_content = delta_content_all
                        continue
                    else:
                        unknown_content = ''
                        if tag_type in ['analysis']:
                            if tag_type != last_tag_type:
                                yield self._create_message_chunk(
                                    content='',
                                    message_id=message_id,
                                    show_content='\n\n',
                                    message_type='observation_result'
                                )
                            
                            yield self._create_message_chunk(
                                content='',
                                message_id=message_id,
                                show_content=delta_content_all,
                                message_type='observation_result'
                            )
                        last_tag_type = tag_type
        
        # 跟踪token使用
        self._track_streaming_token_usage(chunks, "observation", start_time)
        
        logger.info(f"ObservationAgent: 流式观察分析完成，共生成 {chunk_count} 个文本块")
        
        # 处理最终结果
        yield from self._finalize_observation_result(all_content, message_id)

    def _finalize_observation_result(self, 
                                   all_content: str, 
                                   message_id: str) -> Generator[List[Dict[str, Any]], None, None]:
        """
        完成观察结果并返回最终分析
        
        Args:
            all_content: 完整的内容
            message_id: 消息ID
            
        Yields:
            List[Dict[str, Any]]: 最终观察结果消息块
        """
        logger.debug("ObservationAgent: 处理最终观察结果")
        
        try:
            response_json = self.convert_xlm_to_json(all_content)
            logger.info(f"ObservationAgent: 观察分析结果: {response_json}")
            
            # 创建最终结果消息（不需要usage信息，因为这是转换过程）
            result_message = {
                'role': 'assistant',
                'content': 'Observation: ' + json.dumps(response_json, ensure_ascii=False),
                'type': 'observation_result',
                'message_id': message_id,
                'show_content': '\n'
            }
            
            yield [result_message]
            
        except Exception as e:
            logger.error(f"ObservationAgent: 解析观察结果时发生错误: {str(e)}")
            yield from self._handle_observation_error(e)

    def _handle_observation_error(self, error: Exception) -> Generator[List[Dict[str, Any]], None, None]:
        """
        处理观察分析过程中的错误
        
        Args:
            error: 发生的异常
            
        Yields:
            List[Dict[str, Any]]: 错误消息块
        """
        yield from self._handle_error_generic(
            error=error,
            error_context="观察分析",
            message_type='observation_result'
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
            <needs_more_input>true</needs_more_input>
            <finish_percent>50</finish_percent>
            ...
            
            输出JSON格式：
            {
                "needs_more_input": true,
                "finish_percent": 50,
                ...
            }
        """
        logger.debug("ObservationAgent: 转换XML内容为JSON格式")
        
        try:
            # 提取needs_more_input并转换为boolean类型
            needs_more_input = xlm_content.split('<needs_more_input>')[1].split('</needs_more_input>')[0].strip()
            needs_more_input = needs_more_input.lower() == 'true'
            
            # 提取finish_percent并转换为int类型
            finish_percent = xlm_content.split('<finish_percent>')[1].split('</finish_percent>')[0].strip()
            finish_percent = int(finish_percent)
            
            # 提取is_completed并转换为boolean类型
            is_completed = xlm_content.split('<is_completed>')[1].split('</is_completed>')[0].strip()
            is_completed = is_completed.lower() == 'true'
            
            # 提取analysis
            analysis = xlm_content.split('<analysis>')[1].split('</analysis>')[0].strip()
            
            # 提取suggestions并转换为list类型
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
            
            # 构建响应JSON
            response_json = {
                "needs_more_input": needs_more_input,
                "finish_percent": finish_percent,
                "is_completed": is_completed,
                "analysis": analysis,   
                "suggestions": suggestions,
                "user_query": user_query   
            }
            
            logger.debug(f"ObservationAgent: XML转JSON完成: {response_json}")
            return response_json
            
        except Exception as e:
            logger.error(f"ObservationAgent: XML转JSON失败: {str(e)}")
            raise

    def _extract_task_description_to_str(self, messages: List[Dict[str, Any]]) -> str:
        """
        提取任务描述并转换为字符串
        
        Args:
            messages: 消息列表
            
        Returns:
            str: 任务描述字符串
        """
        logger.debug(f"ObservationAgent: 处理 {len(messages)} 条消息以提取任务描述")
        
        task_description_messages = self._extract_task_description_messages(messages)
        result = self.convert_messages_to_str(task_description_messages)
        
        logger.debug(f"ObservationAgent: 生成任务描述，长度: {len(result)}")
        return result

    def _extract_execution_results_to_str(self, messages: List[Dict[str, Any]]) -> str:
        """
        提取执行结果并转换为字符串
        
        Args:
            messages: 消息列表
            
        Returns:
            str: 执行结果字符串
        """
        logger.debug(f"ObservationAgent: 处理 {len(messages)} 条消息以提取执行结果")
        
        completed_actions_messages = self._extract_completed_actions_messages(messages)
        result = self.convert_messages_to_str(completed_actions_messages)
        
        logger.debug(f"ObservationAgent: 生成执行结果，长度: {len(result)}")
        return result

    def run(self, 
            messages: List[Dict[str, Any]], 
            tool_manager: Optional[Any] = None,
            session_id: str = None,
            system_context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        执行观察分析（非流式版本）
        
        Args:
            messages: 对话历史记录
            tool_manager: 可选的工具管理器
            session_id: 会话ID
            system_context: 系统上下文
            
        Returns:
            List[Dict[str, Any]]: 观察分析结果消息列表
        """
        logger.info("ObservationAgent: 执行非流式观察分析")
        
        # 调用父类的默认实现，将流式结果合并
        return super().run(
            messages=messages,
            tool_manager=tool_manager,
            session_id=session_id,
            system_context=system_context
        )
