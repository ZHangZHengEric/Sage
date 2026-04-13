from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, Optional, AsyncGenerator, Union, cast
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import SessionContext
from sagents.tool.tool_manager import ToolManager
from sagents.utils.prompt_manager import PromptManager
from sagents.utils.content_saver import save_agent_response_content
import json
import uuid
from copy import deepcopy
import re
import os
from sagents.utils.repeat_pattern import (
    build_loop_signature as _build_loop_signature_util,
    detect_repeat_pattern as _detect_repeat_pattern_util,
    build_self_correction_message as _build_self_correction_message_util,
)


def _get_system_prefix(tool_manager: Optional[ToolManager], language: str) -> str:
    """
    根据工具管理器中是否有 todo_write 工具来选择合适的 system prefix
    
    Args:
        tool_manager: 工具管理器
        language: 语言
        
    Returns:
        str: 合适的 system prefix 模板名称
    """
    tool_names = []
    if tool_manager:
        # 获取所有工具
        tool_names = tool_manager.list_all_tools_name()
        # tools_json = tool_manager.get_openai_tools(lang=language, fallback_chain=["en"])
        # tool_names = [tool['function']['name'] for tool in tools_json]
    
    # 如果有 todo_write 工具，使用完整版本
    if 'todo_write' in tool_names:
        return "agent_custom_system_prefix"
    
    # 没有 todo_write 工具，使用无任务管理版本
    return "agent_custom_system_prefix_no_task"


class SimpleAgent(AgentBase):
    """
    简单智能体

    负责无推理策略的直接任务执行，比ReAct策略更快速。
    适用于不需要推理或早期处理的任务。
    """

    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)

        # 循环模式触发阈值：连续命中后触发软纠偏/硬暂停
        self.max_repeat_pattern_hits = 2
        self.agent_name = "SimpleAgent"
        self.agent_description = """SimpleAgent: 简单智能体，负责无推理策略的直接任务执行，比ReAct策略更快速。适用于不需要推理或早期处理的任务。"""
        logger.debug("SimpleAgent 初始化完成")

    def _build_loop_signature(self, chunks: List[MessageChunk]) -> str:
        """
        为单轮输出构建签名（同时覆盖文本与工具调用/结果）。
        """
        return _build_loop_signature_util(chunks)

    def _detect_repeat_pattern(
        self,
        signatures: List[str],
        max_period: int = 8,
    ) -> Optional[Dict[str, int]]:
        """
        在最近签名序列中检测循环模式，支持:
        - AAAAAAA (period=1)
        - ABABAB / ABBABB (period=2/3)
        - AABBAABB (period=4)
        """
        return _detect_repeat_pattern_util(signatures, max_period=max_period)

    def _build_self_correction_message(self, pattern: Dict[str, int], language: str = 'zh') -> str:
        template = PromptManager().get_prompt(
            key='repeat_pattern_self_correction_template',
            agent='common',
            language=language,
            default=_build_self_correction_message_util(pattern),
        )
        try:
            return template.format(period=pattern['period'], cycles=pattern['cycles'])
        except Exception:
            return _build_self_correction_message_util(pattern)

    async def run_stream(
        self,
        session_context: SessionContext,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        if not session_context.tool_manager:
            raise ValueError("ToolManager is not initialized in SessionContext")
        session_id = session_context.session_id
        if self._should_abort_due_to_session(session_context):
            return
        tool_manager = session_context.tool_manager

        # 重新获取agent_custom_system_prefix以支持动态语言切换
        current_system_prefix = PromptManager().get_agent_prompt_auto(
            _get_system_prefix(tool_manager, session_context.get_language()), language=session_context.get_language()
        )

        # 从会话管理中，获取消息管理实例
        message_manager = session_context.message_manager
        # 从消息管理实例中，获取满足context 长度限制的消息
        history_messages = message_manager.extract_all_context_messages(recent_turns=20, last_turn_user_only=False)
        
        # 获取后续可能使用到的工具建议
        # 如果 audit_status 中有建议的工具，使用建议的工具；否则使用所有可用工具
        if tool_manager:
            suggested_tools = session_context.audit_status.get('suggested_tools', [])
            if not suggested_tools:
                # 使用所有可用工具名称列表
                try:
                    tools_list = tool_manager.list_tools_simplified()
                    suggested_tools = [t.get('name', '') for t in tools_list if t.get('name')]
                except Exception:
                    suggested_tools = []
        else:
            suggested_tools = []
        # 准备工具列表
        tools_json = self._prepare_tools(tool_manager, suggested_tools, session_context)
        # 将system 加入到到messages中
        system_message = await self.prepare_unified_system_message(
            session_id,
            custom_prefix=current_system_prefix,
            language=session_context.get_language(),
        )
        history_messages.insert(0, system_message)
        async for chunks in self._execute_loop(
            messages_input=history_messages,
            tools_json=tools_json,
            tool_manager=tool_manager,
            session_id=session_id or "",
            session_context=session_context
        ):
            for chunk in chunks:
                chunk.session_id = session_id
            yield chunks
    def _prepare_tools(self,
                       tool_manager: Optional[Any],
                       suggested_tools: List[str],
                       session_context: SessionContext) -> List[Dict[str, Any]]:
        """
        准备工具列表

        Args:
            tool_manager: 工具管理器
            suggested_tools: 建议工具列表
            session_context: 会话上下文

        Returns:
            List[Dict[str, Any]]: 工具配置列表
        """
        logger.debug("SimpleAgent: 准备工具列表")

        if not tool_manager or not suggested_tools:
            logger.warning("SimpleAgent: 未提供工具管理器或建议工具")
            return []

        # 获取所有工具
        tools_json = tool_manager.get_openai_tools(lang=session_context.get_language(), fallback_chain=["en"])

        # 根据建议过滤工具
        # 强制包含 todo 工具，如果它们存在于可用工具中
        always_include = ['todo_write','search_memory']
        
        tools_suggest_json = [
            tool for tool in tools_json
            if tool['function']['name'] in suggested_tools or tool['function']['name'] in always_include
        ]
        
        if tools_suggest_json:
            tools_json = tools_suggest_json

        tool_names = [tool['function']['name'] for tool in tools_json]
        logger.debug(f"SimpleAgent: 准备了 {len(tools_json)} 个工具: {tool_names}")

        return tools_json

    def _has_explicit_followup_intent(self, content: str) -> bool:
        text = (content or "").strip().lower()
        if not text:
            return False

        conditional_markers = [
            "如果你需要",
            "如需",
            "如果需要",
            "if you need",
            "if needed",
            "if you want",
        ]
        if any(marker in text for marker in conditional_markers):
            return False

        patterns = [
            r"接下来",
            r"下一步",
            r"现在让我",
            r"让我继续",
            r"我将继续",
            r"我会继续",
            r"接着",
            r"随后",
            r"然后我",
            r"我将(生成|整理|总结|分析|执行|补充|创建|处理)",
            r"我会(生成|整理|总结|分析|执行|补充|创建|处理)",
            r"继续(生成|整理|总结|分析|执行|处理)",
            r"请稍等",
            r"等待(工具调用|生成|处理)",
            r"\bnext\b",
            r"\bnext,? i('| wi)ll\b",
            r"\bi('| wi)ll now\b",
            r"\blet me\b",
            r"\bplease wait\b",
            r"\bcontinue (with|to|processing|analyzing|generating)\b",
        ]
        return any(re.search(pattern, text) for pattern in patterns)

    def _normalize_task_interrupted_decision(
        self,
        reason: str,
        task_interrupted: bool,
    ) -> bool:
        """根据 reason 做轻量一致性兜底，避免输出语义与布尔值矛盾。"""
        reason_text = (reason or "").strip().lower()
        if not reason_text:
            return task_interrupted

        wait_tool_markers = [
            "waiting for tool call",
            "waiting for generation",
            "waiting for tool",
            "等待工具调用",
            "等待生成",
            "处理中",
            "aguardando chamada de ferramenta",
            "aguardando geração",
        ]
        if any(marker in reason_text for marker in wait_tool_markers):
            return False

        wait_user_markers = [
            "waiting for user",
            "waiting user",
            "need user input",
            "need user confirmation",
            "awaiting user",
            "等待用户",
            "等待用户确认",
            "等待用户输入",
            "需要用户确认",
            "需要用户输入",
            "用户补充",
            "aguardando usuário",
            "aguardando confirmação",
            "entrada do usuário",
            "confirmação do usuário",
        ]
        if any(marker in reason_text for marker in wait_user_markers):
            return True

        return task_interrupted

    async def _must_continue_by_rules(self, messages_input: List[MessageChunk]) -> bool:
        """通过确定性规则判断是否必须继续执行

        返回 True 表示必须继续执行（task_interrupted = False）
        返回 False 表示未命中确定性规则，需要进入 LLM 判断

        这些规则基于客观事实，尽量保证误判率接近 0。
        """
        if not messages_input:
            return False

        last_message = messages_input[-1]

        # 规则1：最后一条消息是 tool 调用结果
        if last_message.role == 'tool':
            logger.debug("[SimpleAgent] must_continue 规则1命中：最后一条消息是 tool 结果，必须继续")
            return True

        # 规则2：最后一条消息是工具调用错误结果（如参数解析失败等）
        if last_message.matches_message_types([MessageType.DO_SUBTASK_RESULT.value]):
            content = last_message.content or ""
            if any(mark in content for mark in ["参数解析失败", "工具调用失败"]):
                logger.debug("[SimpleAgent] must_continue 规则2命中：工具调用失败，必须继续")
                return True

        # 规则3：最后一条 assistant 消息包含明确的处理中表达
        if last_message.role == MessageRole.ASSISTANT.value and (last_message.content or "").strip():
            content = last_message.content
            processing_keywords = [
                "等待工具调用",
                "等待生成",
                "请稍等",
                "正在处理",
                "正在调用",
                "正在执行",
                "处理中",
                "执行中",
            ]
            if any(keyword in content for keyword in processing_keywords):
                logger.debug("[SimpleAgent] must_continue 规则3命中：assistant 文本包含处理中关键词，必须继续")
                return True

            # 规则4：最后一个字符是表示还有后续内容的标点
            stripped = content.strip()
            if stripped:
                last_char = stripped[-1]
                continue_punctuations = [":", "："]
                # 省略号可以是单个字符，也可以是三个点
                if last_char in continue_punctuations or stripped.endswith("..."):
                    logger.debug("[SimpleAgent] must_continue 规则4命中：assistant 文本以继续标点结尾，必须继续")
                    return True

        return False

    async def _is_task_complete(self,
                                messages_input: List[MessageChunk],
                                session_id: str,
                                tool_manager: Optional[ToolManager],
                                session_context: SessionContext) -> bool:
        """判断任务是否应该中断（完成/等待用户）

        两层策略：
        1. 先用确定性规则判断是否必须继续执行；
        2. 如果没有命中规则，再调用 LLM 进行综合判断。
        """
        # 第一层：确定性规则
        if await self._must_continue_by_rules(messages_input):
            return False

        # 第二层：LLM 综合判断
        # 只提取最后一个 user 以及之后的 messages
        last_user_index = None
        for i, message in enumerate(messages_input):
            if message.is_user_input_message():
                last_user_index = i
        if last_user_index is not None:
            messages_for_complete = messages_input[last_user_index:]
        else:
            messages_for_complete = messages_input

        # 压缩消息，避免 token 超限
        budget = min(session_context.message_manager.context_budget_manager.budget_info.get('active_budget', 3000), 3000)
        messages_for_complete = MessageManager.compress_messages(messages_for_complete, budget)

        clean_messages = MessageManager.convert_messages_to_dict_for_request(messages_for_complete)

        task_complete_template = PromptManager().get_agent_prompt_auto('task_complete_template', language=session_context.get_language())
        system_msg = await self.prepare_unified_system_message(
            session_id,
            custom_prefix=PromptManager().get_agent_prompt_auto(
                _get_system_prefix(tool_manager, session_context.get_language()), language=session_context.get_language()
            ),
            language=session_context.get_language(),
        )
        prompt = task_complete_template.format(
            system_prompt=system_msg,
            messages=json.dumps(clean_messages, ensure_ascii=False, indent=2)
        )
        llm_input_messages: List[Dict[str, Any]] = [{'role': 'user', 'content': prompt}]

        response = self._call_llm_streaming(
            messages=cast(List[Union[MessageChunk, Dict[str, Any]]], llm_input_messages),
            session_id=session_id,
            step_name="task_complete_judge",
            enable_thinking=False,
            model_config_override={
                'model_type': 'fast',  # 使用快速模型
                'response_format': {'type': 'json_object'}  # 要求JSON返回
            }
        )

        all_content = ""
        async for chunk in response:
            if len(chunk.choices) == 0:
                continue
            if chunk.choices[0].delta.content:
                all_content += chunk.choices[0].delta.content

        try:
            result_clean = MessageChunk.extract_json_from_markdown(all_content)
            result = json.loads(result_clean)
            task_interrupted = bool(result.get('task_interrupted', False))
            reason = str(result.get('reason', ''))
            normalized = self._normalize_task_interrupted_decision(reason, task_interrupted)
            if normalized != task_interrupted:
                logger.warning(
                    f"SimpleAgent: 任务完成判断存在语义冲突，已自动修正。reason={reason}, "
                    f"task_interrupted={task_interrupted} -> {normalized}"
                )
            logger.info(f"SimpleAgent: 任务完成 LLM 判断结果: {result}, normalized={normalized}")
            return normalized
        except json.JSONDecodeError:
            logger.warning("SimpleAgent: 解析任务完成判断响应时JSON解码错误，默认继续执行")
            return False



    async def _execute_loop(self,
                            messages_input: List[MessageChunk],
                            tools_json: List[Dict[str, Any]],
                            tool_manager: Optional[ToolManager],
                            session_id: str,
                            session_context: SessionContext) -> AsyncGenerator[List[MessageChunk], None]:
        """
        执行主循环

        Args:
            messages_input: 输入消息列表
            tools_json: 工具配置列表
            tool_manager: 工具管理器
            session_id: 会话ID

        Yields:
            List[MessageChunk]: 执行结果消息块
        """

        if self._should_abort_due_to_session(session_context):
            return
        all_new_response_chunks: List[MessageChunk] = []
        loop_count = 0
        repeat_pattern_hits = 0
        # 从session context 获取 max_loop_count；缺失则直接报错，避免静默兜底
        max_loop_count = session_context.agent_config.get('max_loop_count')
        if max_loop_count is None:
            raise ValueError("SimpleAgent requires session_context.agent_config.max_loop_count")
        logger.info(f"SimpleAgent: 开始执行主循环，最大循环次数：{max_loop_count}")
        
        # 从 MessageManager 加载跨调用的签名历史，支持检测跨 SimpleAgent 调用的循环模式
        message_manager = session_context.message_manager
        recent_signatures: List[str] = message_manager.get_recent_loop_signatures()
        logger.debug(f"SimpleAgent: 加载历史签名 {len(recent_signatures)} 个")
        while True:
            if self._should_abort_due_to_session(session_context):
                break
            loop_count += 1
            logger.info(f"SimpleAgent: 循环计数: {loop_count}")

            if loop_count > max_loop_count:
                logger.warning(f"SimpleAgent: 循环次数超过 {max_loop_count}，终止循环")
                yield [MessageChunk(role=MessageRole.ASSISTANT.value, content=f"Agent执行次数超过最大循环次数：{max_loop_count}, 任务暂停，是否需要继续执行？", type=MessageType.ASSISTANT_TEXT.value)]
                break

            # 合并消息
            messages_input = MessageManager.merge_new_messages_to_old_messages(
                cast(List[Union[MessageChunk, Dict[str, Any]]], all_new_response_chunks),
                cast(List[Union[MessageChunk, Dict[str, Any]]], messages_input)
            )
            all_new_response_chunks = []
            current_system_prefix = PromptManager().get_agent_prompt_auto(_get_system_prefix(tool_manager, session_context.get_language()), language=session_context.get_language())

            # 更新system message，确保包含最新的子智能体列表等上下文信息
            if messages_input and messages_input[0].role == MessageRole.SYSTEM.value:
                system_message = await self.prepare_unified_system_message(
                    session_id,
                    custom_prefix=current_system_prefix,
                    language=session_context.get_language(),
                )
                messages_input[0] = system_message

            # 调用LLM
            should_break = False
            async for chunks, is_complete in self._call_llm_and_process_response(
                messages_input=messages_input,
                tools_json=tools_json,
                tool_manager=tool_manager,
                session_id=session_id
            ):
                non_empty_chunks = [c for c in chunks if (c.message_type != MessageType.EMPTY.value)]
                if len(non_empty_chunks) > 0:
                    all_new_response_chunks.extend(deepcopy(non_empty_chunks))
                yield chunks
                if is_complete:
                    should_break = True
                    break

            if should_break:
                break

            # 检查是否应该停止
            if self._should_stop_execution(all_new_response_chunks):
                logger.info("SimpleAgent: 检测到停止条件，终止执行")
                break

            # 检测循环模式：支持文本与工具调用/结果混合重复
            loop_signature = self._build_loop_signature(all_new_response_chunks)
            recent_signatures.append(loop_signature)
            # 同时保存到 MessageManager，支持跨 SimpleAgent 调用检测
            message_manager.add_loop_signature(loop_signature)
            if len(recent_signatures) > 24:
                recent_signatures = recent_signatures[-24:]

            pattern = self._detect_repeat_pattern(recent_signatures)
            if pattern:
                repeat_pattern_hits += 1
                correction_message = self._build_self_correction_message(
                    pattern,
                    language=session_context.get_language(),
                )
                logger.warning(
                    f"SimpleAgent: 检测到循环模式 period={pattern['period']} cycles={pattern['cycles']} "
                    f"(hit={repeat_pattern_hits}/{self.max_repeat_pattern_hits})"
                )

                # 通过过程 assistant 文本注入纠偏，而非修改 system prompt
                correction_chunk = MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content=correction_message,
                    type=MessageType.DO_SUBTASK_RESULT.value,
                    agent_name=self.agent_name,
                )
                all_new_response_chunks.append(correction_chunk)

                if repeat_pattern_hits >= self.max_repeat_pattern_hits:
                    yield [MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content=(
                            "检测到任务进入重复循环，且已尝试过程内纠偏仍未跳出。"
                            "已自动暂停，避免无效重复。请给我一个新的约束或允许我切换执行路径后继续。"
                        ),
                        type=MessageType.ASSISTANT_TEXT.value
                    )]
                    break
            else:
                repeat_pattern_hits = 0

            messages_input = MessageManager.merge_new_messages_to_old_messages(
                cast(List[Union[MessageChunk, Dict[str, Any]]], all_new_response_chunks),
                cast(List[Union[MessageChunk, Dict[str, Any]]], messages_input)
            )
            all_new_response_chunks = []

            if MessageManager.calculate_messages_token_length(cast(List[Union[MessageChunk, Dict[str, Any]]], messages_input)) > self.max_model_input_len:
                logger.warning(f"SimpleAgent: 消息长度超过 {self.max_model_input_len}，截断消息")
                # 任务暂停，返回一个超长的错误消息块
                yield [MessageChunk(role=MessageRole.ASSISTANT.value, content=f"消息长度超过最大长度：{self.max_model_input_len},是否需要继续执行？", type=MessageType.ERROR.value)]
                break
            if self._should_abort_due_to_session(session_context):
                break
            # 检查任务是否完成
            if await self._is_task_complete(messages_input, session_id, tool_manager, session_context):
                logger.info("SimpleAgent: 任务完成，终止执行")
                break


    async def _call_llm_and_process_response(self,
                                             messages_input: List[MessageChunk],
                                             tools_json: List[Dict[str, Any]],
                                             tool_manager: Optional[ToolManager],
                                             session_id: str
                                             ) -> AsyncGenerator[tuple[List[MessageChunk], bool], None]:

        # 准备消息：提取可用消息 -> 检查压缩 -> 执行压缩
        # 通过生成器获取中间结果（tool_calls/tool result）和最终结果
        prepared_messages = None
        async for messages_chunk, is_final in self._prepare_messages_for_llm(messages_input, session_id):
            if is_final:
                # 最终结果
                prepared_messages = messages_chunk
                break
            else:
                # 中间结果（tool_calls 或 tool result），yield 出去让上层处理
                yield (messages_chunk, False)

        if prepared_messages is None:
            logger.error("SimpleAgent: 准备消息失败，没有获得最终消息列表")
            return

        clean_message_input = MessageManager.convert_messages_to_dict_for_request(prepared_messages)
        logger.info(f"SimpleAgent: 准备了 {len(clean_message_input)} 条消息用于LLM")

        # 准备模型配置覆盖，包含工具信息
        model_config_override = {}

        if len(tools_json) > 0:
            model_config_override['tools'] = tools_json

        response = self._call_llm_streaming(
            messages=cast(List[Union[MessageChunk, Dict[str, Any]]], clean_message_input),
            session_id=session_id,
            step_name="direct_execution",
            model_config_override=model_config_override
        )

        tool_calls: Dict[str, Any] = {}
        reasoning_content_response_message_id = str(uuid.uuid4())
        content_response_message_id = str(uuid.uuid4())
        last_tool_call_id = None
        full_content_accumulator = ""
        tool_calls_messages_id = str(uuid.uuid4())
        # 处理流式响应块
        async for chunk in response:
            # print(chunk)
            if chunk is None:
                logger.warning(f"Received None chunk from LLM response, skipping... chunk: {chunk}")
                continue
            if chunk.choices is None:
                logger.warning(f"Received chunk with None choices from LLM response, skipping... chunk: {chunk}")
                continue
            if len(chunk.choices) == 0:
                continue
            
            # 由于 AgentBase._call_llm_streaming 已经处理了 asyncio.sleep(0) 的让权
            # 这里不需要重复让权，减少不必要的调度开销

            if chunk.choices[0].delta.tool_calls:
                self._handle_tool_calls_chunk(chunk, tool_calls, last_tool_call_id or "")
                # 更新last_tool_call_id
                for tool_call in chunk.choices[0].delta.tool_calls:
                    if tool_call.id is not None and len(tool_call.id) > 0:
                        last_tool_call_id = tool_call.id

                # 根据环境变量控制是否流式返回工具调用消息
                # 如果 SAGE_EMIT_TOOL_CALL_ON_COMPLETE=true，则参数完整时才返回工具调用消息
                emit_on_complete = os.environ.get("SAGE_EMIT_TOOL_CALL_ON_COMPLETE", "false").lower() == "true"
                if not emit_on_complete:
                    # 流式返回工具调用消息
                    output_messages = [MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        tool_calls=chunk.choices[0].delta.tool_calls,
                        message_id=tool_calls_messages_id,
                        message_type=MessageType.TOOL_CALL.value,
                        agent_name=self.agent_name
                    )]
                    yield (output_messages, False)
                else:
                    # yield 一个空的消息块以避免生成器卡住
                    output_messages = [MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content="",
                        message_id=content_response_message_id,
                        message_type=MessageType.EMPTY.value
                    )]
                    yield (output_messages, False)

            elif chunk.choices[0].delta.content:
                if len(chunk.choices[0].delta.content) > 0:
                    content_piece = chunk.choices[0].delta.content
                    full_content_accumulator += content_piece
                    output_messages = [MessageChunk(
                        role='assistant',
                        content=content_piece,
                        message_id=content_response_message_id,
                        message_type=MessageType.DO_SUBTASK_RESULT.value,
                        agent_name=self.agent_name
                    )]
                    yield (output_messages, False)
            else:
                # 先判断chunk.choices[0].delta 是否有reasoning_content 这个变量，并且不是none
                if hasattr(chunk.choices[0].delta, 'reasoning_content') and chunk.choices[0].delta.reasoning_content is not None:
                    output_messages = [MessageChunk(
                        role='assistant',
                        content=chunk.choices[0].delta.reasoning_content,
                        message_id=reasoning_content_response_message_id,
                        message_type=MessageType.REASONING_CONTENT.value,
                        agent_name=self.agent_name
                    )]
                    yield (output_messages, False)
        
        # 处理完所有chunk后，尝试保存内容
        if full_content_accumulator:
             try:
                 save_agent_response_content(full_content_accumulator, session_id)
             except Exception as e:
                 logger.error(f"SimpleAgent: Failed to save response content: {e}")

        # 处理工具调用
        if len(tool_calls) > 0:
            # 识别是否包含结束任务的工具调用
            termination_tool_ids = set()
            for tool_call_id, tool_call in tool_calls.items():
                if tool_call['function']['name'] in ['complete_task', 'sys_finish_task']:
                    termination_tool_ids.add(tool_call_id)

            # 根据环境变量控制 emit_tool_call_message
            # 如果 SAGE_EMIT_TOOL_CALL_ON_COMPLETE=true，则参数完整时才返回工具调用消息
            emit_on_complete = os.environ.get("SAGE_EMIT_TOOL_CALL_ON_COMPLETE", "false").lower() == "true"
            async for chunk in self._handle_tool_calls(
                tool_calls=tool_calls,
                tool_manager=tool_manager,
                messages_input=messages_input,
                session_id=session_id or "",
                emit_tool_call_message=emit_on_complete
            ):
                # chunk 是 (messages, is_complete)
                messages, is_complete = chunk
                
                # 如果当前消息块是结束任务工具的执行结果，则标记为完成
                if termination_tool_ids and not is_complete:
                    for msg in messages:
                        if msg.role == MessageRole.TOOL.value and msg.tool_call_id in termination_tool_ids:
                            logger.info(f"SimpleAgent: 检测到结束任务工具 {msg.tool_call_id} 执行完成，标记任务结束")
                            is_complete = True
                            break
                
                yield (messages, is_complete)

        else:
            # 发送换行消息（也包含usage信息）
            output_messages = [MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content='\n',
                message_id=content_response_message_id,
                message_type=MessageType.DO_SUBTASK_RESULT.value,
                agent_name=self.agent_name
            )]
            yield (output_messages, False)

    def _should_stop_execution(self, all_new_response_chunks: List[MessageChunk]) -> bool:
        """
        判断是否应该停止执行

        Args:
            all_new_response_chunks: 响应块列表

        Returns:
            bool: 是否应该停止执行
        """
        if len(all_new_response_chunks) < 10:
            logger.debug(f"SimpleAgent: 响应块: {all_new_response_chunks}")

        if len(all_new_response_chunks) == 0:
            logger.info("SimpleAgent: 没有更多响应块，停止执行")
            return True

        # 如果所有响应块都没有工具调用且没有内容，就停止执行
        if all(
            item.tool_calls is None and
            (item.content is None or item.content == '')
            for item in all_new_response_chunks
        ):
            logger.info("SimpleAgent: 没有更多响应块，停止执行")
            return True

        return False



    async def _compress_messages_with_tool(
        self,
        messages: List[MessageChunk],
        session_id: str
    ) -> AsyncGenerator[List[MessageChunk], None]:
        """
        使用 compress_conversation_history 工具压缩消息
        只 yield tool_calls 和 tool 结果，让上层处理消息列表

        Args:
            messages: 要压缩的消息列表
            session_id: 会话ID

        Yields:
            List[MessageChunk]: 消息列表
                - 首先 yield Assistant 的 tool_calls
                - 然后 yield Tool 的结果
        """
        try:
            # 生成唯一的 tool_call_id
            tool_call_id = f"auto_compress_{uuid.uuid4().hex[:8]}"

            # 1. 首先 yield Assistant 的 tool_calls
            assistant_tool_call = MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content="",
                tool_calls=[{
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": "compress_conversation_history",
                        "arguments": json.dumps({"session_id": session_id})
                    }
                }],
                type=MessageType.TOOL_CALL.value
            )
            logger.info("SimpleAgent: yield 压缩工具的 tool_calls")
            yield [assistant_tool_call]

            # 2. 调用压缩工具获取结果
            from sagents.tool.impl.compress_history_tool import CompressHistoryTool
            tool = CompressHistoryTool()
            result = await tool.compress_conversation_history(messages, session_id)

            # 3. yield Tool 的结果（无论成功或失败都返回）
            compression_result = MessageChunk(
                role=MessageRole.TOOL.value,
                content=result.get('message', ''),
                tool_call_id=tool_call_id,
                type=MessageType.TOOL_CALL_RESULT.value,
                metadata={
                    'tool_name': 'compress_conversation_history',
                    'auto_generated': True,
                    'status': result.get('status', 'unknown')
                }
            )
            if result.get('status') == 'success':
                logger.info("SimpleAgent: yield 压缩工具的 tool result")
            else:
                logger.warning(f"SimpleAgent: 工具压缩失败 - {result.get('message', '未知错误')}")
            yield [compression_result]

        except Exception as e:
            logger.error(f"SimpleAgent: 调用压缩工具失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # 即使异常也返回 tool result
            compression_result = MessageChunk(
                role=MessageRole.TOOL.value,
                content=f"压缩失败: {str(e)}",
                tool_call_id=tool_call_id,
                type=MessageType.TOOL_CALL_RESULT.value,
                metadata={
                    'tool_name': 'compress_conversation_history',
                    'auto_generated': True,
                    'status': 'error'
                }
            )
            yield [compression_result]

    async def _prepare_messages_for_llm(
        self,
        messages_input: List[MessageChunk],
        session_id: str
    ) -> AsyncGenerator[tuple[List[MessageChunk], bool], None]:
        """
        准备用于 LLM 的消息列表
        包括：提取可用消息 -> 检查是否需要压缩 -> 执行压缩 -> 必要时调用工具压缩

        通过 yield 返回中间结果（tool_calls 和 tool 结果）以及最终结果

        Args:
            messages_input: 输入消息列表
            session_id: 会话ID

        Yields:
            tuple[List[MessageChunk], bool]: (消息列表, 是否是最终结果)
                - 可能 yield 压缩工具的 tool_calls (is_final=False)
                - 可能 yield 压缩工具的 tool result (is_final=False)
                - 最后 yield 最终的消息列表 (is_final=True)
        """
        # 1. 提取可用消息（检测压缩工具）
        extracted_messages = MessageManager.extract_messages_for_inference(messages_input)
        logger.info(f"SimpleAgent: 提取后消息数量: {len(extracted_messages)}")

        # 2. 检查是否需要压缩
        max_model_len = self.model_config.get('max_model_len', 64000)
        max_new_tokens = self.model_config.get('max_tokens', 20000)
        should_compress, current_tokens, max_model_len = MessageManager.should_compress_messages(
            extracted_messages, max_model_len, max_new_tokens
        )

        if not should_compress:
            logger.info(f"SimpleAgent: 消息长度符合要求 ({current_tokens} tokens)，无需压缩")
            yield (extracted_messages, True)
            return

        # 3. 先尝试使用 compress_messages 进行压缩
        # 计算 system 消息的 token 长度
        system_messages = [m for m in extracted_messages if m.role == MessageRole.SYSTEM.value]
        system_tokens = MessageManager.calculate_messages_token_length(system_messages)
        # 压缩目标：max_model_len 减去 system 消息后，剩余部分的 30%
        budget_limit = int((max_model_len - system_tokens) * 0.3)
        compressed_messages = MessageManager.compress_messages(extracted_messages, budget_limit)
        new_tokens = MessageManager.calculate_messages_token_length(compressed_messages)

        logger.info(f"SimpleAgent: compress_messages 压缩后: {current_tokens} -> {new_tokens} tokens")

        # 4. 检查压缩后是否满足要求
        should_compress_after, _, _ = MessageManager.should_compress_messages(
            compressed_messages, max_model_len, max_new_tokens
        )

        if not should_compress_after:
            logger.info("SimpleAgent: compress_messages 压缩后满足要求")
            yield (compressed_messages, True)
            return

        # 5. 如果仍不满足，调用 compress_conversation_history 工具进行深度压缩
        # 目标与 compress_messages 一致：max_model_len 减去 system 消息后，剩余部分的 30%
        target_tokens = int((max_model_len - system_tokens) * 0.3)
        logger.info(f"SimpleAgent: compress_messages 压缩后仍不满足要求，调用工具进行深度压缩。当前: {new_tokens} tokens, 目标: <= {target_tokens} tokens (max_model_len: {max_model_len}, system_tokens: {system_tokens})")

        # 通过生成器获取工具调用的中间结果（tool_calls 和 tool result）
        tool_results = []
        async for messages_chunk in self._compress_messages_with_tool(compressed_messages, session_id):
            # 将 tool_calls 和 tool result 向上传递
            yield (messages_chunk, False)
            tool_results.extend(messages_chunk)

        # 将 tool 结果添加到压缩后的消息列表中
        messages_with_tool = compressed_messages + tool_results

        # 6. 重新提取（因为添加了压缩工具结果）
        final_messages = MessageManager.extract_messages_for_inference(messages_with_tool)
        final_tokens = MessageManager.calculate_messages_token_length(final_messages)
        logger.info(f"SimpleAgent: 最终消息数量: {len(final_messages)}, token数: {final_tokens}")
        yield (final_messages, True)
