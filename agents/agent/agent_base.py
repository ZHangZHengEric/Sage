"""
AgentBase 重构版本

智能体基类，提供所有智能体的通用功能和接口。
改进了代码结构、错误处理、日志记录和可维护性。

作者: Eric ZZ
版本: 2.0 (重构版)
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Generator
import re,json
import uuid
import time
from agents.utils.logger import logger
from agents.tool.tool_base import AgentToolSpec
import traceback


class AgentBase(ABC):
    """
    智能体基类
    
    为所有智能体提供通用功能和接口，包括消息处理、工具转换、
    流式处理和内容解析等核心功能。
    """

    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        """
        初始化智能体基类
        
        Args:
            model: 可执行的语言模型实例
            model_config: 模型配置参数
            system_prefix: 系统前缀提示
        """
        self.model = model
        self.model_config = model_config
        self.system_prefix = system_prefix
        self.agent_description = f"{self.__class__.__name__} agent"
        
        # Token使用统计
        self.token_stats = {
            'total_calls': 0,
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'total_cached_tokens': 0,
            'total_reasoning_tokens': 0,
            'step_details': []  # 详细的每步记录
        }
        
        logger.debug(f"AgentBase: 初始化 {self.__class__.__name__}，模型配置: {model_config}")
    
    def _track_token_usage(self, response, step_name: str, start_time: float = None):
        """
        跟踪模型调用的token使用情况
        
        Args:
            response: 模型响应对象
            step_name: 步骤名称（如"task_analysis", "planning", "execution"等）
            start_time: 开始时间戳
        """
        if hasattr(response, 'usage') and response.usage:
            usage = response.usage
            
            # 提取token信息
            input_tokens = getattr(usage, 'prompt_tokens', 0)
            output_tokens = getattr(usage, 'completion_tokens', 0)
            total_tokens = getattr(usage, 'total_tokens', input_tokens + output_tokens)
            
            # 处理不同模型的特殊字段 - 修复对象访问方式
            cached_tokens = 0
            reasoning_tokens = 0
            
            # 处理prompt_tokens_details
            if hasattr(usage, 'prompt_tokens_details') and usage.prompt_tokens_details:
                if hasattr(usage.prompt_tokens_details, 'cached_tokens'):
                    cached_tokens = getattr(usage.prompt_tokens_details, 'cached_tokens', 0) or 0
            else:
                # 兼容性处理，某些模型可能直接在usage对象上有cached_tokens
                cached_tokens = getattr(usage, 'cached_tokens', 0) or 0
            
            # 处理completion_tokens_details  
            if hasattr(usage, 'completion_tokens_details') and usage.completion_tokens_details:
                if hasattr(usage.completion_tokens_details, 'reasoning_tokens'):
                    reasoning_tokens = getattr(usage.completion_tokens_details, 'reasoning_tokens', 0) or 0
            else:
                # 兼容性处理，某些模型可能直接在usage对象上有reasoning_tokens
                reasoning_tokens = getattr(usage, 'reasoning_tokens', 0) or 0
            
            # 更新统计
            self.token_stats['total_calls'] += 1
            self.token_stats['total_input_tokens'] += input_tokens
            self.token_stats['total_output_tokens'] += output_tokens
            self.token_stats['total_cached_tokens'] += cached_tokens
            self.token_stats['total_reasoning_tokens'] += reasoning_tokens
            
            # 记录详细步骤
            execution_time = time.time() - start_time if start_time else 0
            step_detail = {
                'step': step_name,
                'agent': self.__class__.__name__,
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'cached_tokens': cached_tokens,
                'reasoning_tokens': reasoning_tokens,
                'total_tokens': total_tokens,
                'execution_time': round(execution_time, 2),
                'timestamp': time.time()
            }
            self.token_stats['step_details'].append(step_detail)
            
            logger.info(f"{self.__class__.__name__}: {step_name} - 输入:{input_tokens}, 输出:{output_tokens}, 缓存:{cached_tokens}, 推理:{reasoning_tokens}, 总计:{total_tokens} tokens, 耗时:{execution_time:.2f}s")
    
    def _track_streaming_token_usage(self, chunks, step_name: str, start_time: float = None):
        """
        跟踪流式响应的token使用情况
        
        Args:
            chunks: 流式响应的所有chunks
            step_name: 步骤名称
            start_time: 开始时间戳
        """
        # 记录调试信息
        logger.debug(f"{self.__class__.__name__}: 开始跟踪流式token使用，收到 {len(chunks)} 个chunks")
        
        # 对于流式响应，只使用最后一个包含usage信息的chunk，避免重复统计
        final_usage_chunk = None
        for chunk in reversed(chunks):  # 从后往前找，使用最后的usage信息
            if hasattr(chunk, 'usage') and chunk.usage:
                final_usage_chunk = chunk
                logger.debug(f"{self.__class__.__name__}: 找到最终usage信息")
                break
        
        if final_usage_chunk:
            logger.debug(f"{self.__class__.__name__}: 使用最终chunk中的usage信息进行token跟踪")
            self._track_token_usage(final_usage_chunk, step_name, start_time)
        else:
            # 如果没有usage信息，记录一个空调用但计算execution_time
            self.token_stats['total_calls'] += 1
            execution_time = time.time() - start_time if start_time else 0
            step_detail = {
                'step': step_name,
                'agent': self.__class__.__name__,
                'input_tokens': 0,
                'output_tokens': 0,
                'cached_tokens': 0,
                'reasoning_tokens': 0,
                'total_tokens': 0,
                'execution_time': round(execution_time, 2),
                'timestamp': time.time(),
                'note': f'No usage info in {len(chunks)} chunks'
            }
            self.token_stats['step_details'].append(step_detail)
            logger.warning(f"{self.__class__.__name__}: {step_name} - 无法从 {len(chunks)} 个chunks中获取token使用信息，耗时:{execution_time:.2f}s")
    
    def get_token_stats(self) -> Dict[str, Any]:
        """
        获取当前agent的token使用统计
        
        Returns:
            Dict[str, Any]: Token使用统计信息
        """
        return {
            'agent_name': self.__class__.__name__,
            **self.token_stats
        }
    
    def reset_token_stats(self):
        """重置token统计"""
        self.token_stats = {
            'total_calls': 0,
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'total_cached_tokens': 0,
            'total_reasoning_tokens': 0,
            'step_details': []
        }
        logger.debug(f"{self.__class__.__name__}: Token统计已重置")
    
    def print_token_stats(self):
        """打印当前agent的token使用统计"""
        stats = self.get_token_stats()
        print(f"\n🤖 {stats['agent_name']} Token使用统计:")
        print(f"  📞 调用次数: {stats['total_calls']}")
        print(f"  📥 输入tokens: {stats['total_input_tokens']}")
        print(f"  📤 输出tokens: {stats['total_output_tokens']}")
        print(f"  🏃 缓存tokens: {stats['total_cached_tokens']}")
        print(f"  🧠 推理tokens: {stats['total_reasoning_tokens']}")
        print(f"  🔢 总计tokens: {stats['total_input_tokens'] + stats['total_output_tokens']}")
        
        if stats['step_details']:
            print(f"  📋 详细步骤:")
            for detail in stats['step_details']:
                print(f"    • {detail['step']}: 输入{detail['input_tokens']}, 输出{detail['output_tokens']}, 总计{detail['total_tokens']} tokens, 耗时{detail['execution_time']}s")

    def _call_llm_streaming(self, messages: List[Dict[str, Any]]):
        """
        通用的流式模型调用方法
        
        Args:
            messages: 输入消息列表
            
        Returns:
            Generator: 语言模型的流式响应
        """
        logger.debug(f"{self.__class__.__name__}: 调用语言模型进行流式生成")
        
        return self.model.chat.completions.create(
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            **self.model_config
        )
    
    def _call_llm_non_streaming(self, messages: List[Dict[str, Any]]):
        """
        通用的非流式模型调用方法
        
        Args:
            messages: 输入消息列表
            
        Returns:
            模型响应对象
        """
        logger.debug(f"{self.__class__.__name__}: 调用语言模型进行非流式生成")
        
        return self.model.chat.completions.create(
            messages=messages,
            stream=False,
            **self.model_config
        )
    
    def _create_message_chunk(self, 
                            content: str, 
                            message_id: str, 
                            show_content: str,
                            message_type: str = 'assistant',
                            role: str = 'assistant') -> List[Dict[str, Any]]:
        """
        创建通用的消息块
        
        Args:
            content: 消息内容
            message_id: 消息ID
            show_content: 显示内容
            message_type: 消息类型
            role: 消息角色
            
        Returns:
            List[Dict[str, Any]]: 格式化的消息块列表
        """
        message_chunk = {
            'role': role,
            'content': content,
            'type': message_type,
            'message_id': message_id,
            'show_content': show_content
        }
            
        return [message_chunk]
    
    def _handle_error_generic(self, 
                            error: Exception, 
                            error_context: str,
                            message_type: str = 'error') -> Generator[List[Dict[str, Any]], None, None]:
        """
        通用的错误处理方法
        
        Args:
            error: 发生的异常
            error_context: 错误上下文描述
            message_type: 消息类型
            
        Yields:
            List[Dict[str, Any]]: 错误消息块
        """
        logger.error(f"{self.__class__.__name__}: {error_context}错误: {str(error)}")
        
        error_message = f"\n{error_context}失败: {str(error)}"
        message_id = str(uuid.uuid4())
        
        yield [{
            'role': 'tool',
            'content': error_message,
            'type': message_type,
            'message_id': message_id,
            'show_content': error_message
        }]
    
    def _execute_streaming_with_token_tracking(self, 
                                             prompt: str, 
                                             step_name: str,
                                             system_message: Optional[Dict[str, Any]] = None,
                                             message_type: str = 'assistant') -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行流式处理并跟踪token使用
        
        Args:
            prompt: 用户提示
            step_name: 步骤名称（用于token统计）
            system_message: 可选的系统消息
            message_type: 消息类型
            
        Yields:
            List[Dict[str, Any]]: 流式输出的消息块
        """
        logger.info(f"{self.__class__.__name__}: 开始执行流式{step_name}")
        
        message_id = str(uuid.uuid4())
        
        # 准备消息
        if system_message:
            messages = [system_message, {"role": "user", "content": prompt}]
        else:
            messages = [{"role": "user", "content": prompt}]
        
        # 执行流式处理
        chunk_count = 0
        start_time = time.time()
        
        # 收集所有chunks以便跟踪token使用
        chunks = []
        for chunk in self._call_llm_streaming(messages):
            chunks.append(chunk)
            if len(chunk.choices) ==0:
                continue
            if chunk.choices[0].delta.content:
                delta_content = chunk.choices[0].delta.content
                chunk_count += 1
                
                # 传递usage信息到消息块
                yield self._create_message_chunk(
                    content=delta_content,
                    message_id=message_id,
                    show_content=delta_content,
                    message_type=message_type
                )
        
        # 跟踪token使用情况
        self._track_streaming_token_usage(chunks, step_name, start_time)
        
        logger.info(f"{self.__class__.__name__}: 流式{step_name}完成，共生成 {chunk_count} 个文本块")
        
        # 发送结束标记（也包含最终的usage信息）
        yield self._create_message_chunk(
            content="",
            message_id=message_id,
            show_content="\n",
            message_type=message_type
        )
    
    def prepare_unified_system_message(self,
                                     session_id: Optional[str] = None,
                                     system_context: Optional[Dict[str, Any]] = None,
                                     custom_prefix: Optional[str] = None) -> Dict[str, Any]:
        """
        统一的系统消息生成方法
        
        这个方法会自动使用每个agent定义的SYSTEM_PREFIX_DEFAULT常量，
        如果agent没有定义该常量，则使用传入的custom_prefix或默认的system_prefix。
        
        Args:
            session_id: 会话ID（向后兼容，现在可从system_context获取）
            system_context: 运行时系统上下文字典，包含所有需要的信息
            custom_prefix: 自定义前缀，如果agent没有SYSTEM_PREFIX_DEFAULT时使用
            
        Returns:
            Dict[str, Any]: 统一格式的系统消息字典
        """
        logger.debug(f"{self.__class__.__name__}: 生成统一系统消息")
        
        # 1. 确定系统前缀
        system_prefix = self._get_system_prefix(custom_prefix)
        
        # 2. 构建基础系统内容
        system_content = system_prefix
        
        # 3. 添加运行时system_context信息
        if system_context:
            system_content += self._build_system_context_section(system_context)
        
        logger.debug(f"{self.__class__.__name__}: 系统消息生成完成，总长度: {len(system_content)}")
        
        # 4. 打印完整的系统提示信息（新增）
        print("\n" + "="*100)
        print(f"🤖 {self.__class__.__name__} - 系统提示消息")
        print("="*100)
        print(f"📋 Agent类型: {self.__class__.__name__}")
        print(f"🆔 会话ID: {session_id if session_id else system_context.get('session_id', 'None') if system_context else 'None'}")
        
        if system_context:
            print(f"🔧 System Context字段: {list(system_context.keys())}")
            print(f"📊 System Context详情:")
            for key, value in system_context.items():
                if isinstance(value, str) and len(value) > 100:
                    print(f"   • {key}: {value[:100]}... (长度: {len(value)})")
                else:
                    print(f"   • {key}: {value}")
        else:
            print("🔧 System Context: None")
        
        print(f"📏 完整系统消息长度: {len(system_content)} 字符")
        print("📝 完整系统消息内容:")
        print("-" * 50)
        print(system_content)
        print("-" * 50)
        print("="*100 + "\n")
        
        return {
            'role': 'system',
            'content': system_content
        }
    
    def _get_system_prefix(self, custom_prefix: Optional[str] = None) -> str:
        """
        获取系统前缀
        
        优先级：
        1. agent的SYSTEM_PREFIX_DEFAULT常量
        2. custom_prefix参数
        3. agent的system_prefix实例变量
        4. 默认描述
        
        Args:
            custom_prefix: 自定义前缀
            
        Returns:
            str: 最终的系统前缀
        """
        # 优先使用agent定义的SYSTEM_PREFIX_DEFAULT常量
        if hasattr(self, 'SYSTEM_PREFIX_DEFAULT'):
            return self.SYSTEM_PREFIX_DEFAULT
        
        # 其次使用传入的custom_prefix
        if custom_prefix:
            return custom_prefix
        
        # 再次使用实例的system_prefix
        if self.system_prefix:
            return self.system_prefix
        
        # 最后使用默认描述
        return f"你是一个{self.__class__.__name__}智能体。"
    
    def _build_system_context_section(self, system_context: Dict[str, Any]) -> str:
        """
        构建运行时system_context信息部分
        
        Args:
            system_context: 运行时系统上下文字典
            
        Returns:
            str: 格式化的system_context字符串
        """
        logger.debug(f"{self.__class__.__name__}: 添加运行时system_context到系统消息")
        section = "\n\n补充上下文信息：\n"
        
        for key, value in system_context.items():
            if isinstance(value, dict):
                # 如果值是字典，格式化显示
                formatted_dict = json.dumps(value, ensure_ascii=False, indent=2)
                section += f"{key}: {formatted_dict}\n"
            elif isinstance(value, (list, tuple)):
                # 如果值是列表或元组，格式化显示
                formatted_list = json.dumps(list(value), ensure_ascii=False, indent=2)
                section += f"{key}: {formatted_list}\n"
            else:
                # 其他类型直接转换为字符串
                section += f"{key}: {str(value)}\n"
        
        return section

    @abstractmethod
    def run_stream(self, 
                   messages: List[Dict[str, Any]], 
                   tool_manager: Optional[Any] = None,
                   session_id: str = None,
                   system_context: Optional[Dict[str, Any]] = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        流式处理消息的抽象方法
        
        Args:
            messages: 对话消息列表
            tool_manager: 可选的工具管理器
            session_id: 会话ID
            system_context: 运行时系统上下文字典，包含基础信息和用户自定义信息
            
        Yields:
            List[Dict[str, Any]]: 流式输出的消息块
        """
        pass

    def run(self, 
            messages: List[Dict[str, Any]], 
            tool_manager: Optional[Any] = None,
            session_id: str = None,
            system_context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        执行Agent任务（非流式版本）
        
        默认实现：收集流式输出的所有块并合并为最终结果
        
        Args:
            messages: 对话历史记录
            tool_manager: 工具管理器
            session_id: 会话ID
            system_context: 运行时系统上下文字典，包含基础信息和用户自定义信息
            
        Returns:
            List[Dict[str, Any]]: 任务执行结果消息列表
        """
        logger.debug(f"AgentBase: 开始执行非流式任务，Agent类型: {self.__class__.__name__}")
        
        # 收集所有流式输出的块
        all_chunks = []
        for chunk_batch in self.run_stream(
            messages=messages,
            tool_manager=tool_manager,
            session_id=session_id,
            system_context=system_context
        ):
            all_chunks.extend(chunk_batch)
        
        # 合并相同message_id的块
        merged_messages = self._merge_chunks(all_chunks)
        
        # 记录Agent的完整输出
        self._log_agent_output(merged_messages)
        
        logger.debug(f"AgentBase: 非流式任务完成，返回 {len(merged_messages)} 条合并消息")
        return merged_messages

    def _log_agent_output(self, final_messages: List[Dict[str, Any]]) -> None:
        """
        记录Agent的完整输出日志
        
        Args:
            final_messages: Agent最终输出的完整消息列表
        """
        agent_name = self.__class__.__name__
        
        logger.info(f"🎯 {agent_name} 执行完成!")
        logger.info(f"📊 {agent_name} 总共输出 {len(final_messages)} 条完整消息")
        
        if final_messages:
            logger.info(f"📋 {agent_name} 完整输出messages:")
            
            for i, msg in enumerate(final_messages):
                logger.info(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                logger.info(f"  📝 消息 [{i+1}/{len(final_messages)}]:")
                logger.info(f"    🔹 Role: {msg.get('role', 'unknown')}")
                logger.info(f"    🔹 Type: {msg.get('type', 'unknown')}")
                logger.info(f"    🔹 Message ID: {msg.get('message_id', 'none')}")
                
                # 处理tool_calls
                if 'tool_calls' in msg and msg['tool_calls']:
                    logger.info(f"    🔹 Tool Calls: {len(msg['tool_calls'])} 个")
                    for j, tool_call in enumerate(msg['tool_calls']):
                        logger.info(f"      🔧 Tool Call [{j+1}]:")
                        logger.info(f"        • ID: {tool_call.get('id', 'none')}")
                        logger.info(f"        • Function: {tool_call.get('function', {}).get('name', 'unknown')}")
                        logger.info(f"        • Arguments: {tool_call.get('function', {}).get('arguments', 'none')}")
                
                # 处理tool_call_id
                if 'tool_call_id' in msg:
                    logger.info(f"    🔹 Tool Call ID: {msg['tool_call_id']}")
                
                # 显示完整的content内容
                if msg.get('content'):
                    content = str(msg['content'])
                    # 优化日志：单行显示内容，超长则截断
                    if len(content) <= 200:
                        # 短内容：替换换行符并单行显示
                        content_oneline = content.replace('\n', ' | ').replace('\r', ' ')
                        logger.info(f"    📄 Content ({len(content)} 字符): {content_oneline}")
                    else:
                        # 长内容：显示前200字符并截断
                        content_preview = content[:200].replace('\n', ' | ').replace('\r', ' ')
                        logger.info(f"    📄 Content ({len(content)} 字符): {content_preview}... [截断显示]")
                    
                    # 如果内容包含多行，额外显示行数信息
                    line_count = content.count('\n') + 1
                    if line_count > 1:
                        logger.info(f"    📄 Content详情: 共 {line_count} 行")
                    
                    # 如果是JSON格式，尝试简化显示
                    if content.strip().startswith('{') and content.strip().endswith('}'):
                        try:
                            import json
                            parsed = json.loads(content)
                            # 显示JSON的关键信息
                            if isinstance(parsed, dict):
                                keys = list(parsed.keys())[:5]  # 显示前5个键
                                logger.info(f"    📄 JSON结构: 包含字段 {keys}{'...' if len(parsed) > 5 else ''}")
                        except:
                            pass
                
                # 显示完整的show_content内容
                if msg.get('show_content'):
                    show_content = str(msg['show_content'])
                    # 优化日志：单行显示内容，超长则截断
                    if len(show_content) <= 200:
                        # 短内容：替换换行符并单行显示
                        show_oneline = show_content.replace('\n', ' | ').replace('\r', ' ')
                        logger.info(f"    🎨 Show Content ({len(show_content)} 字符): {show_oneline}")
                    else:
                        # 长内容：显示前200字符并截断
                        show_preview = show_content[:200].replace('\n', ' | ').replace('\r', ' ')
                        logger.info(f"    🎨 Show Content ({len(show_content)} 字符): {show_preview}... [截断显示]")
                    
                    # 如果内容包含多行，额外显示行数信息
                    line_count = show_content.count('\n') + 1
                    if line_count > 1:
                        logger.info(f"    🎨 Show Content详情: 共 {line_count} 行")
                
                # 显示其他重要字段
                other_fields = {k: v for k, v in msg.items() 
                              if k not in ['role', 'type', 'message_id', 'content', 'show_content', 'tool_calls', 'tool_call_id']}
                if other_fields:
                    logger.info(f"    🔹 其他字段: {other_fields}")
        
        logger.info(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info(f"🏁 {agent_name} 执行流程结束")
        logger.info("")  # 添加一个空行以便阅读

    def to_tool(self) -> AgentToolSpec:
        """
        将智能体转换为工具格式
        
        Returns:
            AgentToolSpec: 包含智能体运行方法的工具规范
        """
        logger.debug(f"AgentBase: 将 {self.__class__.__name__} 转换为工具格式")
        
        tool_spec = AgentToolSpec(
            name=self.__class__.__name__,
            description=self.agent_description + '\n\n Agent类型的工具，可以自动读取历史对话，所需不需要运行的参数',
            func=self.run,
            parameters={},
            required=[]
        )
        
        return tool_spec
        

    def _extract_json_from_markdown(self, content: str) -> str:
        """
        从markdown代码块中提取JSON内容
        
        Args:
            content: 可能包含markdown代码块的内容
            
        Returns:
            str: 提取的JSON内容，如果没有找到代码块则返回原始内容
        """
        logger.debug("AgentBase: 尝试从内容中提取JSON")
        
        # 首先尝试直接解析
        try:
            json.loads(content)
            return content
        except json.JSONDecodeError:
            pass
        
        # 尝试从markdown代码块中提取
        code_block_pattern = r'```(?:json)?\n([\s\S]*?)\n```'
        match = re.search(code_block_pattern, content)
        
        if match:
            try:
                json.loads(match.group(1))
                logger.debug("AgentBase: 成功从markdown代码块中提取JSON")
                return match.group(1)
            except json.JSONDecodeError:
                logger.warning(f"AgentBase: {self.__class__.__name__} 解析markdown代码块中的JSON失败")
                pass
        
        logger.debug("AgentBase: 未找到有效JSON，返回原始内容")
        return content

    def _extract_completed_actions_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        从消息中提取已完成的操作
        
        Args:
            messages: 消息列表
            
        Returns:
            List[Dict[str, Any]]: 已完成操作的消息列表
        """
        logger.debug(f"AgentBase: {self.__class__.__name__} 从 {len(messages)} 条消息中提取已完成操作")
        
        completed_actions_messages = []
        
        # 从最后一条用户消息开始提取
        for index, msg in enumerate(reversed(messages)):
            if msg['role'] == 'user':
                completed_actions_messages.extend(messages[len(messages) - index:])
                break
        
        # 移除任务分解类型的消息
        completed_actions_messages = [
            msg for msg in completed_actions_messages 
            if msg.get('type') != 'task_decomposition'
        ]

        logger.debug(f"AgentBase: {self.__class__.__name__} 提取了 {len(completed_actions_messages)} 条已完成操作消息")
        return completed_actions_messages

    def _extract_task_description_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        从消息中提取任务描述
        
        Args:
            messages: 消息列表
            
        Returns:
            List[Dict[str, Any]]: 任务描述相关的消息列表
        """
        logger.debug(f"AgentBase: {self.__class__.__name__} 从 {len(messages)} 条消息中提取任务描述")
        
        task_description_messages = []
        
        # 提取到最后一条用户消息为止
        for index, msg in enumerate(reversed(messages)):
            if msg['role'] == 'user':
                task_description_messages.extend(messages[:len(messages) - index])
                break
        
        # 只保留正常类型和最终答案类型的消息
        task_description_messages = [
            msg for msg in task_description_messages 
            if msg.get('type') in ['normal', 'final_answer']
        ]

        logger.debug(f"AgentBase: {self.__class__.__name__} 提取了 {len(task_description_messages)} 条任务描述消息")
        return task_description_messages

    def clean_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        清理消息，只保留OpenAI需要的字段
        
        Args:
            messages: 原始消息列表
            
        Returns:
            List[Dict[str, Any]]: 清理后的消息列表
        """
        logger.debug(f"AgentBase: 清理 {len(messages)} 条消息")
        
        clean_messages = []
        
        for msg in messages:
                if 'tool_calls' in msg and msg['tool_calls'] is not None:
                    clean_messages.append({
                        'role': msg['role'],
                        'tool_calls': msg['tool_calls']
                    })
                elif 'content' in msg:
                    if 'tool_call_id' in msg:
                        clean_messages.append({
                            'role': msg['role'],
                            'content': msg['content'],
                            'tool_call_id': msg['tool_call_id']
                        })
                    else:
                        clean_messages.append({
                            'role': msg['role'],
                            'content': msg['content']
                        })
        
        logger.debug(f"AgentBase: 清理后保留 {len(clean_messages)} 条消息")
        return clean_messages

    def _merge_messages(self, 
                       all_messages: List[Dict[str, Any]], 
                       new_messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        通过message_id将新消息合并到现有消息中
        
        Args:
            all_messages: 当前完整的消息列表
            new_messages: 要合并的新消息
            
        Returns:
            List[Dict[str, Any]]: 合并后的消息列表
        """
        merged = []
        message_map = {}
        
        # 首先添加所有现有消息
        for msg in all_messages:
            msg_copy = msg.copy()
            # 确保消息有message_id
            if 'message_id' not in msg_copy:
                msg_copy['message_id'] = str(uuid.uuid4())
                logger.warning(f"AgentBase: 为现有消息自动生成message_id: {msg_copy['message_id'][:8]}...")
            merged.append(msg_copy)
            message_map[msg_copy['message_id']] = msg_copy
        
        # 然后合并新消息
        for msg in new_messages:
            msg_copy = msg.copy()
            # 确保消息有message_id
            if 'message_id' not in msg_copy:
                msg_copy['message_id'] = str(uuid.uuid4())
                logger.warning(f"AgentBase: 为新消息自动生成message_id: {msg_copy['message_id'][:8]}...")
                
            msg_id = msg_copy['message_id']
            
            if msg_id in message_map:
                # 更新现有消息内容
                existing = message_map[msg_id]
                if 'content' in existing:
                    existing['content'] += msg_copy.get('content', '')
                if 'show_content' in existing:                
                    existing['show_content'] += msg_copy.get('show_content', '')
            else:
                # 添加新消息
                merged.append(msg_copy)
                message_map[msg_id] = msg_copy
        
        return merged

    def _merge_chunks(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        合并消息块，将具有相同message_id的块合并
        
        Args:
            chunks: 消息块列表
            
        Returns:
            List[Dict[str, Any]]: 合并后的消息列表
        """
        if not chunks:
            return []
        
        merged_map = {}
        result = []
        
        for chunk in chunks:
            message_id = chunk.get('message_id')
            if not message_id:
                result.append(chunk)
                continue
                
            if message_id in merged_map:
                # 合并内容
                existing = merged_map[message_id]
                if 'content' in chunk:
                    existing['content'] = existing.get('content', '') + chunk['content']
                if 'show_content' in chunk:
                    existing['show_content'] = existing.get('show_content', '') + chunk['show_content']
            else:
                merged_map[message_id] = chunk.copy()
                result.append(merged_map[message_id])
        
        return result

    def convert_messages_to_str(self, messages: List[Dict[str, Any]]) -> str:
        """
        将消息列表转换为字符串格式
        
        Args:
            messages: 消息列表
            
        Returns:
            str: 格式化后的消息字符串
        """
        logger.debug(f"AgentBase: 将 {len(messages)} 条消息转换为字符串")
        
        messages_str_list = []
        
        for msg in messages:
            if msg['role'] == 'user':
                messages_str_list.append(f"User: {msg['content']}")
            elif msg['role'] == 'assistant':
                if 'content' in msg:
                    messages_str_list.append(f"Assistant: {msg['content']}")
                elif 'tool_calls' in msg:
                    messages_str_list.append(f"Assistant: Tool calls: {msg['tool_calls']}")
            elif msg['role'] == 'tool':
                messages_str_list.append(f"Tool: {msg['content']}")
        
        result = "\n".join(messages_str_list) or "None"
        logger.debug(f"AgentBase: 转换后字符串长度: {len(result)}")
        return result
    
    def _judge_delta_content_type(self, 
                                 delta_content: str, 
                                 all_tokens_str: str, 
                                 tag_type: List[str] = None) -> str:
        """
        判断增量内容的类型
        
        Args:
            delta_content: 增量内容
            all_tokens_str: 所有token字符串
            tag_type: 标签类型列表
            
        Returns:
            str: 内容类型
        """
        if tag_type is None:
            tag_type = []
            
        start_tag = [f"<{tag}>" for tag in tag_type]
        end_tag = [f"</{tag}>" for tag in tag_type]
        
        # 构造结束标签的所有可能前缀
        end_tag_process_list = []
        for tag in end_tag:
            for i in range(len(tag)):
                end_tag_process_list.append(tag[:i + 1])    
        
        last_tag = None
        last_tag_index = None
        
        all_tokens_str = (all_tokens_str + delta_content).strip()
        
        # 查找最后出现的标签
        for tag in start_tag + end_tag:
            index = all_tokens_str.rfind(tag)
            if index != -1:
                if last_tag_index is None or index > last_tag_index:
                    last_tag = tag
                    last_tag_index = index
        
        if last_tag is None:
            return "tag"
            
        if last_tag in start_tag:
            if last_tag_index + len(last_tag) == len(all_tokens_str):
                return 'tag'    
            for end_tag_process in end_tag_process_list:
                if all_tokens_str.endswith(end_tag_process):
                    return 'unknown'
            else:
                return last_tag.replace('<', '').replace('>', '')
        elif last_tag in end_tag:
            return 'tag'

    def _collect_and_log_stream_output(self, stream_generator: Generator[List[Dict[str, Any]], None, None]) -> Generator[List[Dict[str, Any]], None, None]:
        """
        收集流式输出并在最后记录完整日志的装饰器方法
        
        Args:
            stream_generator: 流式输出生成器
            
        Yields:
            List[Dict[str, Any]]: 流式输出的消息块
        """
        agent_name = self.__class__.__name__
        logger.debug(f"🔍 {agent_name} 开始收集流式输出...")
        
        all_output_chunks = []
        chunk_count = 0
        
        try:
            for chunk_batch in stream_generator:
                chunk_count += 1
                all_output_chunks.extend(chunk_batch)
                yield chunk_batch
        except Exception as e:
            logger.error(f"🔍 {agent_name} 在流式处理中发生异常: {str(e)}")
            logger.error(f"🔍 {agent_name} 异常堆栈: {traceback.format_exc()}")
            raise
        finally:
            logger.debug(f"🔍 {agent_name} 流式处理完成，总共收集 {len(all_output_chunks)} 个chunks")
            
            # 合并相同message_id的chunks
            merged_messages = self._merge_chunks(all_output_chunks)
            logger.debug(f"🔍 {agent_name} 合并后得到 {len(merged_messages)} 条消息")
            
            # 记录完整输出日志
            self._log_agent_output(merged_messages)

    def _extract_usage_from_chunk(self, chunk) -> Optional[Dict[str, Any]]:
        """
        从LLM chunk中提取usage信息的统一函数
        
        注意：这个函数用于在流式处理中为消息块添加usage信息，供前端显示使用。
        真正的token统计是在_track_streaming_token_usage中完成的，只统计最终的usage信息，避免重复统计。
        
        两个用途：
        1. 消息传递：每个消息块都包含当前可用的usage信息（可能是中间状态）
        2. 统计汇总：只在最后统计一次完整的usage信息
        
        Args:
            chunk: LLM响应chunk
            
        Returns:
            Optional[Dict[str, Any]]: 提取的usage信息，如果没有则返回None
        """
        if hasattr(chunk, 'usage') and chunk.usage:
            usage = chunk.usage
            
            # 处理不同模型的特殊字段 - 修复对象访问方式
            cached_tokens = 0
            reasoning_tokens = 0
            
            # 处理prompt_tokens_details
            if hasattr(usage, 'prompt_tokens_details') and usage.prompt_tokens_details:
                if hasattr(usage.prompt_tokens_details, 'cached_tokens'):
                    cached_tokens = getattr(usage.prompt_tokens_details, 'cached_tokens', 0) or 0
            else:
                # 兼容性处理，某些模型可能直接在usage对象上有cached_tokens
                cached_tokens = getattr(usage, 'cached_tokens', 0) or 0
            
            # 处理completion_tokens_details  
            if hasattr(usage, 'completion_tokens_details') and usage.completion_tokens_details:
                if hasattr(usage.completion_tokens_details, 'reasoning_tokens'):
                    reasoning_tokens = getattr(usage.completion_tokens_details, 'reasoning_tokens', 0) or 0
            else:
                # 兼容性处理，某些模型可能直接在usage对象上有reasoning_tokens
                reasoning_tokens = getattr(usage, 'reasoning_tokens', 0) or 0
            
            return {
                'prompt_tokens': getattr(usage, 'prompt_tokens', 0),
                'completion_tokens': getattr(usage, 'completion_tokens', 0),
                'total_tokens': getattr(usage, 'total_tokens', 0),
                'cached_tokens': cached_tokens,
                'reasoning_tokens': reasoning_tokens
            }
        return None
