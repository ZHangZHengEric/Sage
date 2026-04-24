from __future__ import annotations

import json
import uuid
import os
import posixpath
import re
import shlex
from typing import Any, AsyncGenerator, Dict, List, Optional, Set, Union, cast

from sagents.agent.agent_base import AgentBase
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.context.session_context import SessionContext
from sagents.tool import ToolProxy
from sagents.utils.logger import logger
from sagents.utils.prompt_manager import PromptManager

PLAN_ALLOWED_TOOLS = {
    "file_read",
    "file_write",
    "file_update",
    "search_memory",
    "fetch_webpages",
    "search_web",
    "questionnaire",
    "execute_shell_command",
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
        self._should_judge_after_tool_calls = False

    async def run_stream(self, session_context: SessionContext) -> AsyncGenerator[List[MessageChunk], None]:
        """
        PlanAgent 的主入口。

        整体过程：
        - 切换到 planning 专用工具集合
        - 提取一份更“干净”的 planning history
        - 用专用 system prompt 跑一个小循环
        - 在循环里允许模型自主调用 questionnaire
        - 所有问卷结果都保留在消息流里，最终状态交给 `_judge_plan_status` 收口
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

                    if self._should_judge_after_tool_calls:
                        self._should_judge_after_tool_calls = False
                        judged_status = await self._judge_plan_status(
                            session_context=session_context,
                            working_messages=working_messages,
                            tool_manager=plan_tool_manager,
                        )
                        session_context.audit_status["plan_status"] = judged_status
                        if judged_status == "continue_plan":
                            logger.info("PlanAgent: judge requested continue_plan after tool calls, continue loop")
                            continue
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

                if not made_progress:
                    logger.info("PlanAgent: no progress in this loop, stop loop")
                    break

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
        self._should_judge_after_tool_calls = False
        session_context.audit_status.pop("plan_status", None)

    def _build_plan_tool_proxy(
        self,
        current_manager: Optional[Any],
    ) -> Optional[Any]:
        """
        裁剪工具集合，只保留 planning 阶段允许的工具。

        PlanAgent 是固定能力阶段，不依赖 ToolSuggestionAgent 的推荐结果。
        这里按工具管理接口读取当前会话真实可用工具，再构造 planning 专用白名单。
        """
        if current_manager is None:
            return None

        observable_wrapper = None
        tool_source = current_manager
        base_manager = getattr(current_manager, "_tool_manager", None)
        if base_manager is not None:
            observable_wrapper = current_manager
            tool_source = base_manager

        def with_observability(tool_proxy: ToolProxy) -> Any:
            if observable_wrapper is None:
                return tool_proxy
            try:
                from sagents.observability.agent_runtime import ObservableToolManager

                return ObservableToolManager(
                    tool_proxy,
                    observable_wrapper.observability_manager,
                    observable_wrapper.session_id,
                )
            except Exception as e:
                logger.warning(f"PlanAgent: failed to restore observable tool wrapper: {e}")
                return tool_proxy

        if not all(
            hasattr(tool_source, method)
            for method in ("list_all_tools_name", "get_openai_tools", "run_tool_async")
        ):
            logger.warning(
                f"PlanAgent: tool manager does not provide required tool interface: {type(tool_source)}"
            )
            return None

        managers = list(getattr(tool_source, "tool_managers", []) or [tool_source])
        currently_available = set(tool_source.list_all_tools_name())
        all_known_names: Set[str] = set()
        for manager in managers:
            if hasattr(manager, "list_all_tools_name"):
                all_known_names.update(manager.list_all_tools_name())

        allowed = {name for name in currently_available if name in PLAN_ALLOWED_TOOLS}
        if "questionnaire" in all_known_names:
            allowed.add("questionnaire")

        if not allowed:
            logger.warning(
                "PlanAgent: planning tool intersection is empty, "
                f"current={sorted(currently_available)}, allowed={sorted(PLAN_ALLOWED_TOOLS)}, "
                f"known={sorted(all_known_names)}. Falling back to current tool manager."
            )
            return current_manager

        logger.info(
            "PlanAgent: planning tools resolved, "
            f"current={sorted(currently_available)}, allowed={sorted(allowed)}"
        )

        if not managers:
            return None

        return with_observability(ToolProxy(managers, sorted(allowed)))

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
        system_messages = await self.prepare_unified_system_messages(
            session_id=session_context.session_id,
            system_prefix_override=planning_prefix,
            language=session_context.get_language(),
            include_sections=["role_definition", "system_context"],
        )
        return list(system_messages) + working_messages

    async def _execute_tool_calls(
        self,
        tool_calls: Dict[str, Any],
        tool_manager: Any,
        session_id: str,
        working_messages: List[MessageChunk],
    ) -> AsyncGenerator[List[MessageChunk], None]:
        """
        执行本轮 LLM 产出的工具调用。

        这里直接复用 AgentBase 提供的标准工具消息生成与工具执行逻辑。
        """
        blocked_chunks: List[MessageChunk] = []

        # 处理 questionnaire 工具的特殊逻辑
        for tool_call_id, tool_call in list(tool_calls.items()):
            tool_name = tool_call.get("function", {}).get("name")
            block_reason = self._get_blocked_plan_tool_reason(tool_call)
            if block_reason:
                blocked_chunks.append(self._build_blocked_tool_result(tool_call_id, tool_name, block_reason))
                del tool_calls[tool_call_id]
                continue

            if tool_name in {"file_write", "file_update"}:
                self._record_plan_document_path(arguments=self._parse_tool_arguments(tool_call))

            if tool_name == "questionnaire":
                arguments = self._parse_tool_arguments(tool_call)
                if arguments.get("questionnaire_kind") == "plan_confirmation":
                    self._should_judge_after_tool_calls = True
                updated_tool_call = self._with_unique_questionnaire_session_id(tool_call, session_id, tool_call_id)
                self._register_questionnaire_call(tool_call_id, updated_tool_call)
                tool_calls[tool_call_id] = updated_tool_call

        if blocked_chunks:
            yield blocked_chunks

        if not tool_calls:
            return

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

    def _get_blocked_plan_tool_reason(self, tool_call: Dict[str, Any]) -> Optional[str]:
        tool_name = tool_call.get("function", {}).get("name")
        arguments = self._parse_tool_arguments(tool_call)

        if tool_name == "execute_shell_command":
            command = str(arguments.get("command") or "")
            if not self._is_readonly_shell_command(command):
                return (
                    "Planning phase only allows read-only shell probes. "
                    "Do not create, modify, install, run builds, or execute project code before plan confirmation."
                )

        if tool_name in {"file_write", "file_update"}:
            file_path = str(arguments.get("file_path") or arguments.get("path") or "")
            if not self._is_plan_document_path(file_path):
                return (
                    "Planning phase may only write or update the plan document at "
                    "plans/<task_title_slug>_plan.md. Do not create implementation artifacts before confirmation."
                )

        return None

    def _parse_tool_arguments(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        arguments_raw = tool_call.get("function", {}).get("arguments") or "{}"
        try:
            parsed = json.loads(arguments_raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _build_blocked_tool_result(
        self,
        tool_call_id: str,
        tool_name: Optional[str],
        reason: str,
    ) -> MessageChunk:
        return MessageChunk(
            role=MessageRole.TOOL.value,
            content=json.dumps(
                {
                    "status": "blocked",
                    "reason": reason,
                    "next_action": "Continue planning, write/update the plan document, or ask a planning questionnaire.",
                },
                ensure_ascii=False,
            ),
            tool_call_id=tool_call_id,
            message_type=MessageType.TOOL_CALL_RESULT.value,
            agent_name=self.agent_name,
            metadata={"tool_name": tool_name or "unknown", "blocked_by": "plan_agent"},
        )

    def _is_plan_document_path(self, file_path: str) -> bool:
        if not file_path:
            return False

        normalized = posixpath.normpath(file_path.replace("\\", "/"))
        parts = [part for part in normalized.split("/") if part]
        if len(parts) < 2:
            return False

        filename = parts[-1]
        return parts[-2] == "plans" and filename.endswith("_plan.md")

    def _record_plan_document_path(self, arguments: Dict[str, Any]) -> None:
        session_context = self._active_session_context
        if session_context is None:
            return

        raw_path = str(arguments.get("file_path") or arguments.get("path") or "").strip()
        if not raw_path or not self._is_plan_document_path(raw_path):
            return

        normalized_path = raw_path.replace("\\", "/")
        if not normalized_path.startswith("/"):
            workspace = session_context.sandbox_agent_workspace or session_context.system_context.get("private_workspace")
            if workspace:
                normalized_path = posixpath.normpath(posixpath.join(str(workspace).replace("\\", "/"), normalized_path))

        session_context.system_context["plan_document_path"] = normalized_path
        session_context.system_context["plan_document_instruction"] = (
            "Before formal execution, read this Markdown plan document first and keep execution aligned with it. "
            "If execution intentionally changes direction, update the same plan document instead of creating a new one."
        )

    def _is_readonly_shell_command(self, command: str) -> bool:
        if not command.strip():
            return False

        if re.search(r"(^|[\s;&|])(?:mkdir|touch|rm|rmdir|mv|cp|chmod|chown|install|npm|pnpm|yarn|pip|python|python3|node|uv|cargo|go|make)\b", command):
            return False
        if re.search(r">|>>|\btee\b|\bsed\s+-i\b", command):
            return False

        try:
            tokens = shlex.split(command)
        except ValueError:
            return False
        if not tokens:
            return False

        executable = tokens[0]
        readonly_commands = {"ls", "pwd", "find", "rg", "grep", "cat", "sed", "head", "tail", "wc", "tree"}
        if executable in readonly_commands:
            return True
        if executable == "git":
            return len(tokens) >= 2 and tokens[1] in {"status", "log", "diff", "show", "branch", "ls-files", "grep"}
        return False

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
        if isinstance(current_questionnaire_id, str) and current_questionnaire_id.strip():
            return cloned_tool_call

        arguments["questionnaire_id"] = f"{session_id}__questionnaire__{tool_call_id}"
        function_payload["arguments"] = json.dumps(arguments, ensure_ascii=False)
        cloned_tool_call["function"] = function_payload
        return cloned_tool_call

    def process_tool_response(self, tool_response: str, tool_call_id: str) -> List[MessageChunk]:
        """
        在标准工具结果处理基础上，把 questionnaire 的结果标记回 planning 历史。
        """
        chunks = super().process_tool_response(tool_response, tool_call_id)

        for chunk in chunks:
            if chunk.role == MessageRole.TOOL.value:
                chunk.metadata = chunk.metadata or {}
                if tool_call_id in self._questionnaire_tool_call_ids:
                    chunk.metadata["tool_name"] = "questionnaire"

        return chunks

    def _register_questionnaire_call(self, tool_call_id: str, tool_call: Dict[str, Any]) -> None:
        """
        识别 questionnaire 调用，确保工具结果能回到 planning 历史里。
        """
        self._questionnaire_tool_call_ids.add(tool_call_id)

    async def _judge_plan_status(
        self,
        session_context: SessionContext,
        working_messages: List[MessageChunk],
        tool_manager: Optional[Any],
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
            system_prefix_override=PromptManager().get_prompt(
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
            system_prompt=system_msg.content,
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
