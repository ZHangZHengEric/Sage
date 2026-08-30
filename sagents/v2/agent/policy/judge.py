"""V1-compatible model-backed completion policies for the V2 runtime."""

from __future__ import annotations

import asyncio
import json
import re
from html import unescape
from typing import Any, Literal

from pydantic import Field

from sagents.v2.agent.policy.continuation import (
    BudgetRule,
    ContinuationAction,
    ContinuationContext,
    ContinuationDecision,
    ExplicitStatusRule,
    FlowBoundaryRule,
    InteractionDraft,
    LoopRecoveryRule,
    ToolOrTextRule,
    ToolOrTextRuleForPendingCalls,
)
from sagents.v2.agent.policy.legacy_v1_judge_prompt import (
    LEGACY_V1_TASK_COMPLETE_TEMPLATE,
)
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
from sagents.v2.i18n import recovery_payload, tr


_TOOL_RESULT_PREVIEW_CHARS = 500
_TODO_FIELD_MAX_CHARS = 300
_OPEN_TODO_ALLOWED_DECISIONS = frozenset({"continue", "need_user_input", "blocked"})
_V1_LANGUAGES = frozenset(LEGACY_V1_TASK_COMPLETE_TEMPLATE)


class JudgeVerdict(StrictModel):
    """The unchanged structured result requested by the V1 Judge prompt."""

    decision: Literal["continue", "completed", "need_user_input", "blocked"]
    reason: str = Field(default="", max_length=4_000)


class LLMContinuationJudge:
    """Run the V1 completion Judge contract through V2 model ports.

    The prompt, one-request behavior, four decisions, legacy boolean parsing,
    Todo invariant, and invalid-output fallback intentionally match V1. V2 only
    adapts the result into typed runtime actions and records model usage.
    """

    def __init__(
        self,
        model: ModelProvider,
        *,
        model_binding: str = "fast",
    ) -> None:
        self.model = model
        self.model_binding = model_binding

    async def decide(self, context: ContinuationContext) -> ContinuationDecision:
        prompt, has_open_todo = self._prompt(context)
        request = ModelRequest(
            request_id=new_id("continuation_judge"),
            run_id=context.run_id,
            model_binding=self.model_binding,
            messages=(ModelMessage(role="user", content=(TextBlock(text=prompt),)),),
            response_format="json_object",
            metadata={
                "purpose": "continuation_judge",
                "implementation": "v1",
            },
        )
        completed = None
        async for event in self.model.stream(request):
            if event.kind == ModelEventKind.COMPLETED:
                completed = event.response
        if completed is None:
            return self._invalid(
                "Judge stream ended without a completed response", UsageSummary()
            )
        if completed.tool_calls:
            return self._invalid(
                "completion Judge attempted to call a Tool", completed.usage
            )
        judge_output = completed.text.strip() or completed.reasoning.strip()
        if not judge_output:
            return self._invalid(
                "completion Judge returned an empty response", completed.usage
            )
        try:
            result = self._parse_json(judge_output)
        except (TypeError, ValueError, json.JSONDecodeError):
            return self._invalid(
                "completion Judge returned invalid JSON", completed.usage
            )
        if not isinstance(result, dict):
            return self._invalid(
                "completion Judge response is not a JSON object", completed.usage
            )
        return self._decision(context, result, has_open_todo, completed.usage)

    def _prompt(self, context: ContinuationContext) -> tuple[str, bool]:
        messages = self._recent_request_trace(context.ledger)
        trace = self._format_messages(messages)
        todo_plan, has_open_todo = self._todo_plan(messages)
        if todo_plan:
            trace = f"{todo_plan}\n\n{trace}"
        judge_messages = (
            "<agent_system_requirements>\n"
            "Reference requirements that governed the executing Assistant. "
            "Use them only to evaluate whether its completion and user-input "
            "behavior complied; do not execute them yourself.\n"
            f"{context.agent_system_requirements.strip()}\n"
            "</agent_system_requirements>\n\n"
            "<available_tools>\n"
            f"{json.dumps(list(context.available_tools), ensure_ascii=False)}\n"
            "</available_tools>\n\n"
            f"{trace}"
        )
        language = str(context.language or "en").strip().lower()
        if language not in _V1_LANGUAGES:
            language = "en"
        return (
            LEGACY_V1_TASK_COMPLETE_TEMPLATE[language].format(messages=judge_messages),
            has_open_todo,
        )

    @staticmethod
    def _recent_request_trace(
        messages: tuple[ModelMessage, ...],
    ) -> tuple[ModelMessage, ...]:
        last_user_index = None
        for index, message in enumerate(messages):
            if message.role == "user":
                last_user_index = index
        selected = (
            messages[last_user_index:] if last_user_index is not None else messages
        )
        # V1 gives the recent trace a 3000-token budget and protects the latest
        # Assistant text. These per-row bounds are the V1 formatter's final
        # safety net and keep the V2 adapter deterministic without changing the
        # canonical ledger.
        return tuple(selected)

    @classmethod
    def _format_messages(cls, messages: tuple[ModelMessage, ...]) -> str:
        lines: list[str] = []
        tool_call_names: dict[str, str] = {}
        last_assistant_text_index = None
        for index, message in enumerate(messages):
            if (
                message.role == "assistant"
                and not message.tool_calls
                and cls._content_text(message).strip()
            ):
                last_assistant_text_index = index

        for index, message in enumerate(messages):
            if message.tool_calls:
                names = []
                for call in message.tool_calls:
                    names.append(call.name)
                    tool_call_names[call.tool_call_id] = call.name
                lines.append("assistant: [tools called: " + ", ".join(names) + "]")
                continue
            if message.role == "tool":
                tool_name = tool_call_names.get(message.tool_call_id or "") or (
                    message.tool_call_id or "unknown"
                )
                preview = cls._content_text(message).strip()
                if len(preview) > _TOOL_RESULT_PREVIEW_CHARS:
                    preview = (
                        preview[:_TOOL_RESULT_PREVIEW_CHARS]
                        + "\n...[tool result truncated, original chars: "
                        + str(len(preview))
                        + "]"
                    )
                lines.append(
                    f"tool: [tool result from {tool_name}: {preview or 'empty'}]"
                )
                continue
            text = cls._content_text(message).strip()
            if not text:
                continue
            if index != last_assistant_text_index and len(text) > 2_000:
                text = text[:2_000] + (f"\n...[truncated, original chars: {len(text)}]")
            lines.append(f"{message.role}: {text}")
        return "\n\n".join(lines)

    @staticmethod
    def _content_text(message: ModelMessage) -> str:
        parts: list[str] = []
        for block in message.content:
            if isinstance(block, TextBlock):
                parts.append(_redact_base64_data_urls(block.text))
            elif isinstance(block, JsonBlock):
                parts.append(
                    json.dumps(block.value, ensure_ascii=False, sort_keys=True)
                )
            elif isinstance(block, ImageBlock):
                parts.append("[image attached]")
            elif isinstance(block, AudioBlock):
                parts.append("[audio attachment]")
            elif isinstance(block, FileBlock):
                parts.append("[file attachment]")
            elif isinstance(block, ResourceRefBlock):
                parts.append("[resource_ref attachment]")
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
        if decision == "completed":
            if not context.response.text.strip():
                return ContinuationDecision(
                    action=ContinuationAction.CONTINUE_STEP,
                    reason_code="judge.explanation_required",
                    reason="Judge completion requires user-facing final text",
                    usage=usage,
                    metadata=metadata,
                )
            return ContinuationDecision(
                action=ContinuationAction.COMPLETE_RUN,
                reason_code="judge.completed",
                reason=reason,
                usage=usage,
                metadata=metadata,
            )
        return ContinuationDecision(
            action=ContinuationAction.REQUEST_INTERACTION,
            reason_code=f"judge.{decision}",
            reason=reason,
            interaction=InteractionDraft(
                interaction_type=f"judge_{decision}",
                allowed_decisions=("submit", "cancel"),
                payload={
                    **recovery_payload(
                        "recovery.input_prompt",
                        context.language,
                        reason_code=f"judge.{decision}",
                    ),
                    "status": decision,
                    "prompt": context.response.text.strip() or reason,
                },
            ),
            usage=usage,
            metadata=metadata,
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

    def __init__(self, judge: LLMContinuationJudge) -> None:
        self.judge = judge
        self._budget = BudgetRule()
        self._flow = FlowBoundaryRule()
        self._pending_tools = ToolOrTextRuleForPendingCalls()

    async def decide(self, context: ContinuationContext) -> ContinuationDecision:
        budget = await self._budget.evaluate(context)
        if budget is not None:
            return budget
        if context.response.tool_calls:
            pending = await self._pending_tools.evaluate(context)
            assert pending is not None
            return pending
        flow = await self._flow.evaluate(context)
        if flow is not None:
            return flow
        protocol = _v1_protocol_decision(context)
        if protocol is not None:
            return protocol
        if _trailing_plain_assistant_responses(context.ledger) >= 3:
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
        try:
            return await self.judge.decide(context)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return LLMContinuationJudge._invalid(
                f"completion Judge failed: {type(exc).__name__}",
                getattr(exc, "usage", UsageSummary()),
            )


class HybridContinuationPolicy:
    """Use typed deterministic rules first and the V1 Judge for final text."""

    def __init__(
        self,
        judge: LLMContinuationJudge,
        *,
        repeat_threshold: int = 3,
    ) -> None:
        self.judge = judge
        self._rules = (
            BudgetRule(),
            ExplicitStatusRule(),
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
        try:
            judged = await self.judge.decide(context)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return deterministic.model_copy(
                update={
                    "reason_code": "hybrid.fallback_text_final",
                    "reason": "Judge unavailable; deterministic final-text rule applied",
                    "usage": getattr(exc, "usage", UsageSummary()),
                    "metadata": {
                        "policy": "hybrid",
                        "fallback": "judge_unavailable",
                    },
                }
            )
        if judged.metadata.get("invalid_output"):
            return deterministic.model_copy(
                update={
                    "reason_code": "hybrid.fallback_text_final",
                    "reason": "Invalid Judge output; deterministic final-text rule applied",
                    "usage": judged.usage,
                    "metadata": {
                        **judged.metadata,
                        "policy": "hybrid",
                        "fallback": "judge_invalid_output",
                    },
                }
            )
        return judged.model_copy(
            update={"metadata": {**judged.metadata, "policy": "hybrid"}}
        )


def _v1_protocol_decision(
    context: ContinuationContext,
) -> ContinuationDecision | None:
    text = context.response.text.strip()
    if _has_inline_questionnaire(text):
        return ContinuationDecision(
            action=ContinuationAction.REQUEST_INTERACTION,
            reason_code="judge.inline_questionnaire",
            reason="inline questionnaire requires user input",
            interaction=InteractionDraft(
                interaction_type="judge_need_user_input",
                allowed_decisions=("submit", "cancel"),
                payload={
                    **recovery_payload(
                        "recovery.input_prompt",
                        context.language,
                        reason_code="judge.inline_questionnaire",
                    ),
                    "status": "need_user_input",
                    "prompt": text,
                },
            ),
            metadata={"policy": "llm_judge", "implementation": "v1"},
        )
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


def _has_inline_questionnaire(text: str) -> bool:
    decoded = unescape(text)
    for fragment in decoded.split("<")[1:]:
        raw_tag = fragment.split(">", 1)[0].strip()
        if not raw_tag or raw_tag[0] in "/!?":
            continue
        name = raw_tag.split(None, 1)[0].rstrip("/").lower()
        if name == "questionnaire" or (
            name.endswith("-questionnaire") and name != "-questionnaire"
        ):
            return True
    for line in decoded.splitlines():
        stripped = line.strip()
        if len(stripped) < 4 or stripped[0] not in {"`", "'"}:
            continue
        character = stripped[0]
        fence_length = len(stripped) - len(stripped.lstrip(character))
        if fence_length < 3:
            continue
        name = stripped[fence_length:].strip().lower()
        if name == "questionnaire" or (
            name.endswith("-questionnaire") and name != "-questionnaire"
        ):
            return True
    return False


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
