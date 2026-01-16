from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Union, AsyncGenerator, cast
import json
from sagents.utils.logger import logger
from sagents.tool.tool_config import AgentToolSpec
from sagents.tool.tool_manager import ToolManager
from sagents.context.session_context import get_session_context, SessionContext, SessionStatus
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.utils.prompt_manager import prompt_manager
import traceback
import time
import os
from openai import AsyncOpenAI
from openai.types.chat import chat_completion_chunk
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessage,
    ChatCompletionMessageToolCall,
)
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message_tool_call import Function
from openai.types.completion_usage import CompletionUsage


class AgentBase(ABC):
    """
    智能体基类

    为所有智能体提供通用功能和接口，包括消息处理、工具转换、
    流式处理和内容解析等核心功能。
    """

    def __init__(self, model: Optional[AsyncOpenAI] = None, model_config: Dict[str, Any] = {}, system_prefix: str = ""):
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
        self.agent_name = self.__class__.__name__

        # 设置最大输入长度（用于安全检查，防止消息过长）
        # 实际的上下文长度由 SessionContext 中的 context_budget_manager 动态管理
        # 这里只是作为兜底的安全阈值

        self.max_model_input_len = 50000

        logger.debug(f"AgentBase: 初始化 {self.__class__.__name__}，模型配置: {model_config}, 最大输入长度（安全阈值）: {self.max_model_input_len}")

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
            description_i18n={},
            func=self.run_stream,
            parameters={},
            required=[]
        )

        return tool_spec

    @abstractmethod
    async def run_stream(self,
                         session_context: SessionContext,
                         tool_manager: Optional[ToolManager] = None,
                         session_id: Optional[str] = None,
                         ) -> AsyncGenerator[List[MessageChunk], None]:
        """
        流式处理消息的抽象方法

        Args:
            session_context: 会话上下文
            tool_manager: 可选的工具管理器
            session_id: 会话ID

        Yields:
            List[MessageChunk]: 流式输出的消息块
        """
        if False:
            yield []

    def _remove_tool_call_without_id(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        移除assistant 是tool call 但是在messages中其他的role 为tool 的消息中没有对应的tool call id

        Args:
            messages: 输入消息列表

        Returns:
            List[Dict[str, Any]]: 移除了没有对应 tool_call_id 的tool call 消息
        """
        new_messages = []
        all_tool_call_ids_from_tool = []
        for msg in messages:
            if msg.get('role') == MessageRole.TOOL.value and 'tool_call_id' in msg:
                all_tool_call_ids_from_tool.append(msg['tool_call_id'])
        for msg in messages:
            if msg.get('role') == MessageRole.ASSISTANT.value and 'tool_calls' in msg:
                tool_calls = msg['tool_calls']
                # 如果tool_calls 里面的id 没有在其他的role 为tool 的消息中出现，就移除这个消息
                if any(tool_call['id'] not in all_tool_call_ids_from_tool for tool_call in tool_calls):
                    continue
            new_messages.append(msg)
        return new_messages

    async def _call_llm_streaming(self, messages: List[Union[MessageChunk, Dict[str, Any]]], session_id: Optional[str] = None, step_name: str = "llm_call", model_config_override: Optional[Dict[str, Any]] = None):
        """
        通用的流式模型调用方法，有这个封装，主要是为了将
        模型调用和日志记录等功能统一起来，以及token 的记录等，方便后续的维护和扩展。

        Args:
            messages: 输入消息列表
            session_id: 会话ID（用于请求记录）
            step_name: 步骤名称（用于请求记录）
            model_config_override: 覆盖模型配置（用于工具调用等）

        Returns:
            Generator: 语言模型的流式响应
        """
        logger.debug(f"{self.__class__.__name__}: 调用语言模型进行流式生成")

        if session_id:
            sc_now = get_session_context(session_id)
            if sc_now is None or sc_now.status == SessionStatus.INTERRUPTED:
                logger.info(f"{self.__class__.__name__}: 跳过模型调用，session上下文不存在或已中断，会话ID: {session_id}")
                return
        # 确定最终的模型配置
        final_config = {**self.model_config}
        if model_config_override:
            final_config.update(model_config_override)

        model_name = cast(str, final_config.pop('model')) if 'model' in final_config else "gpt-3.5-turbo"
        # 移除不是OpenAI API标准参数的配置项
        final_config.pop('max_model_len', None)
        all_chunks = []

        try:
            if self.model is None:
                raise ValueError("Model is not initialized")

            # 发起LLM请求
            # 将 MessageChunk 对象转换为字典，以便进行 JSON 序列化
            start_request_time = time.time()
            serializable_messages = []
            for msg in messages:
                if isinstance(msg, MessageChunk):
                    serializable_messages.append(msg.to_dict())
                else:
                    serializable_messages.append(msg)

            # 只保留model.chat.completions.create 需要的messages的key，移除掉不不要的
            serializable_messages = [{k: v for k, v in msg.items() if k in ['role', 'content', 'tool_calls', 'tool_call_id']} for msg in serializable_messages]
            # print("serializable_messages:",serializable_messages)
            # 确保所有的messages 中都包含role 和 content
            for msg in serializable_messages:
                if 'role' not in msg:
                    msg['role'] = MessageRole.USER.value
                if 'content' not in msg:
                    msg['content'] = ''

            logger.info(f"{self.__class__.__name__}: 调用语言模型进行流式生成，模型配置: {final_config}")

            # 需要处理 serializable_messages 中，如果有tool call ，但是没有后续的tool call id,需要去掉这条消息
            serializable_messages = self._remove_tool_call_without_id(serializable_messages)

            stream = await self.model.chat.completions.create(
                model=model_name,
                messages=cast(List[Any], serializable_messages),
                stream=True,
                stream_options={"include_usage": True},
                extra_body={
                    "chat_template_kwargs": {"enable_thinking": False},
                    "enable_thinking": False,
                    "thinking": {'type': "disabled"},
                    "top_k": 20
                },
                **final_config
            )
            async for chunk in stream:
                # print(chunk)
                all_chunks.append(chunk)
                yield chunk

        except Exception as e:
            logger.error(f"{self.__class__.__name__}: LLM流式调用失败: {e}\n{traceback.format_exc()}")
            all_chunks.append(
                chat_completion_chunk.ChatCompletionChunk(
                    id="",
                    object="chat.completion.chunk",
                    created=0,
                    model="",
                    choices=[
                        chat_completion_chunk.Choice(
                            index=0,
                            delta=chat_completion_chunk.ChoiceDelta(
                                content=traceback.format_exc(),
                                tool_calls=None,
                            ),
                            finish_reason="stop",
                        )
                    ],
                    usage=None,
                )
            )
            raise e
        finally:
            # 将次请求记录在session context 中的llm调用记录中
            logger.info(f"{step_name}: 调用语言模型进行流式生成，耗时: {time.time() - start_request_time},返回{len(all_chunks)}个chunk")
            if session_id:
                session_context = get_session_context(session_id) if session_id else None

                llm_request = {
                    "step_name": step_name,
                    "model_config": final_config,
                    "messages": messages,
                }
                # 将流式的chunk，进行合并成非流式的response，保存下chunk所有的记录
                try:
                    llm_response = self.merge_stream_response_to_non_stream_response(all_chunks)
                except Exception:
                    logger.error(f"{self.__class__.__name__}: 合并流式响应失败: {traceback.format_exc()}")
                    logger.error(f"{self.__class__.__name__}: 合并流式响应失败: {all_chunks}")
                    llm_response = None
                if session_context:
                    session_context.add_llm_request(llm_request, llm_response)
                else:
                    logger.warning(f"{self.__class__.__name__}: session_context is None for session_id={session_id}, skip add_llm_request")

    def prepare_unified_system_message(self,
                                       session_id: Optional[str] = None,
                                       custom_prefix: Optional[str] = None,
                                       language: Optional[str] = None,
                                       system_prefix_override: Optional[str] = None) -> MessageChunk:
        """
        准备统一的系统消息

        Args:
            session_id: 会话ID
            custom_prefix: 自定义前缀,会添加到system_prefix 后面，system context 前面
            language: 语言设置
            system_prefix_override: 覆盖默认的系统前缀（避免修改self.SYSTEM_PREFIX_FIXED导致并发问题）

        Returns:
            MessageChunk: 系统消息
        """
        system_prefix = ""
        if system_prefix_override:
            system_prefix = system_prefix_override
        elif hasattr(self, 'SYSTEM_PREFIX_FIXED'):
            system_prefix = self.SYSTEM_PREFIX_FIXED
        else:
            if self.system_prefix:
                system_prefix = self.system_prefix
            else:
                # 使用PromptManager获取多语言文本
                agent_intro = prompt_manager.get_prompt(
                    'agent_intro_template',
                    agent='common',
                    language=language,
                    default=f"\n你是一个{self.__class__.__name__}智能体。"
                )
                system_prefix += agent_intro.format(agent_name=self.__class__.__name__)

        if custom_prefix:
            system_prefix += custom_prefix + '\n'

        # 根据session_id获取session_context信息（用于获取system_context和agent_workspace）
        session_context = None
        if session_id:
            session_context = get_session_context(session_id)

        if session_context:
            system_context_info = session_context.system_context
            logger.debug(f"{self.__class__.__name__}: 添加运行时system_context到系统消息")

            # 使用PromptManager获取多语言文本
            additional_info = prompt_manager.get_prompt(
                'additional_info_label',
                agent='common',
                language=language,
                default="\n补充其他的信息：\n "
            )
            system_prefix += additional_info

            for key, value in system_context_info.items():
                if isinstance(value, dict):
                    # 如果值是字典，格式化显示
                    formatted_dict = json.dumps(value, ensure_ascii=False, indent=2)
                    system_prefix += f"{key}: {formatted_dict}\n"
                elif isinstance(value, (list, tuple)):
                    # 如果值是列表或元组，格式化显示
                    formatted_list = json.dumps(list(value), ensure_ascii=False, indent=2)
                    system_prefix += f"{key}: {formatted_list}\n"
                else:
                    # 其他类型直接转换为字符串
                    system_prefix += f"{key}: {str(value)}\n"
            logger.debug(f"{self.__class__.__name__}: 系统消息生成完成，总长度: {len(system_prefix)}")

            # 补充当前工作空间中的文件情况，工作空间的路径是 session_context.agent_workspace,需要把这个文件夹下的文件或者文件夹，有可能多层路径，给展示出来，类似tree 结构，只展示文件的相对路径
            current_agent_workspace = session_context.agent_workspace
            if current_agent_workspace:
                workspace_name = session_context.system_context.get('file_workspace', '')

                # 使用PromptManager获取多语言文本
                workspace_files = prompt_manager.get_prompt(
                    'workspace_files_label',
                    agent='common',
                    language=language,
                    default=f"\n当前工作空间 {workspace_name} 的文件情况：\n"
                )
                system_prefix += workspace_files.format(workspace=workspace_name)

                # 如果没有文件，就不展示了
                if not os.listdir(current_agent_workspace):
                    no_files = prompt_manager.get_prompt(
                        'no_files_message',
                        agent='common',
                        language=language,
                        default="当前工作空间下没有文件。\n"
                    )
                    system_prefix += no_files
                else:
                    for root, dirs, files in os.walk(current_agent_workspace):
                        for file_item in files:
                            system_prefix += f"{os.path.join(root, file_item).replace(current_agent_workspace, '').lstrip('/')}\n"
                        for dir_item in dirs:
                            system_prefix += f"{os.path.join(root, dir_item).replace(current_agent_workspace, '').lstrip('/')}/\n"
                system_prefix += "\n"

        return MessageChunk(
            role=MessageRole.SYSTEM.value,
            content=system_prefix,
            type=MessageType.SYSTEM.value
        )

    def _judge_delta_content_type(self,
                                  delta_content: str,
                                  all_tokens_str: str,
                                  tag_type: Optional[List[str]] = None) -> str:
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
        last_tag_index: Optional[int] = None

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

        # Ensure last_tag_index is not None for mypy
        if last_tag_index is None:
            return "tag"

        if last_tag in start_tag:
            if last_tag_index + len(last_tag) == len(all_tokens_str):
                return 'tag'
            for end_tag_process in end_tag_process_list:
                if all_tokens_str.endswith(end_tag_process):
                    return 'unknown'
            else:
                return last_tag.replace("<", "").replace(">", "")
        elif last_tag in end_tag:
            return 'tag'

        return "tag"

    def _handle_tool_calls_chunk(self,
                                 chunk,
                                 tool_calls: Dict[str, Any],
                                 last_tool_call_id: str) -> None:
        """
        处理工具调用数据块

        Args:
            chunk: LLM响应块
            tool_calls: 工具调用字典
            last_tool_call_id: 最后的工具调用ID
        """
        if not chunk.choices or not chunk.choices[0].delta.tool_calls:
            return

        for tool_call in chunk.choices[0].delta.tool_calls:
            if tool_call.id is not None and len(tool_call.id) > 0:
                last_tool_call_id = tool_call.id

            if last_tool_call_id not in tool_calls:
                logger.info(f"{self.agent_name}: 检测到新工具调用: {last_tool_call_id}, 工具名称: {tool_call.function.name}")
                tool_calls[last_tool_call_id] = {
                    'id': last_tool_call_id,
                    'type': tool_call.type,
                    'function': {
                        'name': tool_call.function.name or "",
                        'arguments': tool_call.function.arguments if tool_call.function.arguments else ""
                    }
                }
            else:
                if tool_call.function.name:
                    logger.info(f"{self.agent_name}: 更新工具调用: {last_tool_call_id}, 工具名称: {tool_call.function.name}")
                    tool_calls[last_tool_call_id]['function']['name'] = tool_call.function.name
                if tool_call.function.arguments:
                    tool_calls[last_tool_call_id]['function']['arguments'] += tool_call.function.arguments

    def _create_tool_call_message(self, tool_call: Dict[str, Any]) -> List[MessageChunk]:
        """
        创建工具调用消息

        Args:
            tool_call: 工具调用信息

        Returns:
            List[Dict[str, Any]]: 工具调用消息列表
        """
        # 格式化工具参数显示
        # 兼容两种分隔符
        args = tool_call['function']['arguments']
        if '```<｜tool▁call▁end｜>' in args:
            logger.debug(f"{self.agent_name}: 原始错误参数(▁): {args}")
            tool_call['function']['arguments'] = args.split('```<｜tool▁call▁end｜>')[0]
        elif '```<｜tool call end｜>' in args:
            logger.debug(f"{self.agent_name}: 原始错误参数(space): {args}")
            tool_call['function']['arguments'] = args.split('```<｜tool call end｜>')[0]

        function_params = tool_call['function']['arguments']
        if len(function_params) > 0:
            try:
                function_params = json.loads(function_params)
            except json.JSONDecodeError:
                try:
                    function_params = eval(function_params)
                except Exception:
                    logger.error(f"{self.agent_name}: 第一次参数解析报错，再次进行参数解析失败")
                    logger.error(f"{self.agent_name}: 原始参数: {tool_call['function']['arguments']}")

            if isinstance(function_params, str):
                try:
                    function_params = json.loads(function_params)
                except json.JSONDecodeError:
                    try:
                        function_params = eval(function_params)
                    except Exception:
                        logger.error(f"{self.agent_name}: 解析完参数化依旧后是str，再次进行参数解析失败")
                        logger.error(f"{self.agent_name}: 原始参数: {tool_call['function']['arguments']}")
                        logger.error(f"{self.agent_name}: 工具参数格式错误: {function_params}")
                        logger.error(f"{self.agent_name}: 工具参数类型: {type(function_params)}")

            formatted_params = ''
            if isinstance(function_params, dict):
                tool_call['function']['arguments'] = json.dumps(function_params, ensure_ascii=False)
                for param, value in function_params.items():
                    formatted_params += f"{param} = {json.dumps(value, ensure_ascii=False)}, "
                formatted_params = formatted_params.rstrip(', ')
            else:
                # 只有当非空且非字典时才记录错误（SimpleAgent逻辑兼容）
                if function_params: 
                    logger.warning(f"{self.agent_name}: 参数解析结果不是字典: {type(function_params)}")
                formatted_params = str(function_params)
        else:
            formatted_params = ""

        tool_name = tool_call['function']['name']

        # 将show_content 整理成函数调用的形式
        return [MessageChunk(
            role='assistant',
            tool_calls=[{
                'id': tool_call['id'],
                'type': tool_call['type'],
                'function': {
                    'name': tool_call['function']['name'],
                    'arguments': tool_call['function']['arguments']
                }
            }],
            message_type=MessageType.TOOL_CALL.value,
            message_id=str(uuid.uuid4()),
            show_content=f"{tool_name}({formatted_params})"
        )]

    async def _execute_tool(self,
                            tool_call: Dict[str, Any],
                            tool_manager: Optional[ToolManager],
                            messages_input: List[Any],
                            session_id: str) -> AsyncGenerator[List[MessageChunk], None]:
        """
        执行工具

        Args:
            tool_call: 工具调用信息
            tool_manager: 工具管理器
            messages_input: 输入消息列表
            session_id: 会话ID

        Yields:
            List[MessageChunk]: 消息块列表
        """
        tool_name = tool_call['function']['name']

        try:
            # 解析并执行工具调用
            if len(tool_call['function']['arguments']) > 0:
                arguments = json.loads(tool_call['function']['arguments'])
            else:
                arguments = {}

            if not isinstance(arguments, dict):
                async for chunk in self._handle_tool_error(tool_call['id'], tool_name, Exception("工具参数格式错误: 参数必须是JSON对象")):
                    yield chunk
                return

            logger.info(f"{self.agent_name}: 执行工具 {tool_name}")
            if not tool_manager:
                raise ValueError("Tool manager is not provided")

            tool_response = await tool_manager.run_tool_async(
                tool_name,
                session_context=get_session_context(session_id),
                session_id=session_id,
                **arguments
            )

            # 检查是否为流式响应（AgentToolSpec）
            if hasattr(tool_response, '__iter__') and not isinstance(tool_response, (str, bytes)):
                # 检查是否为专业agent工具
                tool_spec = tool_manager.get_tool(tool_name) if tool_manager else None
                is_agent_tool = isinstance(tool_spec, AgentToolSpec)

                # 处理流式响应
                logger.debug(f"{self.agent_name}: 收到流式工具响应，工具类型: {'专业Agent' if is_agent_tool else '普通工具'}")
                try:
                    for chunk in tool_response:
                        if is_agent_tool:
                            # 专业agent工具：直接返回原始结果，不做任何处理
                            if isinstance(chunk, list):
                                yield chunk
                            else:
                                yield [chunk]
                        else:
                            # 普通工具：添加必要的元数据
                            if isinstance(chunk, list):
                                # 转化成message chunk
                                message_chunks = []
                                for message in chunk:
                                    if isinstance(message, dict):
                                        message_chunks.append(MessageChunk(
                                            role=MessageRole.TOOL.value,
                                            content=message['content'],
                                            tool_call_id=tool_call['id'],
                                            message_id=str(uuid.uuid4()),
                                            message_type=MessageType.TOOL_CALL_RESULT.value,
                                            show_content=message['content']
                                        ))
                                yield message_chunks
                            else:
                                # 单个消息
                                if isinstance(chunk, dict):
                                    message_chunk_ = MessageChunk(
                                        role=MessageRole.TOOL.value,
                                        content=chunk['content'],
                                        tool_call_id=tool_call['id'],
                                        message_id=str(uuid.uuid4()),
                                        message_type=MessageType.TOOL_CALL_RESULT.value,
                                        show_content=chunk['content']
                                    )
                                    yield [message_chunk_]
                except Exception as e:
                    logger.error(f"{self.agent_name}: 处理流式工具响应时发生错误: {str(e)}")
                    async for chunk in self._handle_tool_error(tool_call['id'], tool_name, e):
                        yield chunk
            else:
                # 处理非流式响应
                logger.debug(f"{self.agent_name}: 收到非流式工具响应，正在处理")
                logger.info(f"{self.agent_name}: 工具响应 {tool_response}")
                processed_response = self.process_tool_response(tool_response, tool_call['id'])
                yield processed_response

        except Exception as e:
            logger.error(f"{self.agent_name}: 执行工具 {tool_name} 时发生错误: {str(e)}")
            logger.error(f"{self.agent_name}: 堆栈: {traceback.format_exc()}")
            async for chunk in self._handle_tool_error(tool_call['id'], tool_name, e):
                yield chunk

    async def _handle_tool_error(self, tool_call_id: str, tool_name: str, error: Exception) -> AsyncGenerator[List[MessageChunk], None]:
        """
        处理工具执行错误

        Args:
            tool_call_id: 工具调用ID
            tool_name: 工具名称
            error: 错误信息

        Yields:
            List[MessageChunk]: 错误消息块列表
        """
        error_message = f"工具 {tool_name} 执行失败: {str(error)}"
        logger.error(f"{self.agent_name}: {error_message}")

        error_chunk = MessageChunk(
            role='tool',
            content=json.dumps({"error": error_message}, ensure_ascii=False),
            tool_call_id=tool_call_id,
            message_id=str(uuid.uuid4()),
            message_type=MessageType.TOOL_CALL_RESULT.value,
            show_content=error_message
        )

        yield [error_chunk]

    def process_tool_response(self, tool_response: str, tool_call_id: str) -> List[MessageChunk]:
        """
        处理工具执行响应

        Args:
            tool_response: 工具执行响应
            tool_call_id: 工具调用ID

        Returns:
            List[MessageChunk]: 处理后的结果消息
        """
        logger.debug(f"{self.agent_name}: 处理工具响应，工具调用ID: {tool_call_id}")

        try:
            tool_response_dict = json.loads(tool_response)

            if "content" in tool_response_dict:
                result = [MessageChunk(
                    role=MessageRole.TOOL.value,
                    content=tool_response,
                    tool_call_id=tool_call_id,
                    message_id=str(uuid.uuid4()),
                    message_type=MessageType.TOOL_CALL_RESULT.value,
                    show_content='\\n```json\\n' + json.dumps(tool_response_dict['content'], ensure_ascii=False, indent=2) + '\\n```\\n'
                )]
            elif 'messages' in tool_response_dict:
                result = [MessageChunk(
                    role=MessageRole.TOOL.value,
                    content=msg,
                    tool_call_id=tool_call_id,
                    message_id=str(uuid.uuid4()),
                    message_type=MessageType.TOOL_CALL_RESULT.value,
                    show_content=msg
                ) for msg in tool_response_dict['messages']]
            else:
                # 默认处理
                result = [MessageChunk(
                    role=MessageRole.TOOL.value,
                    content=tool_response,
                    tool_call_id=tool_call_id,
                    message_id=str(uuid.uuid4()),
                    message_type=MessageType.TOOL_CALL_RESULT.value,
                    show_content='\\n' + tool_response + '\\n'
                )]

            logger.debug(f"{self.agent_name}: 工具响应处理成功")
            return result

        except json.JSONDecodeError:
            logger.warning(f"{self.agent_name}: 处理工具响应时JSON解码错误")
            return [MessageChunk(
                role='tool',
                content='\\n' + tool_response + '\\n',
                tool_call_id=tool_call_id,
                message_id=str(uuid.uuid4()),
                message_type=MessageType.TOOL_CALL_RESULT.value,
                show_content="工具调用失败\\n\\n"
            )]

    def merge_stream_response_to_non_stream_response(self, chunks):
        """
        将流式的chunk，进行合并成非流式的response
        """
        id_ = model_ = created_ = None
        content = ""
        tool_calls: dict[int, dict] = {}
        finish_reason = None
        usage = None

        for chk in chunks:
            if id_ is None:
                id_, model_, created_ = chk.id, chk.model, chk.created

            if chk.usage:  # 最后的 usage chunk
                usage = CompletionUsage(
                    prompt_tokens=chk.usage.prompt_tokens,
                    completion_tokens=chk.usage.completion_tokens,
                    total_tokens=chk.usage.total_tokens,
                )

            if not chk.choices:
                continue

            delta = chk.choices[0].delta
            finish_reason = chk.choices[0].finish_reason

            if delta.content:
                content += delta.content

            for tc in delta.tool_calls or []:
                idx = tc.index
                if idx not in tool_calls:
                    tool_calls[idx] = {
                        "id": tc.id or "",
                        "type": tc.type or "function",
                        "function": {"name": "", "arguments": ""},
                    }
                func = tool_calls[idx]["function"]
                func["name"] += tc.function.name or ""
                func["arguments"] += tc.function.arguments or ""
        if finish_reason is None:
            finish_reason = "stop"
        if id_ is None:
            id_ = "stream-merge-empty"
        if created_ is None:
            created_ = 0
        if model_ is None:
            model_ = "unknown"
        return ChatCompletion(
            id=id_,
            object="chat.completion",  # ← 关键修复
            created=created_,
            model=model_,
            choices=[
                Choice(
                    index=0,
                    message=ChatCompletionMessage(
                        role="assistant",
                        content=content or None,
                        tool_calls=(
                            [
                                ChatCompletionMessageToolCall(
                                    id=tc["id"],
                                    type="function",
                                    function=Function(
                                        name=tc["function"]["name"],
                                        arguments=tc["function"]["arguments"],
                                    ),
                                )
                                for tc in tool_calls.values()
                            ]
                            if tool_calls
                            else None
                        ),
                    ),
                    finish_reason=finish_reason,
                )
            ],
            usage=usage,
        )
