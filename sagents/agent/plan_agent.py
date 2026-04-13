from __future__ import annotations

import json
import uuid
import os
from typing import Any, AsyncGenerator, Dict, List, Optional, Set, Union, cast

from sagents.agent.agent_base import AgentBase
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.context.session_context import SessionContext
from sagents.tool import ToolManager, ToolProxy
from sagents.utils.logger import logger
from sagents.utils.prompt_manager import PromptManager

PLAN_QUESTIONNAIRE_KIND_PLAN_INFORMATION = "plan_information"
PLAN_QUESTIONNAIRE_KIND_PLAN_CONFIRMATION = "plan_confirmation"

PLAN_READONLY_TOOLS = {
    "file_read",
    "search_memory",
    "fetch_webpages",
    "search_web",
    "questionnaire",
    "execute_shell_command",
}

PLAN_CONFIRMATION_QUESTION_IDS = {
    "decision",
    "feedback",
}

class PlanAgent(AgentBase):
    """
    执行前规划智能体。

    这版实现故意不走 SimpleAgent 的“通用执行循环”，而是更接近
    TaskAnalysisAgent / TaskCompletionJudgeAgent 这种“专用单职责 agent”：

    1. 自己决定 planning 阶段要使用什么 system prompt
    2. 自己决定 planning 阶段应该带哪些历史消息
    3. 自己执行一个工具驱动的 planning loop
    4. 允许模型自主调用 questionnaire
    5. 最终只写一个 flow 控制状态：plan_status

    这样做的目的，是尽量避免被执行期的上下文、通用 agent 的 system、以及
    SimpleAgent 大循环行为带偏。
    """

    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "PlanAgent"
        self.agent_description = "执行前规划智能体，负责调研、澄清、生成计划并确认是否执行"
        self._active_session_context: Optional[SessionContext] = None
        self._questionnaire_tool_call_ids: Set[str] = set()
        self._confirmation_tool_call_ids: Set[str] = set()
        self._questionnaire_kinds: Dict[str, str] = {}

    async def run_stream(self, session_context: SessionContext) -> AsyncGenerator[List[MessageChunk], None]:
        """
        PlanAgent 的主入口。

        整体过程：
        - 切换到 planning 专用工具集合
        - 提取一份更“干净”的 planning history
        - 用专用 system prompt 跑一个小循环
        - 在循环里允许模型自主调用 questionnaire
        - 如果识别到“最终计划确认问卷”，就把结果翻译成单一的 plan_status
        """
        session_id = session_context.session_id
        if self._should_abort_due_to_session(session_context):
            return

        original_tool_manager = session_context.tool_manager
        self._reset_runtime_state(session_context)

        if not original_tool_manager:
            logger.warning("PlanAgent: tool_manager is not available, skip planning phase")
            return

        plan_tool_manager = self._build_plan_tool_proxy(original_tool_manager)
        if not plan_tool_manager:
            logger.info("PlanAgent: no planning tools available, skip planning phase")
            return

        plan_tools = plan_tool_manager.get_openai_tools(
            lang=session_context.get_language(),
            fallback_chain=["en"],
        )
        working_messages = self._build_planning_history(session_context)

        try:
            session_context.tool_manager = plan_tool_manager

            loop_index = 0
            while True:
                if self._should_abort_due_to_session(session_context):
                    return

                loop_index += 1
                logger.info(f"PlanAgent: planning loop {loop_index}")
                llm_messages = await self._build_llm_request_messages(
                    session_context=session_context,
                    working_messages=working_messages,
                )

                made_progress = False
                tool_calls: Dict[str, Any] = {}
                last_tool_call_id = ""
                assistant_message_id = str(uuid.uuid4())
                tool_calls_messages_id = str(uuid.uuid4())
                content_response_message_id = str(uuid.uuid4())
                assistant_content_parts: List[str] = []

                async for llm_chunk in self._call_llm_streaming(
                    messages=llm_messages,
                    session_id=session_id,
                    step_name="plan_agent",
                    model_config_override={"tools": plan_tools} if plan_tools else {},
                    enable_thinking=False,
                ):
                    if not llm_chunk.choices:
                        continue

                    delta = llm_chunk.choices[0].delta

                    if delta.tool_calls:
                        made_progress = True
                        self._handle_tool_calls_chunk(llm_chunk, tool_calls, last_tool_call_id)
                        for tool_call in delta.tool_calls:
                            if tool_call.id:
                                last_tool_call_id = tool_call.id

                        # 根据环境变量控制是否流式返回工具调用消息
                        # 如果 SAGE_EMIT_TOOL_CALL_ON_COMPLETE=true，则参数完整时才返回工具调用消息
                        emit_on_complete = os.environ.get("SAGE_EMIT_TOOL_CALL_ON_COMPLETE", "false").lower() == "true"
                        if not emit_on_complete:
                            # 流式返回工具调用消息
                            output_messages = [MessageChunk(
                                role=MessageRole.ASSISTANT.value,
                                tool_calls=delta.tool_calls,
                                message_id=tool_calls_messages_id,
                                message_type=MessageType.TOOL_CALL.value,
                                agent_name=self.agent_name
                            )]
                            yield output_messages
                        else:
                            # yield 一个空的消息块以避免生成器卡住
                            output_messages = [MessageChunk(
                                role=MessageRole.ASSISTANT.value,
                                content="",
                                message_id=content_response_message_id,
                                message_type=MessageType.EMPTY.value
                            )]
                            yield output_messages

                    if delta.content:
                        made_progress = True
                        assistant_content_parts.append(delta.content)
                        assistant_chunk = MessageChunk(
                            role=MessageRole.ASSISTANT.value,
                            content=delta.content,
                            message_id=assistant_message_id,
                            message_type=MessageType.DO_SUBTASK_RESULT.value,
                            agent_name=self.agent_name,
                        )
                        yield [assistant_chunk]

                if assistant_content_parts:
                    working_messages.append(
                        MessageChunk(
                            role=MessageRole.ASSISTANT.value,
                            content="".join(assistant_content_parts),
                            message_id=assistant_message_id,
                            message_type=MessageType.DO_SUBTASK_RESULT.value,
                            agent_name=self.agent_name,
                        )
                    )

                if tool_calls:
                    async for tool_chunks in self._execute_tool_calls(
                        tool_calls=tool_calls,
                        tool_manager=plan_tool_manager,
                        session_id=session_id,
                        working_messages=working_messages,
                    ):
                        working_messages.extend(tool_chunks)
                        yield tool_chunks

                    if self._planning_resolved(session_context):
                        logger.info("PlanAgent: planning resolved after tool execution, stop loop")
                        break

                    # 这一轮已经发生工具调用，先进入下一轮，让 agent 基于最新工具结果继续自主推进。
                    continue

                judged_status = await self._judge_plan_status(
                    session_context=session_context,
                    working_messages=working_messages,
                    tool_manager=plan_tool_manager,
                )
                session_context.audit_status["plan_status"] = judged_status

                if judged_status == "continue_plan":
                    logger.info("PlanAgent: judge requested continue_plan, continue loop")
                    continue

                if self._planning_resolved(session_context):
                    logger.info(f"PlanAgent: planning resolved by judge with status={judged_status}, stop loop")
                    break

                if not made_progress:
                    logger.info("PlanAgent: no progress in this loop, stop loop")
                    break

            await self._finalize_state(
                session_context=session_context,
                working_messages=working_messages,
                tool_manager=plan_tool_manager,
            )
        finally:
            self._active_session_context = None
            session_context.tool_manager = original_tool_manager

    def _reset_runtime_state(self, session_context: SessionContext) -> None:
        """
        每次运行前清理内部状态。

        每轮 planning 都重新计算 plan_status，所以先清掉旧值。
        """
        self._active_session_context = session_context
        self._questionnaire_tool_call_ids.clear()
        self._confirmation_tool_call_ids.clear()
        self._questionnaire_kinds.clear()
        session_context.audit_status.pop("plan_status", None)

    def _build_plan_tool_proxy(
        self,
        current_manager: Optional[Union[ToolManager, ToolProxy]],
    ) -> Optional[ToolProxy]:
        """
        裁剪工具集合，只保留 planning 阶段允许的只读工具。
        """
        if current_manager is None:
            return None

        managers: List[ToolManager] = []
        currently_available: Set[str] = set()
        all_known_names: Set[str] = set()

        if isinstance(current_manager, ToolProxy):
            managers = current_manager.tool_managers
            currently_available = set(current_manager.list_all_tools_name())
            for manager in managers:
                all_known_names.update(manager.list_all_tools_name())
        elif isinstance(current_manager, ToolManager):
            managers = [current_manager]
            currently_available = set(current_manager.list_all_tools_name())
            all_known_names = set(currently_available)
        else:
            return None

        allowed = {name for name in currently_available if name in PLAN_READONLY_TOOLS}
        if "questionnaire" in all_known_names:
            allowed.add("questionnaire")

        if not allowed:
            return None

        return ToolProxy(managers, sorted(allowed))

    def _build_planning_history(self, session_context: SessionContext) -> List[MessageChunk]:
        """
        构造 planning 专用历史消息。

        这里故意不直接拿通用的“最近若干轮完整对话”，而是做一次收敛：
        - 保留最近几轮 user 输入
        - 保留少量 assistant 的收尾性消息
        - 保留 questionnaire 的 tool result
        - 尽量排除执行期的大量中间输出
        """
        message_manager = session_context.message_manager
        raw_messages = message_manager.extract_all_context_messages(
            recent_turns=6,
            last_turn_user_only=False,
            allowed_message_types=[
                MessageType.ASSISTANT_TEXT.value,
                MessageType.FINAL_ANSWER.value,
                MessageType.TOOL_CALL.value,
                MessageType.TOOL_CALL_RESULT.value,
            ],
        )

        filtered_messages: List[MessageChunk] = []
        for msg in raw_messages:
            if msg.role == MessageRole.USER.value:
                filtered_messages.append(msg)
                continue

            if msg.role == MessageRole.ASSISTANT.value:
                if msg.is_assistant_text_message():
                    filtered_messages.append(msg)
                continue

            if msg.role == MessageRole.TOOL.value:
                # planning 阶段最有价值的 tool result 主要是 questionnaire 的答案。
                tool_name = (msg.metadata or {}).get("tool_name")
                if tool_name == "questionnaire":
                    filtered_messages.append(msg)
                    continue
                # 兼容老数据：有些 tool result 没带 metadata，这里用内容特征兜一下。
                if isinstance(msg.content, str) and '"answers"' in msg.content:
                    filtered_messages.append(msg)

        budget_info = message_manager.context_budget_manager.budget_info
        if budget_info:
            filtered_messages = MessageManager.compress_messages(
                filtered_messages,
                min(budget_info.get("active_budget", 8000), 3500),
            )

        return filtered_messages

    async def _build_llm_request_messages(
        self,
        session_context: SessionContext,
        working_messages: List[MessageChunk],
    ) -> List[MessageChunk]:
        """
        构造本轮 planning 的 LLM 输入。

        这里刻意把 system sections 缩小到最小必需集，避免 planning prompt
        被 AGENT.MD、workspace 文件列表、技能描述等大块内容稀释。
        """
        planning_prefix = PromptManager().get_prompt(
            "plan_system_prefix",
            agent="PlanAgent",
            language=session_context.get_language(),
        )
        planning_prompt_suffix = self._build_planning_prompt_suffix(session_context)
        system_message = await self.prepare_unified_system_message(
            session_id=session_context.session_id,
            custom_prefix=f"{planning_prefix}\n\n{planning_prompt_suffix}" if planning_prompt_suffix else planning_prefix,
            language=session_context.get_language(),
            include_sections=["role_definition", "system_context"],
        )
        return [system_message] + working_messages

    def _build_planning_prompt_suffix(self, session_context: SessionContext) -> str:
        """
        给 planning prompt 增加少量运行时上下文。
        """
        parts: List[str] = []

        execution_mode = (
            session_context.audit_status.get("agent_mode")
            or session_context.agent_config.get("agent_mode")
            or "simple"
        )
        parts.append(f"后续正式执行模式：{execution_mode}")

        custom_sub_agents = (
            getattr(session_context, "custom_sub_agents", None)
            or session_context.agent_config.get("custom_sub_agents")
            or session_context.system_context.get("custom_sub_agents")
            or session_context.system_context.get("available_sub_agents")
            or []
        )
        if custom_sub_agents:
            lines = []
            seen_agent_keys = set()
            for agent_cfg in custom_sub_agents:
                if isinstance(agent_cfg, dict):
                    agent_id = agent_cfg.get("agent_id")
                    name = agent_cfg.get("name") or agent_id
                    description = agent_cfg.get("description", "")
                else:
                    agent_id = getattr(agent_cfg, "agent_id", None)
                    name = getattr(agent_cfg, "name", None) or agent_id
                    description = getattr(agent_cfg, "description", "")
                dedupe_key = agent_id or name
                if not dedupe_key or dedupe_key in seen_agent_keys:
                    continue
                seen_agent_keys.add(dedupe_key)
                if name:
                    lines.append(f"- {name}: {description}")
            if lines:
                parts.append("可用子智能体信息：\n" + "\n".join(lines))

        return "\n".join(parts)

    async def _execute_tool_calls(
        self,
        tool_calls: Dict[str, Any],
        tool_manager: Union[ToolManager, ToolProxy],
        session_id: str,
        working_messages: List[MessageChunk],
    ) -> AsyncGenerator[List[MessageChunk], None]:
        """
        执行本轮 LLM 产出的工具调用。

        这里直接复用 AgentBase 提供的标准工具消息生成与工具执行逻辑。
        """
        # 处理 questionnaire 工具的特殊逻辑
        for tool_call_id, tool_call in list(tool_calls.items()):
            if tool_call.get("function", {}).get("name") == "questionnaire":
                updated_tool_call = self._with_unique_questionnaire_session_id(tool_call, session_id, tool_call_id)
                self._register_questionnaire_call(tool_call_id, updated_tool_call)
                tool_calls[tool_call_id] = updated_tool_call

        # 根据环境变量控制 emit_tool_call_message
        # 如果 SAGE_EMIT_TOOL_CALL_ON_COMPLETE=true，则参数完整时才返回工具调用消息
        emit_on_complete = os.environ.get("SAGE_EMIT_TOOL_CALL_ON_COMPLETE", "false").lower() == "true"
        async for messages, _ in self._handle_tool_calls(
            tool_calls=tool_calls,
            tool_manager=tool_manager,
            messages_input=working_messages,
            session_id=session_id,
            emit_tool_call_message=emit_on_complete
        ):
            yield messages

    def _with_unique_questionnaire_session_id(
        self,
        tool_call: Dict[str, Any],
        session_id: str,
        tool_call_id: str,
    ) -> Dict[str, Any]:
        """
        为每一次 questionnaire 调用分配独立 questionnaire_id，避免同一会话内多次问卷互相串结果。
        """
        cloned_tool_call = json.loads(json.dumps(tool_call))
        function_payload = cloned_tool_call.get("function", {})
        arguments_raw = function_payload.get("arguments") or "{}"

        try:
            arguments = json.loads(arguments_raw)
        except Exception:
            logger.warning("PlanAgent: failed to parse questionnaire arguments for unique session id")
            return tool_call

        current_questionnaire_id = arguments.get("questionnaire_id")
        if isinstance(current_questionnaire_id, str) and "__questionnaire__" in current_questionnaire_id:
            if "questionnaire_kind" not in arguments:
                arguments["questionnaire_kind"] = (
                    PLAN_QUESTIONNAIRE_KIND_PLAN_CONFIRMATION
                    if self._is_plan_confirmation_questionnaire(arguments)
                    else PLAN_QUESTIONNAIRE_KIND_PLAN_INFORMATION
                )
                function_payload["arguments"] = json.dumps(arguments, ensure_ascii=False)
                cloned_tool_call["function"] = function_payload
            return cloned_tool_call

        arguments["questionnaire_id"] = f"{session_id}__questionnaire__{tool_call_id}"
        if "questionnaire_kind" not in arguments:
            arguments["questionnaire_kind"] = (
                PLAN_QUESTIONNAIRE_KIND_PLAN_CONFIRMATION
                if self._is_plan_confirmation_questionnaire(arguments)
                else PLAN_QUESTIONNAIRE_KIND_PLAN_INFORMATION
            )
        function_payload["arguments"] = json.dumps(arguments, ensure_ascii=False)
        cloned_tool_call["function"] = function_payload
        return cloned_tool_call

    def process_tool_response(self, tool_response: str, tool_call_id: str) -> List[MessageChunk]:
        """
        在标准工具结果处理基础上，额外识别“最终计划确认问卷”的返回值。
        """
        chunks = super().process_tool_response(tool_response, tool_call_id)

        for chunk in chunks:
            if chunk.role == MessageRole.TOOL.value:
                chunk.metadata = chunk.metadata or {}
                if tool_call_id in self._questionnaire_tool_call_ids:
                    chunk.metadata["tool_name"] = "questionnaire"

        session_context = self._active_session_context
        if session_context and tool_call_id in self._confirmation_tool_call_ids:
            confirmation = self._parse_plan_confirmation_result(tool_response)
            self._persist_plan_status(session_context, confirmation)

        return chunks

    def _register_questionnaire_call(self, tool_call_id: str, tool_call: Dict[str, Any]) -> None:
        """
        识别 questionnaire 调用，并判断它是否属于“最终计划确认问卷”。
        """
        self._questionnaire_tool_call_ids.add(tool_call_id)

        arguments_raw = tool_call.get("function", {}).get("arguments") or "{}"
        try:
            arguments = json.loads(arguments_raw)
        except Exception:
            logger.warning("PlanAgent: failed to parse questionnaire arguments for registration")
            return

        questionnaire_kind = arguments.get("questionnaire_kind")
        if questionnaire_kind not in {
            PLAN_QUESTIONNAIRE_KIND_PLAN_INFORMATION,
            PLAN_QUESTIONNAIRE_KIND_PLAN_CONFIRMATION,
        }:
            questionnaire_kind = (
                PLAN_QUESTIONNAIRE_KIND_PLAN_CONFIRMATION
                if self._is_plan_confirmation_questionnaire(arguments)
                else PLAN_QUESTIONNAIRE_KIND_PLAN_INFORMATION
            )

        self._questionnaire_kinds[tool_call_id] = questionnaire_kind
        if questionnaire_kind == PLAN_QUESTIONNAIRE_KIND_PLAN_CONFIRMATION:
            self._confirmation_tool_call_ids.add(tool_call_id)

    def _is_plan_confirmation_questionnaire(self, arguments: Dict[str, Any]) -> bool:
        """
        通过固定 question ids 识别“最终计划确认问卷”。
        """
        questions = arguments.get("questions")
        if not isinstance(questions, list):
            return False

        question_ids = {
            q.get("id")
            for q in questions
            if isinstance(q, dict) and isinstance(q.get("id"), str)
        }
        return PLAN_CONFIRMATION_QUESTION_IDS.issubset(question_ids)

    def _parse_plan_confirmation_result(self, raw_content: Any) -> Dict[str, Any]:
        """
        解析 questionnaire 返回的确认结果，并把它映射成唯一的 plan_status。
        """
        fallback = {
            "decision": "adjust_plan",
            "answers": {},
            "status": "failed",
            "feedback": "",
            "plan_status": "pause",
        }

        if not isinstance(raw_content, str) or not raw_content.strip():
            return fallback

        try:
            parsed = json.loads(raw_content)
        except Exception as e:
            logger.warning(f"PlanAgent: failed to parse plan confirmation result: {e}")
            return fallback

        # 工具层返回的常见格式是 {"content": "<json string>"}，这里先解包一层。
        if isinstance(parsed, dict) and "content" in parsed:
            inner_content = parsed.get("content")
            if isinstance(inner_content, str) and inner_content.strip():
                try:
                    parsed = json.loads(inner_content)
                except Exception as e:
                    logger.warning(f"PlanAgent: failed to parse inner plan confirmation content: {e}")
                    return fallback

        answers = parsed.get("answers") if isinstance(parsed.get("answers"), dict) else {}
        decision = answers.get("decision") or "adjust_plan"
        plan_status = "start_execution" if decision == "execute_plan" else "pause"

        return {
            "decision": decision,
            "answers": answers,
            "status": parsed.get("status") or "submitted",
            "feedback": answers.get("feedback", "") if isinstance(answers.get("feedback", ""), str) else "",
            "is_auto_submit": bool(parsed.get("is_auto_submit", False)),
            "plan_status": plan_status,
        }

    def _persist_plan_status(self, session_context: SessionContext, confirmation: Dict[str, Any]) -> None:
        """
        PlanAgent 只写一个主状态：plan_status。
        """
        session_context.audit_status["plan_status"] = confirmation.get("plan_status", "pause")

    def _planning_resolved(self, session_context: SessionContext) -> bool:
        """
        planning 是否已经到达一个可结束状态。
        """
        return session_context.audit_status.get("plan_status") in {"pause", "start_execution"}

    async def _judge_plan_status(
        self,
        session_context: SessionContext,
        working_messages: List[MessageChunk],
        tool_manager: Optional[Union[ToolManager, ToolProxy]],
    ) -> str:
        """
        在 planning 主循环结束后，用一次轻量 LLM 判断来收口。

        这里不依赖“有没有调用工具”这种容易被模型风格影响的规则，
        而是像 SimpleAgent 一样，让模型基于最近消息和 planning 规则，
        明确给出下一步应该是：
        - continue_plan
        - pause
        - start_execution
        """
        last_user_index = None
        for i, message in enumerate(working_messages):
            if message.is_user_input_message():
                last_user_index = i

        if last_user_index is not None:
            messages_for_judge = working_messages[last_user_index:]
        else:
            messages_for_judge = working_messages

        budget_info = session_context.message_manager.context_budget_manager.budget_info
        active_budget = 3000
        if budget_info:
            active_budget = min(budget_info.get("active_budget", 3000), 3000)
        messages_for_judge = MessageManager.compress_messages(messages_for_judge, active_budget)
        clean_messages = MessageManager.convert_messages_to_dict_for_request(messages_for_judge)

        system_msg = await self.prepare_unified_system_message(
            session_context.session_id,
            custom_prefix=PromptManager().get_prompt(
                "plan_system_prefix",
                agent="PlanAgent",
                language=session_context.get_language(),
            ),
            language=session_context.get_language(),
            include_sections=["role_definition", "system_context"],
        )
        judge_template = PromptManager().get_agent_prompt_auto(
            "plan_status_judge_template",
            language=session_context.get_language(),
        )
        prompt = judge_template.format(
            system_prompt=system_msg,
            messages=json.dumps(clean_messages, ensure_ascii=False, indent=2),
        )
        response = self._call_llm_streaming(
            messages=cast(List[Union[MessageChunk, Dict[str, Any]]], [{"role": "user", "content": prompt}]),
            session_id=session_context.session_id,
            step_name="plan_status_judge",
        )

        all_content = ""
        async for chunk in response:
            if not chunk.choices:
                continue
            if chunk.choices[0].delta.content:
                all_content += chunk.choices[0].delta.content

        try:
            result_clean = MessageChunk.extract_json_from_markdown(all_content)
            result = json.loads(result_clean)
            plan_status = result.get("plan_status")
            if plan_status in {"continue_plan", "pause", "start_execution"}:
                return plan_status
        except json.JSONDecodeError:
            logger.warning("PlanAgent: 解析 plan status judge 响应时 JSON 解码错误")

        if tool_manager and working_messages and working_messages[-1].role == MessageRole.TOOL.value:
            return "continue_plan"
        return "pause"

    async def _finalize_state(
        self,
        session_context: SessionContext,
        working_messages: List[MessageChunk],
        tool_manager: Optional[Union[ToolManager, ToolProxy]],
    ) -> None:
        """
        结束时做一次轻量校验。
        """
        if "plan_status" not in session_context.audit_status:
            session_context.audit_status["plan_status"] = await self._judge_plan_status(
                session_context=session_context,
                working_messages=working_messages,
                tool_manager=tool_manager,
            )
