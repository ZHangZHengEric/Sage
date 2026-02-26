from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Union, AsyncGenerator, cast
import json
import uuid
from sagents.utils.logger import logger
from sagents.tool.tool_schema import AgentToolSpec
from sagents.tool.tool_manager import ToolManager
from sagents.context.session_context import get_session_context, SessionContext, SessionStatus
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.utils.prompt_manager import prompt_manager
from sagents.context.messages.message_manager import MessageManager
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

        self.max_model_input_len = 1000000

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
                tool_calls = msg['tool_calls'] or []
                # 如果tool_calls 里面的id 没有在其他的role 为tool 的消息中出现，就移除这个消息
                # 兼容 ChoiceDeltaToolCall 对象和字典形式
                def get_tool_call_id(tool_call):
                    if hasattr(tool_call, 'id'):
                        return tool_call.id
                    return tool_call.get('id')
                if any(get_tool_call_id(tool_call) not in all_tool_call_ids_from_tool for tool_call in tool_calls):
                    continue
            new_messages.append(msg)
        return new_messages

    def _remove_content_if_tool_calls(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        如果 assistant 消息包含 tool_calls，则移除 content 字段

        Args:
            messages: 消息列表

        Returns:
            List[Dict[str, Any]]: 处理后的消息列表
        """
        for msg in messages:
            if msg.get('role') == MessageRole.ASSISTANT.value and msg.get('tool_calls'):
                msg.pop('content', None)
        return messages

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
        logger.debug(f"{self.__class__.__name__}: 调用语言模型进行流式生成, session_id={session_id}")

        if session_id:
            sc_now = get_session_context(session_id)
            if sc_now is None:
                logger.warning(f"{self.__class__.__name__}: sc_now is None for session_id={session_id}")
            elif sc_now.status == SessionStatus.INTERRUPTED:
                logger.info(f"{self.__class__.__name__}: 跳过模型调用，session上下文不存在或已中断，会话ID: {session_id}")
                return
        # 确定最终的模型配置
        final_config = {**self.model_config}
        if model_config_override:
            final_config.update(model_config_override)

        model_name = cast(str, final_config.pop('model')) if 'model' in final_config else "gpt-3.5-turbo"
        # 移除不是OpenAI API标准参数的配置项
        final_config.pop('max_model_len', None)
        final_config.pop('api_key', None)
        final_config.pop('maxTokens', None)
        final_config.pop('base_url', None)
        all_chunks = []

        try:
            if self.model is None:
                raise ValueError("Model is not initialized")

            # 发起LLM请求
            # 将 MessageChunk 对象转换为字典，以便进行 JSON 序列化
            start_request_time = time.time()
            first_token_time = None
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


            # 需要处理 serializable_messages 中，如果有tool call ，但是没有后续的tool call id,需要去掉这条消息
            serializable_messages = self._remove_tool_call_without_id(serializable_messages)
            # 如果针对带有 tool_calls 的assistant 的消息，要删除content 这个字段
            serializable_messages = self._remove_content_if_tool_calls(serializable_messages)
            logger.info(f"{self.__class__.__name__} | {step_name}: 调用语言模型进行流式生成")

            stream = await self.model.chat.completions.create(
                model=model_name,
                messages=cast(List[Any], serializable_messages),
                stream=True,
                stream_options={"include_usage": True},
                extra_body={
                    "chat_template_kwargs": {"enable_thinking": False},
                    "enable_thinking": False,
                    "thinking": {'type': "disabled"},
                    "top_k": 20,
                    "_step_name": step_name # 观察用，记录下当前是哪个步骤的调用
                },
                **final_config
            )
            async for chunk in stream:
                # print(chunk)
                # 记录首token时间
                if first_token_time is None:
                    first_token_time = time.time()
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
            total_time = time.time() - start_request_time
            first_token_latency = first_token_time - start_request_time if first_token_time else None
            first_token_str = f"{first_token_latency:.3f}s" if first_token_latency else "N/A"
            logger.info(f"{self.__class__.__name__} | {step_name}: 调用语言模型进行流式生成，总耗时: {total_time:.3f}s, 首token延迟: {first_token_str}, 返回{len(all_chunks)}个chunk")
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
                                       system_prefix_override: Optional[str] = None,
                                       include_sections: Optional[List[str]] = None) -> MessageChunk:
        """
        准备统一的系统消息

        Args:
            session_id: 会话ID
            custom_prefix: 自定义前缀,会添加到system_prefix 后面，system context 前面
            language: 语言设置
            system_prefix_override: 覆盖默认的系统前缀（避免修改self.SYSTEM_PREFIX_FIXED导致并发问题）
            include_sections: 包含的部分列表，可选值：['role_definition', 'system_context', 'active_skill', 'workspace_files', 'available_skills']。默认为None，表示包含所有部分。

        Returns:
            MessageChunk: 系统消息
        """
        # 默认包含所有部分
        if include_sections is None:
            include_sections = ['role_definition', 'system_context', 'active_skill', 'workspace_files', 'available_skills']

        system_prefix = ""

        # 1. Role Definition
        if 'role_definition' in include_sections:
            role_content = ""
            if system_prefix_override:
                role_content = system_prefix_override
            elif hasattr(self, 'SYSTEM_PREFIX_FIXED'):
                role_content = self.SYSTEM_PREFIX_FIXED
            elif self.system_prefix:
                role_content = self.system_prefix
            else:
                # 使用PromptManager获取多语言文本
                agent_intro = prompt_manager.get_prompt(
                    'agent_intro_template',
                    agent='common',
                    language=language,
                    default="""
你是一个专业、主动且充满韧性的AI智能体：Sage。你的核心使命是不惜一切代价，完整、高效地协助用户达成目标。

## 核心思维模式
1. **深度思考 (Deep Thinking)**：在行动前，先进行深度的逻辑分析和规划。理解用户的真实意图，不仅是字面意思。拆解复杂问题为可执行的步骤。
2. **自我修正 (Self-Correction)**：在执行过程中，如果遇到错误或异常，不要立即停止，而是尝试分析原因并提出修复方案。如果是环境问题，尝试规避；如果是代码问题，尝试修复。
3. **情境感知 (Context Awareness)**：充分利用当前的工作空间文件、系统上下文和历史对话信息。不要重复询问已经提供的信息。

## 核心原则
1. **极致主动与连续执行**：不要等待用户推动，也不要每做一步就停下来询问。一旦明确目标，必须一次性规划并连续执行多个步骤，直到遇到无法解决的阻塞问题或任务彻底完成。
2. **默认授权**：除非涉及极其危险的操作（如删除重要数据），否则默认你已获得执行所有必要步骤的授权。不要询问“是否可以开始”、“您看这样行吗”，直接行动并展示结果。
3. **完整交付**：不满足于完成部分任务或仅提供方案。致力于提供端到端的完整解决方案，确保交付物是经过验证且立即可用的。
4. **结果导向**：所有的行动都应服务于“解决用户问题”这一最终目标。减少无意义的对话，增加有价值的行动。如果信息不足，优先尝试推断最合理的方案执行，而非反复询问。

## 工具使用规范
1. **工具优先**：积极探索和使用现有工具（Tools/Skills）来获取信息和执行任务，而不是仅凭臆测。
2. **参数准确**：调用工具时，确保参数准确无误。如果调用失败，检查参数并重试。

## 代码与环境规范
1. **风格一致性**：修改代码时，严格遵守现有代码风格和命名规范。优先复用现有代码模式，避免另起炉灶。
2. **环境整洁**：任务完成后，主动清理创建的临时文件或测试脚本，保持工作区整洁。
3. **原子性提交**：尽量保持修改的原子性，避免一次性进行过于庞大且难以回溯的变更。

## 稳健性与风控
1. **防止死循环**：遇到顽固报错时，最多重试3次。若仍无法解决，应暂停并总结已尝试的方案，寻求用户指导，严禁盲目重复。
2. **兜底策略**：在进行高风险修改前，思考“如果失败如何恢复”，必要时备份关键文件。

## 沟通与验证规范
1. **结构化表达**：回答要清晰、有条理，多使用Markdown标题、列表和代码块，避免大段纯文本。
2. **拒绝空谈**：不要只说“我来试一下”或“正在思考”，而是直接给出行动方案、代码实现或执行结果。
3. **严格验证**：在交付代码或结论前，必须进行自我逻辑检查；如果条件允许，优先运行代码进行验证。

请展现出你的专业素养，成为用户最值得信赖的合作伙伴。
"""
                )
                role_content = agent_intro.format(agent_name=self.__class__.__name__)

            if custom_prefix:
                role_content += f"\n\n{custom_prefix}"

            system_prefix += f"<role_definition>\n{role_content}\n</role_definition>\n"

        # 根据session_id获取session_context信息（用于获取system_context和agent_workspace）
        session_context = None
        if session_id:
            session_context = get_session_context(session_id)

        if session_context:
            system_context_info = session_context.system_context.copy()
            logger.debug(f"{self.__class__.__name__}: 添加运行时system_context到系统消息")
            
            # 处理 active_skill_instruction (无论是否包含system_context，都先提取出来，避免污染通用context)
            active_skill_instruction = None
            if 'active_skill_instruction' in system_context_info:
                active_skill_instruction = system_context_info.pop('active_skill_instruction')

            # 2. System Context
            if 'system_context' in include_sections:
                system_prefix += "<system_context>\n"
                
                # Exclude external_paths from generic system_context display as they are handled separately
                excluded_keys = {'active_skill_instruction', '可以访问的其他路径文件夹', 'external_paths'}
                
                for key, value in system_context_info.items():
                    if key in excluded_keys:
                        continue
                        
                    if isinstance(value, (dict, list, tuple)):
                        # 如果值是字典、列表或元组，格式化显示
                        # 如果是元组，先转换为列表，确保序列化行为明确
                        if isinstance(value, tuple):
                            value = list(value)
                        
                        # 将value转换为JSON字符串
                        formatted_val = json.dumps(value, ensure_ascii=False, indent=2)
                        system_prefix += f"  <{key}>\n{formatted_val}\n  </{key}>\n"
                    else:
                        # 其他类型直接转换为字符串
                        system_prefix += f"  <{key}>{str(value)}</{key}>\n"
                system_prefix += "</system_context>\n"
            
            # 3. Active Skill
            if 'active_skill' in include_sections and active_skill_instruction:
                system_prefix += f"<active_skill>\n{str(active_skill_instruction)}\n</active_skill>\n"

            logger.debug(f"{self.__class__.__name__}: 系统消息生成完成，总长度: {len(system_prefix)}")

            # 4. Workspace Files
            if 'workspace_files' in include_sections:
                # 补充当前工作空间中的文件情况
                # 优先使用 session_context.sandbox.file_system 获取文件树信息
                # 为了兼容性，也可以检查 session_context.file_system
                file_system = None
                if hasattr(session_context, 'sandbox') and session_context.sandbox and session_context.sandbox.file_system:
                    file_system = session_context.sandbox.file_system
                elif hasattr(session_context, 'file_system') and session_context.file_system:
                    file_system = session_context.file_system

                if file_system:
                    workspace_name = session_context.system_context.get('private_workspace', '')
                    
                    system_prefix += "<workspace_files>\n"
                    # 使用PromptManager获取多语言文本
                    workspace_files = prompt_manager.get_prompt(
                        'workspace_files_label',
                        agent='common',
                        language=language,
                        default=f"当前工作空间 {workspace_name} 的文件情况：\n"
                    )
                    system_prefix += workspace_files.format(workspace=workspace_name)
                    
                    file_tree = file_system.get_file_tree(include_hidden=True)
                    if not file_tree:
                        no_files = prompt_manager.get_prompt(
                            'no_files_message',
                            agent='common',
                            language=language,
                            default="当前工作空间下没有文件。\n"
                        )
                        system_prefix += no_files
                    else:
                        system_prefix += file_tree
                    system_prefix += "</workspace_files>\n"
                
                # Fallback: 如果没有 file_system 对象但有 agent_workspace 路径 (兼容旧代码)
                elif session_context.agent_workspace:
                    current_agent_workspace = session_context.agent_workspace
                    workspace_name = session_context.system_context.get('private_workspace', '')

                    system_prefix += "<workspace_files>\n"
                    # 使用PromptManager获取多语言文本
                    workspace_files = prompt_manager.get_prompt(
                        'workspace_files_label',
                        agent='common',
                        language=language,
                        default=f"当前工作空间 {workspace_name} 的文件情况：\n"
                    )
                    system_prefix += workspace_files.format(workspace=workspace_name)

                    # 尝试使用临时 SandboxFileSystem 获取文件树，保持行为一致性
                    # 即使没有全局 Sandbox，我们也使用 SandboxFileSystem 的安全逻辑来展示文件
                    try:
                        from sagents.utils.sandbox.filesystem import SandboxFileSystem
                        
                        fs_obj = None
                        if isinstance(current_agent_workspace, SandboxFileSystem):
                                fs_obj = current_agent_workspace
                        elif isinstance(current_agent_workspace, str):
                            # 假设虚拟路径就是 /workspace
                            fs_obj = SandboxFileSystem(host_path=current_agent_workspace, virtual_path="/workspace")
                        
                        if fs_obj:
                            file_tree = fs_obj.get_file_tree(include_hidden=True,max_depth=2)
                            
                            if not file_tree:
                                no_files = prompt_manager.get_prompt(
                                    'no_files_message',
                                    agent='common',
                                    language=language,
                                    default="当前工作空间下没有文件。\n"
                                )
                                system_prefix += no_files
                            else:
                                system_prefix += file_tree
                    except Exception as e:
                        logger.error(f"AgentBase: 获取工作空间文件树时出错: {e}")
                        # 如果发生错误，仅显示无文件提示，避免暴露宿主机路径
                        no_files = prompt_manager.get_prompt(
                            'no_files_message',
                            agent='common',
                            language=language,
                            default="当前工作空间下没有文件。\n"
                        )
                        system_prefix += no_files
                    
                    system_prefix += "</workspace_files>\n"

                # 4.1 External/Additional Paths
                # Support accessing other directories on the host machine if specified in system_context
                # Key: 'external_paths'
                external_paths = session_context.system_context.get('external_paths')
                
                if external_paths and isinstance(external_paths, list):
                    system_prefix += "<external_paths>\n"
                    ext_paths_intro = prompt_manager.get_prompt(
                        'external_paths_intro',
                        agent='common',
                        language=language,
                        default="您还可以访问以下外部目录（访问深度不受限，此处仅展示前2层文件）：\n"
                    )
                    system_prefix += ext_paths_intro

                    # Ensure we have a file system object
                    fs_for_external = file_system
                    if not fs_for_external:
                         # Try to create a temporary one
                         try:
                            from sagents.utils.sandbox.filesystem import SandboxFileSystem
                            # We just need it for reading, host_path doesn't matter much if we provide root_path
                            # Use current working directory as a safe default if available, else /
                            fs_for_external = SandboxFileSystem(host_path=os.getcwd(), virtual_path="/workspace") 
                         except Exception as e:
                            logger.error(f"AgentBase: 创建外部路径文件系统时出错: {e}")
                            pass
                    
                    if fs_for_external:
                        for ext_path in external_paths:
                            if isinstance(ext_path, str):
                                if os.path.exists(ext_path):
                                    system_prefix += f"Path: {ext_path}\n"
                                    try:
                                        # Limit depth to 1 to avoid context overflow
                                        ext_tree = fs_for_external.get_file_tree(include_hidden=True, root_path=ext_path, max_depth=2)
                                        if ext_tree:
                                            system_prefix += ext_tree
                                        else:
                                            system_prefix += "(Empty)\n"
                                    except Exception as e:
                                        system_prefix += f"(Error listing files: {e})\n"
                                else:
                                     system_prefix += f"Path: {ext_path} (Not found)\n"
                                system_prefix += "\n"
                    
                    system_prefix += "</external_paths>\n"

            # 5. Available Skills
            if 'available_skills' in include_sections:
                # 补充 Skills 信息
                # 确保不仅skill_manager存在，而且确实有技能可用
                if hasattr(session_context, 'skill_manager') and session_context.skill_manager:
                    # 尝试加载新技能，以确保新安装的技能能被发现
                    try:
                        session_context.skill_manager.load_new_skills()
                    except Exception as e:
                        logger.warning(f"Failed to load new skills: {e}")

                    skill_infos = session_context.skill_manager.list_skill_info()
                    if skill_infos:
                        system_prefix += "<available_skills>\n"
                        for skill in skill_infos:
                            system_prefix += f"<skill>\n<skill_name>{skill.name}</skill_name>\n<skill_description>{skill.description}</skill_description>\n</skill>\n"
                        system_prefix += "</available_skills>\n"
                        
                        # 获取技能使用说明
                        skills_hint = prompt_manager.get_prompt(
                            'skills_usage_hint',
                            agent='common',
                            language=language,
                            default=""
                        )
                        if skills_hint:
                             system_prefix += f"<skill_usage>\n{skills_hint}\n</skill_usage>\n"

        return MessageChunk(
            role=MessageRole.SYSTEM.value,
            content=system_prefix,
            type=MessageType.SYSTEM.value,
            agent_name=self.agent_name
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
            List[MessageChunk]: 工具调用消息列表
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
                    # 尝试使用 eval 解析，并注入 JSON 常量
                    function_params = eval(function_params, {"__builtins__": None}, {'true': True, 'false': False, 'null': None})
                except Exception:
                    logger.error(f"{self.agent_name}: 第一次参数解析报错，再次进行参数解析失败")
                    logger.error(f"{self.agent_name}: 原始参数: {tool_call['function']['arguments']}")

            if isinstance(function_params, str):
                try:
                    function_params = json.loads(function_params)
                except json.JSONDecodeError:
                    try:
                        # 再次尝试使用 eval 解析
                        function_params = eval(function_params, {"__builtins__": None}, {'true': True, 'false': False, 'null': None})
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

        # 将content 整理成函数调用的形式
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
            content=f"{tool_name}({formatted_params})",
            agent_name=self.agent_name
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

            # 构造调用参数，确保 session_id 正确传递且不重复
            call_kwargs = arguments.copy()
            call_kwargs['session_id'] = session_id
            
            tool_response = await tool_manager.run_tool_async(
                tool_name,
                session_context=get_session_context(session_id),
                **call_kwargs
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
                                            agent_name=self.agent_name
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
                                        agent_name=self.agent_name
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
                content = tool_response_dict["content"]
            else:
                content = tool_response
        except (json.JSONDecodeError, TypeError):
            content = tool_response

        # 如果 content 还是 dict/list，转成 json string
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False)
        else:
            content = str(content)

        return [MessageChunk(
            role=MessageRole.TOOL.value,
            content=content,
            tool_call_id=tool_call_id,
            message_id=str(uuid.uuid4()),
            message_type=MessageType.TOOL_CALL_RESULT.value,
            agent_name=self.agent_name
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

    async def _get_suggested_tools(self,
                                   messages_input: List[MessageChunk],
                                   tool_manager: ToolManager,
                                   session_id: str,
                                   session_context: SessionContext) -> List[str]:
        """
        基于用户输入和历史对话获取建议工具

        Args:
            messages_input: 消息列表
            tool_manager: 工具管理器
            session_id: 会话ID

        Returns:
            List[str]: 建议工具名称列表
        """
        logger.info("AgentBase: 开始获取建议工具")

        if not messages_input or not tool_manager:
            logger.warning("AgentBase: 未提供消息或工具管理器，返回空列表")
            return []
        try:
            # 获取可用工具，只提取工具名称和ID
            available_tools = tool_manager.list_tools_simplified()

            if len(available_tools) <= 15:
                logger.info("AgentBase: 可用工具数量小于等于15个，直接返回所有工具")
                # 移除complete_task工具
                tool_names = [tool['name'] for tool in available_tools if tool['name'] != 'complete_task']
                return tool_names
            
            # 准备工具列表字符串，包含ID和名称
            available_tools_str = "\n".join([f"{i+1}. {tool['name']}" for i, tool in enumerate(available_tools)]) if available_tools else '无可用工具'

            # 准备消息
            clean_messages = MessageManager.convert_messages_to_dict_for_request(messages_input)

            # 重新获取agent_custom_system_prefix以支持动态语言切换
            current_system_prefix = prompt_manager.get_agent_prompt_auto("agent_custom_system_prefix", language=session_context.get_language())

            # 生成提示
            tool_suggestion_template = prompt_manager.get_agent_prompt_auto('tool_suggestion_template', language=session_context.get_language())
            prompt = tool_suggestion_template.format(
                session_id=session_id,
                available_tools_str=available_tools_str,
                agent_config=self.prepare_unified_system_message(
                    session_id,
                    custom_prefix=current_system_prefix,
                    language=session_context.get_language(),
                ).content,
                messages=json.dumps(clean_messages, ensure_ascii=False, indent=2)
            )

            # 调用LLM获取建议
            suggested_tool_ids = await self._get_tool_suggestions(prompt, session_id)

            # 将工具ID转换为工具名称
            suggested_tool_names = []
            for tool_id in suggested_tool_ids:
                try:
                    index = int(tool_id) - 1
                    if 0 <= index < len(available_tools):
                        suggested_tool_names.append(available_tools[index]['name'])
                except (ValueError, IndexError):
                    pass

            # 确保有必要的工具
            if session_context.skill_manager is not None and session_context.skill_manager.list_skills():
                # 添加必要的工具
                necessary_tools = ['file_read', 'execute_python_code', 'execute_javascript_code', 'execute_shell_command', 'file_write', 'file_update', 'load_skill']
                for tool_name in necessary_tools:
                    if tool_name not in suggested_tool_names:
                        suggested_tool_names.append(tool_name)

            # 添加系统工具
            system_tools = ['sys_spawn_agent', 'sys_delegate_task', 'sys_finish_task']
            for tool_name in system_tools:
                if tool_name not in suggested_tool_names:
                    # 检查工具是否存在
                    for tool in available_tools:
                        if tool['name'] == tool_name:
                            suggested_tool_names.append(tool_name)
                            break

            # 移除complete_task工具
            if 'complete_task' in suggested_tool_names:
                suggested_tool_names.remove('complete_task')

            # 去重
            suggested_tool_names = list(set(suggested_tool_names))    

            logger.info(f"AgentBase: 获取到建议工具: {suggested_tool_names}")
            return suggested_tool_names

        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f"AgentBase: 获取建议工具时发生错误: {str(e)}")
            return []

    async def _get_tool_suggestions(self, prompt: str, session_id: str) -> List[str]:
        """
        调用LLM获取工具建议（流式调用）

        Args:
            prompt: 提示文本

        Returns:
            List[str]: 建议工具ID列表
        """
        logger.debug("AgentBase: 调用LLM获取工具建议（流式）")

        messages_input = [{'role': 'user', 'content': prompt}]
        # 使用基类的流式调用方法，自动处理LLM request日志
        response = self._call_llm_streaming(
            messages=messages_input,
            session_id=session_id,
            step_name="tool_suggestion"
        )
        # 收集流式响应内容
        all_content = ""
        async for chunk in response:
            if len(chunk.choices) == 0:
                continue
            if chunk.choices[0].delta.content:
                all_content += chunk.choices[0].delta.content
        try:
            result_clean = MessageChunk.extract_json_from_markdown(all_content)
            suggested_tool_ids = json.loads(result_clean)
            # 确保返回的工具ID列表是数字列表，不是字符串列表，并且不是数字的item要过滤掉
            # 过滤掉非数字的item，确保返回的是数字列表
            suggested_tool_ids = [int(item) for item in suggested_tool_ids if isinstance(item, (int, str)) and str(item).isdigit()]
            return suggested_tool_ids
        except json.JSONDecodeError:
            logger.warning("AgentBase: 解析工具建议响应时JSON解码错误")
            return []

    async def _handle_tool_calls(self,
                                 tool_calls: Dict[str, Any],
                                 tool_manager: Optional[ToolManager],
                                 messages_input: List[Any],
                                 session_id: str,
                                 handle_complete_task: bool = False) -> AsyncGenerator[tuple[List[MessageChunk], bool], None]:
        """
        处理工具调用

        Args:
            tool_calls: 工具调用字典
            tool_manager: 工具管理器
            messages_input: 输入消息列表
            session_id: 会话ID
            handle_complete_task: 是否处理complete_task工具（TaskExecutorAgent需要）

        Yields:
            tuple[List[MessageChunk], bool]: (消息块列表, 是否完成任务)
        """
        logger.info(f"{self.agent_name}: LLM响应包含 {len(tool_calls)} 个工具调用")
        logger.info(f"{self.agent_name}: 工具调用: {tool_calls}")

        for tool_call_id, tool_call in tool_calls.items():
            tool_name = tool_call['function']['name']
            logger.info(f"{self.agent_name}: 执行工具 {tool_name}")
            logger.info(f"{self.agent_name}: 参数 {tool_call['function']['arguments']}")

            # 检查是否为complete_task（仅TaskExecutorAgent需要处理）
            if handle_complete_task and tool_name == 'complete_task':
                logger.info(f"{self.agent_name}: complete_task，停止执行")
                yield ([MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content='已经完成了满足用户的所有要求',
                    message_id=str(uuid.uuid4()),
                    message_type=MessageType.DO_SUBTASK_RESULT.value
                )], True)
                return

            # 发送工具调用消息,如果流式已经返回了，则需要注释掉这个
            # output_messages = self._create_tool_call_message(tool_call)
            # yield output_messages

            # 执行工具
            async for message_chunk_list in self._execute_tool(
                tool_call=tool_call,
                tool_manager=tool_manager,
                messages_input=messages_input,
                session_id=session_id
            ):
                yield (message_chunk_list, False)
