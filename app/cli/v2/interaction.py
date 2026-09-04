"""交互决策器：把 v2 的 ``InteractionRequest``（审批 / 用户输入）交给用户或既定策略作答。"""

from __future__ import annotations

import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, TextIO

from sagents.v2.contracts.interactions import InteractionRequest, InteractionType

from app.cli.v2.render import JsonRenderer

# 读一行用户输入（去掉换行）；EOF 返回 None。由 ``StdinLineReader`` 提供，测试可注入。
LineReader = Callable[[], Awaitable[str | None]]

# 无法作答时的退化顺序：只会收紧（拒绝/停止），绝不放宽。
DECISION_FALLBACK_ORDER = ("deny", "cancel")
# ``--json`` 模式下，驱动方（如 Rust TUI）通过 stdin 回写的决策行类型。
JSON_DECISION_TYPE = "v2_interaction_decision"
_APPROVAL_KEYS = {
    "a": "approve_once",
    "approve": "approve_once",
    "y": "approve_once",
    "r": "approve_and_remember",
    "remember": "approve_and_remember",
    "d": "deny",
    "deny": "deny",
    "n": "deny",
    "c": "cancel",
    "cancel": "cancel",
}
# "记住"的作用域：r = 本会话，w = 本工作区（仅当运行时在 approval_scopes 里提供时）。
_REMEMBER_SCOPE_KEYS = {
    "r": "session",
    "remember": "session",
    "w": "workspace",
    "workspace": "workspace",
}
_RECOVERY_KEYS = {
    "r": "retry",
    "retry": "retry",
    "c": "change_direction",
    "change": "change_direction",
    "s": "cancel",
    "stop": "cancel",
    "cancel": "cancel",
}


@dataclass(frozen=True)
class InteractionAnswer:
    decision: str
    payload: dict[str, Any] = field(default_factory=dict)


class InteractionDecider(Protocol):
    async def decide(self, interaction: InteractionRequest) -> InteractionAnswer: ...


def fallback_decision(interaction: InteractionRequest) -> str:
    for candidate in DECISION_FALLBACK_ORDER:
        if candidate in interaction.allowed_decisions:
            return candidate
    return interaction.allowed_decisions[0]


def remember_scopes(interaction: InteractionRequest) -> tuple[str, ...]:
    """本次审批可"记住"的作用域；不能记住时为空。``session`` 始终排最前。"""

    if "approve_and_remember" not in interaction.allowed_decisions:
        return ()
    raw = interaction.payload.get("approval_scopes")
    scopes = [str(value) for value in raw] if isinstance(raw, list) else []
    if "session" not in scopes:
        scopes.insert(0, "session")
    return tuple(scopes)


def coerce_answer(
    interaction: InteractionRequest,
    decision: str | None,
    payload: dict[str, Any] | None = None,
) -> InteractionAnswer:
    """不在 ``allowed_decisions`` 内的答案一律退化为拒绝/停止。"""

    if decision is not None and decision in interaction.allowed_decisions:
        return InteractionAnswer(decision, dict(payload or {}))
    return InteractionAnswer(fallback_decision(interaction))


def summarize_interaction(interaction: InteractionRequest) -> str:
    payload = interaction.payload
    if interaction.interaction_type == InteractionType.APPROVAL:
        lines = [
            f"approval required: {payload.get('tool_name')}",
            f"  arguments: {json.dumps(payload.get('arguments'), ensure_ascii=False)}",
        ]
        if payload.get("side_effect_level"):
            lines.append(f"  risk: {payload.get('side_effect_level')}")
        if payload.get("risk_reason"):
            lines.append(f"  reason: {payload.get('risk_reason')}")
        return "\n".join(lines)
    title = payload.get("title") or f"{interaction.interaction_type.value} required"
    lines = [str(title)]
    if payload.get("prompt"):
        lines.append(f"  {payload['prompt']}")
    error = payload.get("error")
    if isinstance(error, dict):
        detail = error.get("message") or ""
        diagnostic = (error.get("metadata") or {}).get("diagnostic_message")
        if diagnostic and diagnostic not in detail:
            detail = f"{detail} ({diagnostic})" if detail else str(diagnostic)
        lines.append(f"  error: {error.get('code')}: {detail}")
    for question in payload.get("questions") or ():
        if not isinstance(question, dict):
            continue
        lines.append(f"  - {question.get('title') or question.get('id')}")
        for option in question.get("options") or ():
            if isinstance(option, dict):
                lines.append(f"      [{option.get('value')}] {option.get('label')}")
    lines.append(f"  allowed decisions: {', '.join(interaction.allowed_decisions)}")
    return "\n".join(lines)


class StaticInteractionDecider:
    """固定答案（``--approval-mode approve-all|deny-all`` 或非交互 stdin）。

    审批以外的交互（需要用户输入）无法用固定答案回答，只能停止本次 Run；
    停止前把原因完整打出来，用户才能知道发生了什么。
    """

    def __init__(
        self,
        decision: str,
        *,
        notice: Callable[[str], None] | None = None,
    ) -> None:
        self.decision = decision
        self.notice = notice

    async def decide(self, interaction: InteractionRequest) -> InteractionAnswer:
        answer = coerce_answer(interaction, self.decision)
        if self.notice is not None:
            self.notice(
                summarize_interaction(interaction)
                + f"\n  -> non-interactive decision: {answer.decision}"
            )
        return answer


class PromptInteractionDecider:
    """TTY 交互式提问；输入来自进程唯一的 stdin 读取者，等待可被中断。"""

    def __init__(
        self,
        read_line: LineReader,
        *,
        err: TextIO | None = None,
    ) -> None:
        self.read_line = read_line
        self.err = err or sys.stderr

    async def decide(self, interaction: InteractionRequest) -> InteractionAnswer:
        self._write("\n" + summarize_interaction(interaction) + "\n")
        if interaction.interaction_type == InteractionType.APPROVAL:
            return await self._decide_approval(interaction)
        if "submit" in interaction.allowed_decisions:
            return await self._decide_free_text(interaction)
        if "retry" in interaction.allowed_decisions:
            return await self._decide_recovery(interaction)
        return await self._decide_by_name(interaction)

    async def _decide_approval(self, interaction: InteractionRequest) -> InteractionAnswer:
        scopes = remember_scopes(interaction)
        options = "[a]pprove once / [d]eny / [c]ancel"
        if scopes:
            remember = "[r]emember for this session"
            if "workspace" in scopes:
                remember += " / [w] remember for this workspace"
            options = f"[a]pprove once / {remember} / [d]eny / [c]ancel"
        while True:
            raw = await self._ask(f"{options}: ")
            if raw is None:
                return InteractionAnswer(fallback_decision(interaction))
            key = raw.strip().lower()
            scope = _REMEMBER_SCOPE_KEYS.get(key)
            if scope is not None and scope in scopes:
                return InteractionAnswer("approve_and_remember", {"scope": scope})
            decision = _APPROVAL_KEYS.get(key)
            if (
                decision is not None
                and decision != "approve_and_remember"
                and decision in interaction.allowed_decisions
            ):
                return InteractionAnswer(decision)
            self._write(f"please answer one of: {options}\n")

    async def _decide_free_text(self, interaction: InteractionRequest) -> InteractionAnswer:
        raw = await self._ask("your answer (empty line cancels): ")
        text = (raw or "").strip()
        if not text:
            return InteractionAnswer(fallback_decision(interaction))
        return InteractionAnswer("submit", {"text": text})

    async def _decide_recovery(self, interaction: InteractionRequest) -> InteractionAnswer:
        options = "[r]etry / [c]hange direction / [s]top"
        while True:
            raw = await self._ask(f"{options}: ")
            if raw is None:
                return InteractionAnswer(fallback_decision(interaction))
            decision = _RECOVERY_KEYS.get(raw.strip().lower())
            if decision is None or decision not in interaction.allowed_decisions:
                self._write(f"please answer one of: {options}\n")
                continue
            if decision == "change_direction":
                guidance = await self._ask("new direction (empty line cancels): ")
                text = (guidance or "").strip()
                if not text:
                    return InteractionAnswer(fallback_decision(interaction))
                return InteractionAnswer(decision, {"text": text})
            return InteractionAnswer(decision)

    async def _decide_by_name(self, interaction: InteractionRequest) -> InteractionAnswer:
        options = " / ".join(interaction.allowed_decisions)
        while True:
            raw = await self._ask(f"decision ({options}): ")
            if raw is None:
                return InteractionAnswer(fallback_decision(interaction))
            decision = raw.strip()
            if decision in interaction.allowed_decisions:
                return InteractionAnswer(decision)
            self._write(f"please answer one of: {options}\n")

    async def _ask(self, prompt: str) -> str | None:
        self._write(prompt)
        line = await self.read_line()
        if line is None:
            self._write("\n")
        return line

    def _write(self, text: str) -> None:
        self.err.write(text)
        self.err.flush()


class JsonLineInteractionDecider:
    """``--json`` 模式：向 stdout 发 ``cli_v2_interaction`` 帧，从 stdin 读决策行。"""

    def __init__(self, renderer: JsonRenderer, read_line: LineReader) -> None:
        self.renderer = renderer
        self.read_line = read_line

    async def decide(self, interaction: InteractionRequest) -> InteractionAnswer:
        self.renderer.frame(interaction_frame(interaction))
        while True:
            line = await self.read_line()
            if line is None:
                return InteractionAnswer(fallback_decision(interaction))
            payload = _parse_line(line)
            if payload is None or payload.get("type") != JSON_DECISION_TYPE:
                continue
            target = payload.get("interaction_id")
            if target and target != interaction.interaction_id:
                continue
            reply_payload = payload.get("payload")
            return coerce_answer(
                interaction,
                payload.get("decision"),
                reply_payload if isinstance(reply_payload, dict) else None,
            )


def interaction_frame(interaction: InteractionRequest) -> dict[str, Any]:
    return {
        "type": "cli_v2_interaction",
        "run_id": interaction.run_id,
        "interaction_id": interaction.interaction_id,
        "interaction_type": interaction.interaction_type.value,
        "allowed_decisions": list(interaction.allowed_decisions),
        "payload": interaction.payload,
        "expires_at": (
            interaction.expires_at.isoformat() if interaction.expires_at else None
        ),
    }


def _parse_line(line: str) -> dict[str, Any] | None:
    text = line.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
