from abc import ABC, abstractmethod
from math import log
from tracemalloc import stop
from typing import List, Dict, Any, Optional, Generator, Union
import re,json
import uuid
import time
from httpx import request
from sagents.utils.logger import logger
from sagents.utils.stream_format import merge_stream_response_to_non_stream_response
from sagents.tool.tool_base import AgentToolSpec
from sagents.tool.tool_manager import ToolManager
from sagents.context.session_context import get_session_context, SessionContext
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
import traceback,os
from openai import OpenAI
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import Choice,ChoiceDelta

class AgentBase(ABC):
    """
    智能体基类
    
    为所有智能体提供通用功能和接口，包括消息处理、工具转换、
    流式处理和内容解析等核心功能。
    """

    def __init__(self, model: Optional[OpenAI] = None, model_config: Dict[str, Any] = {}, system_prefix: str = ""):
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
        
        logger.debug(f"AgentBase: 初始化 {self.__class__.__name__}，模型配置: {model_config}")
    
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

    @abstractmethod
    def run_stream(self, 
                   session_context: SessionContext, 
                   tool_manager: ToolManager = None,
                   session_id: str = None,
                   ) -> Generator[List[MessageChunk], None, None]:
        """
        流式处理消息的抽象方法
        
        Args:
            session_context: 会话上下文
            tool_manager: 可选的工具管理器
            session_id: 会话ID
            
        Yields:
            List[MessageChunk]: 流式输出的消息块
        """
        pass



    def _call_llm_streaming(self, messages: List[Union[MessageChunk, Dict[str, Any]]], session_id: Optional[str] = None, step_name: str = "llm_call", model_config_override: Optional[Dict[str, Any]] = None):
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
        
        # 确定最终的模型配置
        final_config = {**self.model_config}
        if model_config_override:
            final_config.update(model_config_override)
        all_chunks = []

        try:
            # 发起LLM请求
            # 将 MessageChunk 对象转换为字典，以便进行 JSON 序列化
            serializable_messages = []
            for msg in messages:
                if isinstance(msg, MessageChunk):
                    serializable_messages.append(msg.to_dict())
                else:
                    serializable_messages.append(msg)
            
            # 只保留model.chat.completions.create 需要的messages的key，移除掉不不要的
            serializable_messages = [{k: v for k, v in msg.items() if k in ['role', 'content', 'tool_calls','tool_call_id']} for msg in serializable_messages]
            # print("serializable_messages:",serializable_messages)
            # 确保所有的messages 中都包含role 和 content
            for msg in serializable_messages:
                if 'role' not in msg:
                    msg['role'] = MessageRole.USER.value
                if 'content' not in msg:
                    msg['content'] = ''


            logger.info(f"{self.__class__.__name__}: 调用语言模型进行流式生成，模型配置: {final_config}")
            stream = self.model.chat.completions.create(
                messages=serializable_messages,
                stream=True,
                stream_options={"include_usage": True},
                **final_config
            )
            # 直接yield chunks，不再收集用于日志记录
            for chunk in stream:
                # print(chunk)
                all_chunks.append(chunk)
                yield chunk

        except Exception as e:
            logger.error(f"{self.__class__.__name__}: LLM流式调用失败: {e}\n{traceback.format_exc()}")
            all_chunks.append( ChatCompletionChunk(
                id="",
                object="chat.completion.chunk",
                created=0,
                model="",
                choices=[
                    Choice(
                        index=0,
                        delta=ChoiceDelta(
                            content=traceback.format_exc(),
                            tool_calls=None,
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            ) )
            raise e
        finally:
            # 将次请求记录在session context 中的llm调用记录中
            if session_id:
                # 调用seesion manager 中获取llm logger，然后记录请求以及完整的响应
                session_context = get_session_context(session_id)

                llm_request = {
                    "step_name": step_name,
                    "model_config": final_config,
                    "messages": messages,
                }
                # 将流式的chunk，进行合并成非流式的response，保存下chunk所有的记录
                try:
                    llm_response =  merge_stream_response_to_non_stream_response(all_chunks)
                except:
                    print(all_chunks)
                    llm_response = None
                session_context.add_llm_request(llm_request,llm_response)

    def prepare_unified_system_message(self,
                                     session_id: Optional[str] = None,
                                     custom_prefix: Optional[str] = None) -> MessageChunk:
        """
        准备统一的系统消息
        
        Args:
            session_id: 会话ID
            custom_prefix: 自定义前缀,会添加到system_prefix 后面，system context 前面
            
        Returns:
            MessageChunk: 系统消息
        """
        system_prefix  = ""
        if hasattr(self, 'SYSTEM_PREFIX_FIXED'):
            system_prefix =  self.SYSTEM_PREFIX_FIXED
        else:
            if self.system_prefix:
                system_prefix = self.system_prefix
            else:
                system_prefix += f"\n你是一个{self.__class__.__name__}智能体。"
            
            if custom_prefix:
                system_prefix += custom_prefix +'\n'
        
        # 根据session_id获取session_context
        if session_id:
            session_context = get_session_context(session_id)
            system_context_info = session_context.system_context
            logger.debug(f"{self.__class__.__name__}: 添加运行时system_context到系统消息")
            system_prefix += f"\n补充上下文信息：\n "
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
                system_prefix += f"\n当前工作空间 {session_context.system_context['file_workspace']} 的文件情况：\n"
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
                                 tag_type: List[str] = None) -> str:
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

