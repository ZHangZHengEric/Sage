"""V1-compatible model-backed completion policies for the V2 runtime."""

from __future__ import annotations
from sagents.v2.model.recovery_scope import scoped_recovery, reserve_additional_request
from sagents.v2.contracts.errors import SageV2Error, RuntimeErrorInfo, ErrorCategory

from sagents.v2.context.plugins.summarizer_model.auxiliary import stream_auxiliary_model

import json
import re
from html import unescape
from typing import Any, Literal

from pydantic import Field

from sagents.v2.contracts.conversation import is_user_request
from sagents.v2.agent.policy.plugins._shared.continuation_rules import (
    QuestionnaireRule,
    BudgetRule,
    ResponseLimitRule,
    ExplicitStatusRule,
    FlowBoundaryRule,
    LoopRecoveryRule,
    InspectionProgressRule,
    LoopCorrectionRule,
    ToolOrTextRule,
    ToolOrTextRuleForPendingCalls,
)
from sagents.v2.agent.policy.continuation import (
    ContinuationAction,
    ContinuationContext,
    ContinuationDecision,
    InteractionDraft,
)
from sagents.v2.agent.policy.plugins.judge.prompts import LEGACY_V1_TASK_COMPLETE_TEMPLATE
from sagents.v2.contracts.common import StrictModel, new_id
from sagents.v2.contracts.items import (
    AudioBlock,
    FileBlock,
    ImageBlock,
    JsonBlock,
    ResourceRefBlock,
    TextBlock,
    UsageSummary,
)
from sagents.v2.model import ModelEventKind, ModelMessage, ModelProvider, ModelRequest
from sagents.v2.model.provider import (
    DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS,
    auxiliary_model_timeout_error,
)
from sagents.v2.i18n import recovery_payload, tr
from sagents.v2.prompt_i18n import prompt_language, prompt_text


_TOOL_RESULT_PREVIEW_CHARS = 500
_TODO_FIELD_MAX_CHARS = 300
_OPEN_TODO_ALLOWED_DECISIONS = frozenset({"continue", "need_user_input", "blocked"})


class JudgeVerdict(StrictModel):
    """The unchanged structured result requested by the V1 Judge prompt."""

    decision: Literal["continue", "completed", "need_user_input", "blocked"]
    reason: str = Field(default="", max_length=4_000)


class LLMContinuationJudge:
    """Run the V1 completion Judge contract through V2 model ports.

    The prompt, four decisions, legacy boolean parsing,
    and Todo invariant match V1. Invalid verdicts use bounded private repair. V2
    adapts the result into typed runtime actions and records model usage.
    """

    def __init__(
        self,
        model: ModelProvider,
        *,
        model_binding: str = "fast",
        timeout_seconds: float = DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self.model = model
        self.model_binding = model_binding
        self.timeout_seconds = float(timeout_seconds)

    @scoped_recovery
    async def decide(self, context: ContinuationContext) -> ContinuationDecision:
        judge_input, has_open_todo = self._judge_input(context)
        language = prompt_language(context.language)
        instructions = LEGACY_V1_TASK_COMPLETE_TEMPLATE[language].format(
            messages="<judge_input>The following user message contains the conversation and execution evidence to assess.</judge_input>"
        )
        request = ModelRequest(
            request_id=new_id("continuation_judge"),
            run_id=context.run_id,
            model_binding=self.model_binding,
            messages=(
                ModelMessage(role="system", content=(TextBlock(text=instructions),)),
                ModelMessage(role="user", content=(TextBlock(text=judge_input),)),
            ),
            response_format="json_object",
            metadata={
                "purpose": "continuation_judge",
                "implementation": "v1",
                "response_language": prompt_language(context.language),
            },
        )
        original = request
        usage = UsageSummary()
        from sagents.v2.model.recovery_scope import current_recovery_scope
        scope = current_recovery_scope()
        limit = scope.config.argument_repairs if scope else 2
        for attempt in range(limit + 1):
            completed = None
            async for event in stream_auxiliary_model(
                self.model, request, timeout_seconds=self.timeout_seconds,
                timeout_error=auxiliary_model_timeout_error(
                    code="agent.continuation.judge_timeout", operation="LLM continuation Judge",
                    timeout_seconds=self.timeout_seconds, plugin_id="sage.agent.continuation.llm-judge",
                ).info,
            ):
                if event.kind == ModelEventKind.COMPLETED:
                    completed = event.response
            reason = "Judge returned an invalid structured verdict"
            if completed is not None:
                usage = usage.model_copy(update={
                    "reported": usage.reported or completed.usage.reported,
                    "input_tokens": usage.input_tokens + completed.usage.input_tokens,
                    "output_tokens": usage.output_tokens + completed.usage.output_tokens,
                    "cached_input_tokens": usage.cached_input_tokens + completed.usage.cached_input_tokens,
                    "reasoning_tokens": usage.reasoning_tokens + completed.usage.reasoning_tokens,
                })
                try:
                    result = self._parse_json(completed.text.strip() or completed.reasoning.strip())
                except (TypeError, ValueError):
                    result = None
                if isinstance(result, dict) and not completed.tool_calls:
                    decision = self._decision(context, result, has_open_todo, usage)
                    if decision.reason_code != "judge.invalid_output":
                        return decision
                    reason = decision.reason
            error = RuntimeErrorInfo(code="model.structured_output_invalid", category=ErrorCategory.VALIDATION,
                message=reason, safe_to_resume=True, metadata={"usage": usage.model_dump(mode="json")})
            if completed is not None and scope is not None and scope.record_failed_usage is not None:
                await scope.record_failed_usage(completed.usage)
                # These failed verdicts are already durable usage; a later
                # successful decision must not count them a second time.
                usage = UsageSummary()
            if attempt == limit:
                raise SageV2Error(error)
            await reserve_additional_request("arguments", purpose="judge_schema", error=error)
            request = original.model_copy(update={"request_id": new_id("judge_repair"),
                "messages": (*original.messages, ModelMessage(role="user", content=(TextBlock(text=
                    'Return one JSON object with decision (continue, completed, need_user_input, or blocked) and reason. '
                    'Judge only the supplied evidence; do not execute the task or invent missing results.'),),
                    metadata={"inference_view_only": True, "runtime_continuation_guidance": True})),
            })
        raise AssertionError("unreachable Judge recovery state")

    def _prompt(self, context: ContinuationContext) -> tuple[str, bool]:
        judge_input, has_open_todo = self._judge_input(context)
        language = prompt_language(context.language)
        return LEGACY_V1_TASK_COMPLETE_TEMPLATE[language].format(
            messages=judge_input
        ), has_open_todo

    def _judge_input(self, context: ContinuationContext) -> tuple[str, bool]:
        language = prompt_language(context.language)
        messages = self._recent_request_trace(context.ledger)
        trace = self._format_messages(messages, language=language)
        todo_plan, has_open_todo = self._todo_plan(messages)
        if todo_plan:
            trace = f"{todo_plan}\n\n{trace}"
        judge_messages = (
            "<agent_system_requirements>\n"
            f"{prompt_text('judge_reference', language)}\n"
            f"{context.agent_system_requirements.strip()}\n"
            "</agent_system_requirements>\n\n"
            "<available_tools>\n"
            f"{json.dumps(list(context.available_tools), ensure_ascii=False)}\n"
            "</available_tools>\n\n"
            f"{trace}"
        )
        return judge_messages, has_open_todo

    @staticmethod
    def _recent_request_trace(
        messages: tuple[ModelMessage, ...],
    ) -> tuple[ModelMessage, ...]:
        last_user_index = None
        for index, message in enumerate(messages):
            if is_user_request(message):
                last_user_index = index
        selected = (
            messages[last_user_index:] if last_user_index is not None else messages
        )
        # Trace formatting retains the latest user turn and bounds display rows
        # by explicit characters; API feedback governs context recovery.
        return tuple(selected)

    @classmethod
    def _format_messages(
        cls, messages: tuple[ModelMessage, ...], *, language: str = "en"
    ) -> str:
        lines: list[str] = []
        tool_call_names: dict[str, str] = {}
        last_assistant_text_index = None
        for index, message in enumerate(messages):
            if (
                message.role == "assistant"
                and not message.tool_calls
                and cls._content_text(message, language=language).strip()
            ):
                last_assistant_text_index = index

        for index, message in enumerate(messages):
            if message.tool_calls:
                names = []
                for call in message.tool_calls:
                    names.append(call.name)
                    tool_call_names[call.tool_call_id] = call.name
                lines.append(
                    "assistant: ["
                    + prompt_text("judge_tools", language)
                    + " "
                    + ", ".join(names)
                    + "]"
                )
                continue
            if message.role == "tool":
                tool_name = tool_call_names.get(message.tool_call_id or "") or (
                    message.tool_call_id or "unknown"
                )
                preview = cls._content_text(message, language=language).strip()
                if len(preview) > _TOOL_RESULT_PREVIEW_CHARS:
                    preview = (
                        preview[:_TOOL_RESULT_PREVIEW_CHARS]
                        + "\n...["
                        + prompt_text("judge_tool_truncated", language)
                        + " "
                        + str(len(preview))
                        + "]"
                    )
                lines.append(
                    f"tool: [{prompt_text('judge_result', language, name=tool_name)}: {preview or prompt_text('judge_empty', language)}]"
                )
                continue
            text = cls._content_text(message, language=language).strip()
            if not text:
                continue
            if index != last_assistant_text_index and len(text) > 2_000:
                text = text[:2_000] + (
                    f"\n...[{prompt_text('judge_truncated', language)} {len(text)}]"
                )
            lines.append(f"{message.role}: {text}")
        return "\n\n".join(lines)

    @staticmethod
    def _content_text(message: ModelMessage, *, language: str = "en") -> str:
        parts: list[str] = []
        for block in message.content:
            if isinstance(block, TextBlock):
                parts.append(_redact_base64_data_urls(block.text))
            elif isinstance(block, JsonBlock):
                parts.append(
                    json.dumps(block.value, ensure_ascii=False, sort_keys=True)
                )
            elif isinstance(block, ImageBlock):
                parts.append(prompt_text("attachment_image", language))
            elif isinstance(block, AudioBlock):
                parts.append(prompt_text("attachment_audio", language))
            elif isinstance(block, FileBlock):
                parts.append(prompt_text("attachment_file", language))
            elif isinstance(block, ResourceRefBlock):
                parts.append(prompt_text("attachment_resource_ref", language))
        return "\n".join(parts)

    @classmethod
    def _todo_plan(cls, messages: tuple[ModelMessage, ...]) -> tuple[str, bool]:
        call_names = {
            call.tool_call_id: call.name
            for message in messages
            for call in message.tool_calls
        }
        latest_tasks: list[dict[str, Any]] | None = None
        for message in messages:
            if message.role != "tool":
                continue
            if call_names.get(message.tool_call_id or "") != "todo_write":
                continue
            payload = cls._content_payload(message)
            tasks = payload.get("tasks") if isinstance(payload, dict) else None
            if isinstance(tasks, list):
                latest_tasks = [value for value in tasks if isinstance(value, dict)]
        if not latest_tasks:
            return "", False
        if not any(cls._todo_status(value) != "completed" for value in latest_tasks):
            return "", False
        compact = []
        for task in latest_tasks:
            item = {
                "id": cls._bounded_todo_field(task.get("id")),
                "status": cls._todo_status(task),
                "content": cls._bounded_todo_field(
                    task.get("content") or task.get("name") or task.get("title")
                ),
            }
            conclusion = cls._bounded_todo_field(task.get("conclusion"))
            if conclusion:
                item["conclusion"] = conclusion
            compact.append(item)
        payload = {
            "source": "latest_todo_write_result",
            "authoritative": True,
            "tasks": compact,
        }
        return (
            "<current_todo_plan>\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
            + "\n</current_todo_plan>",
            True,
        )

    @classmethod
    def _content_payload(cls, message: ModelMessage) -> dict[str, Any] | None:
        for block in message.content:
            if isinstance(block, JsonBlock) and isinstance(block.value, dict):
                return block.value
        text = cls._content_text(message).strip()
        try:
            payload = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        nested = payload.get("content")
        if isinstance(nested, dict):
            return nested
        if isinstance(nested, str):
            try:
                decoded = json.loads(nested)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(decoded, dict):
                    return decoded
        return payload

    @staticmethod
    def _bounded_todo_field(value: Any) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) <= _TODO_FIELD_MAX_CHARS:
            return text
        return text[:_TODO_FIELD_MAX_CHARS].rstrip() + "... [truncated]"

    @staticmethod
    def _todo_status(task: dict[str, Any]) -> str:
        status = str(task.get("status") or "").strip().lower()
        if not status:
            status = "completed" if task.get("completed") is True else "pending"
        return status

    @staticmethod
    def _parse_json(value: str) -> object:
        text = value.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3 and lines[-1].strip() == "```":
                text = "\n".join(lines[1:-1])
                if text.lstrip().lower().startswith("json\n"):
                    text = text.lstrip()[5:]
        return json.loads(text)

    @classmethod
    def _decision(
        cls,
        context: ContinuationContext,
        result: dict[str, Any],
        has_open_todo: bool,
        usage: UsageSummary,
    ) -> ContinuationDecision:
        raw_decision = result.get("decision")
        decision = raw_decision.strip().lower() if isinstance(raw_decision, str) else ""
        reason = result.get("reason")
        reason = reason if isinstance(reason, str) else ""
        if not decision and "task_interrupted" in result:
            interrupted = cls._parse_legacy_boolean(result.get("task_interrupted"))
            interrupted = cls._normalize_legacy_interruption(reason, interrupted)
            decision = "completed" if interrupted else "continue"
        if decision not in {"continue", "completed", "need_user_input", "blocked"}:
            return cls._invalid("Judge returned an invalid decision", usage)
        if has_open_todo and decision not in _OPEN_TODO_ALLOWED_DECISIONS:
            decision = "continue"
            reason = "authoritative Todo still has pending/in_progress items"
        metadata = {"policy": "llm_judge", "implementation": "v1"}
        if decision == "continue":
            if context.step_number >= context.max_steps:
                return ContinuationDecision(
                    action=ContinuationAction.REQUEST_INTERACTION,
                    reason_code="budget.max_steps",
                    reason=tr("recovery.max_steps", context.language),
                    interaction=InteractionDraft(
                        interaction_type="loop_recovery",
                        allowed_decisions=("submit", "cancel"),
                        payload={
                            **recovery_payload(
                                "recovery.max_steps",
                                context.language,
                                reason_code="budget.max_steps",
                            ),
                            "reset_step_budget": True,
                        },
                    ),
                    usage=usage,
                    metadata=metadata,
                )
            return ContinuationDecision(
                action=ContinuationAction.CONTINUE_STEP,
                reason_code="judge.continue",
                reason=reason,
                usage=usage,
                metadata=metadata,
            )
        # A Judge verdict closes this conversational Run; approval and recovery
        # interactions retain a suspended execution that must be resumed.
        if not context.response.text.strip():
            return ContinuationDecision(
                action=ContinuationAction.CONTINUE_STEP,
                reason_code="judge.explanation_required",
                reason={
                    "completed": "Judge completion requires user-facing final text",
                    "need_user_input": "Judge need_user_input requires a user-facing question",
                    "blocked": "Judge blocked requires a user-facing explanation",
                }[decision],
                usage=usage,
                metadata=metadata,
            )
        return ContinuationDecision(
            action=ContinuationAction.COMPLETE_RUN,
            reason_code=f"judge.{decision}",
            reason=reason,
            usage=usage,
            metadata={
                **metadata,
                **({"completion_status": decision} if decision != "completed" else {}),
                **({"needs_user_input": True} if decision == "need_user_input" else {}),
            },
        )

    @staticmethod
    def _invalid(reason: str, usage: UsageSummary) -> ContinuationDecision:
        return ContinuationDecision(
            action=ContinuationAction.CONTINUE_STEP,
            reason_code="judge.invalid_output",
            reason=reason,
            usage=usage,
            metadata={
                "policy": "llm_judge",
                "implementation": "v1",
                "invalid_output": True,
            },
        )

    @staticmethod
    def _parse_legacy_boolean(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized == "true":
                return True
            if normalized == "false":
                return False
        return False

    @staticmethod
    def _normalize_legacy_interruption(reason: str, interrupted: bool) -> bool:
        lowered = reason.strip().lower()
        continue_markers = (
            "waiting for tool call",
            "waiting for generation",
            "waiting for tool",
            "missing execution evidence",
            "missing tool evidence",
            "no execution evidence",
            "no tool result",
            "等待工具调用",
            "等待生成",
            "处理中",
            "缺少执行证据",
            "没有执行证据",
            "缺少工具结果",
            "没有工具结果",
            "aguardando chamada de ferramenta",
            "aguardando geração",
            "sem evidência de execução",
            "sem resultado de ferramenta",
        )
        if any(value in lowered for value in continue_markers):
            return False
        user_markers = (
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
        )
        if any(value in lowered for value in user_markers):
            return True
        return interrupted


class LLMJudgeContinuationPolicy:
    """V1 Judge behavior with only V2 runtime safety boundaries retained."""

    plugin_id = "sage.agent.continuation.llm-judge"
    name = "No-tool-call LLM Judge completion policy"
    description = (
        "Uses a judge model to decide completion when no tool call is pending."
    )

    def __init__(self, judge: LLMContinuationJudge) -> None:
        self.judge = judge
        self._budget = BudgetRule()
        self._output_limit = ResponseLimitRule()
        self._flow = FlowBoundaryRule()
        self._pending_tools = ToolOrTextRuleForPendingCalls()
        self._tool_guards = (
            InspectionProgressRule(),
            LoopCorrectionRule(),
            LoopRecoveryRule(6),
        )

    async def decide(self, context: ContinuationContext) -> ContinuationDecision:
        questionnaire = await QuestionnaireRule().evaluate(context)
        if questionnaire is not None:
            return questionnaire
        if context.requested_interaction is not None:
            return ContinuationDecision(
                action=ContinuationAction.REQUEST_INTERACTION,
                reason_code="interaction.requested",
                reason=(
                    context.explicit_status_note
                    or str(context.requested_interaction.payload.get("title") or "")
                    or str(context.requested_interaction.payload.get("prompt") or "")
                    or "an explicit interaction requires user input"
                ),
                interaction=context.requested_interaction,
                metadata={
                    "policy": "llm_judge",
                    "implementation": "v1",
                    "response_language": prompt_language(context.language),
                    "source": "explicit_interaction",
                },
            )
        budget = await self._budget.evaluate(context)
        if budget is not None:
            return budget
        output_limit = await self._output_limit.evaluate(context)
        if output_limit is not None:
            return output_limit
        if context.response.tool_calls:
            for rule in self._tool_guards:
                decision = await rule.evaluate(context)
                if decision is not None:
                    return decision
            pending = await self._pending_tools.evaluate(context)
            assert pending is not None
            return pending
        flow = await self._flow.evaluate(context)
        if flow is not None:
            return flow
        protocol = _v1_protocol_decision(context)
        if protocol is not None:
            return protocol
        if (
            not context.validated_output_progress
            and _trailing_plain_assistant_responses(context.ledger) >= 3
        ):
            return ContinuationDecision(
                action=ContinuationAction.REQUEST_INTERACTION,
                reason_code="judge.plain_text_no_progress",
                reason=tr("recovery.plain_text", context.language),
                interaction=InteractionDraft(
                    interaction_type="loop_recovery",
                    allowed_decisions=("submit", "cancel"),
                    payload={
                        **recovery_payload(
                            "recovery.plain_text",
                            context.language,
                            reason_code="judge.plain_text_no_progress",
                        ),
                        "stop_reason": "plain_text_no_progress",
                    },
                ),
                metadata={"policy": "llm_judge", "implementation": "v1"},
            )
        return await self.judge.decide(context)


class HybridContinuationPolicy:
    """Use typed deterministic rules first and the V1 Judge for final text."""

    plugin_id = "sage.agent.continuation.hybrid"
    name = "Hybrid deterministic and LLM Judge policy"
    description = (
        "Combines deterministic safety rules with an LLM judge for completion."
    )

    def __init__(
        self,
        judge: LLMContinuationJudge,
        *,
        repeat_threshold: int = 3,
    ) -> None:
        self.judge = judge
        self._rules = (
            QuestionnaireRule(),
            BudgetRule(),
            ResponseLimitRule(),
            ExplicitStatusRule(),
            InspectionProgressRule(),
            LoopCorrectionRule(),
            LoopRecoveryRule(repeat_threshold),
            FlowBoundaryRule(),
        )
        self._fallback = ToolOrTextRule()

    async def decide(self, context: ContinuationContext) -> ContinuationDecision:
        for rule in self._rules:
            decision = await rule.evaluate(context)
            if decision is not None:
                return decision
        deterministic = await self._fallback.evaluate(context)
        if deterministic.reason_code != "text.final":
            return deterministic
        judged = await self.judge.decide(context)
        if judged.metadata.get("invalid_output"):
            raise SageV2Error(RuntimeErrorInfo(code="model.structured_output_invalid",
                category=ErrorCategory.VALIDATION, message="Judge returned an invalid verdict",
                safe_to_resume=True, metadata={"usage": judged.usage.model_dump(mode="json")}))
        return judged.model_copy(
            update={"metadata": {**judged.metadata, "policy": "hybrid"}}
        )


def _v1_protocol_decision(
    context: ContinuationContext,
) -> ContinuationDecision | None:
    text = context.response.text.strip()
    if _has_ling_action(text):
        return ContinuationDecision(
            action=ContinuationAction.COMPLETE_RUN,
            reason_code="judge.ling_action",
            reason="ling-action marks a closed reply awaiting an optional user action",
            metadata={"policy": "llm_judge", "implementation": "v1"},
        )
    if text.endswith((":", "：", "...")):
        return ContinuationDecision(
            action=ContinuationAction.CONTINUE_STEP,
            reason_code="judge.v1_must_continue",
            reason="assistant text ends with continuation punctuation",
            metadata={"policy": "llm_judge", "implementation": "v1"},
        )
    return None


def _has_ling_action(text: str) -> bool:
    for fragment in unescape(text).split("<")[1:]:
        raw_tag = fragment.split(">", 1)[0].strip()
        if not raw_tag or raw_tag[0] in "/!?":
            continue
        if raw_tag.split(None, 1)[0].rstrip("/").lower() == "ling-action":
            return True
    return False


def _trailing_plain_assistant_responses(
    messages: tuple[ModelMessage, ...],
) -> int:
    count = 0
    for message in reversed(messages):
        if message.metadata.get("runtime_continuation_guidance"):
            continue
        if message.role in {"user", "tool"}:
            break
        if message.role == "assistant":
            if message.tool_calls:
                break
            if LLMContinuationJudge._content_text(message).strip():
                count += 1
    return count


def _redact_base64_data_urls(value: str) -> str:
    return re.sub(
        r"data:[^;\s]+;base64,[A-Za-z0-9+/=_-]+",
        "[base64 data URL redacted]",
        value,
    )
