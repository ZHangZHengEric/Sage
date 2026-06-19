from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Dict, List, Optional

import httpx
from openai import APIConnectionError, APIError, RateLimitError

from sagents.llm.capabilities import create_chat_completion_with_fallback
from sagents.llm.model_capabilities import (
    is_openai_reasoning_model,
    resolve_reasoning_effort,
)
from sagents.utils.logger import logger
from sagents.utils.prompt_manager import PromptManager


DEFAULT_DIGEST_BUDGET = 24000
CHUNK_CHAR_BUDGET = 32000
IMPORTANT_LINES_BUDGET = 4000
HEAD_BUDGET = 6000
TAIL_BUDGET = 14000


_MODEL_CONFIG_INTERNAL_KEYS = {
    "api_key",
    "base_url",
    "fast_api_key",
    "fast_base_url",
    "fast_model_name",
    "max_model_len",
    "maxTokens",
}

_SUMMARY_MAX_RETRIES = 3


def _build_summary_extra_body(model_name: str, step_name: str) -> Dict[str, Any]:
    extra_body: Dict[str, Any] = {"_step_name": step_name}
    if is_openai_reasoning_model(model_name):
        extra_body["reasoning_effort"] = resolve_reasoning_effort(
            enable_thinking=False,
            env_value=os.environ.get("SAGE_REASONING_EFFORT_OFF"),
            default_off="low",
        )
    else:
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}
        extra_body["enable_thinking"] = False
        extra_body["thinking"] = {"type": "disabled"}
    return extra_body


def _retry_delay(attempt: int) -> float:
    return min(0.5 * (2**attempt), 4.0)


def _important_lines(history: str, max_chars: int = IMPORTANT_LINES_BUDGET) -> str:
    patterns = [
        r"(/\S+)",
        r"([A-Za-z]:\\[^\s]+)",
        r"(Status\s*:.*)",
        r"(Result\s*:.*)",
        r"(执行摘要.*|关键产出.*|分析结论.*)",
        r"(error|failed|exception|traceback|warning)",
    ]
    important: List[str] = []
    seen = set()
    current_chars = 0
    for line in history.splitlines():
        text = line.strip()
        if not text or text in seen:
            continue
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            important.append(text)
            seen.add(text)
            current_chars += len(text) + 1
        if current_chars >= max_chars:
            break
    return "\n".join(important)[:max_chars]


def compact_subtask_history(
    history: str,
    *,
    max_chars: int = DEFAULT_DIGEST_BUDGET,
) -> str:
    """Create a deterministic digest when LLM summarization is unavailable."""
    history = (history or "").strip()
    if len(history) <= max_chars:
        return history

    section_budget = max(max_chars // 3, 1)
    important = _important_lines(
        history, max_chars=min(IMPORTANT_LINES_BUDGET, section_budget)
    )
    head_chars = min(HEAD_BUDGET, section_budget)
    tail_chars = min(TAIL_BUDGET, section_budget)
    head = history[:head_chars]
    tail = history[-tail_chars:]
    omitted = len(history) - len(head) - len(tail)
    sections = [
        "【重要线索摘录】",
        important or "(未提取到显式路径/状态/错误线索)",
        "\n【执行开头】",
        head,
        f"\n【中间内容已压缩，省略约 {max(omitted, 0)} 字符】",
        "\n【执行结尾】",
        tail,
    ]
    return "\n".join(sections)[:max_chars]


def split_history_chunks(
    history: str,
    *,
    chunk_chars: int = CHUNK_CHAR_BUDGET,
) -> List[str]:
    history = (history or "").strip()
    if not history:
        return []
    if len(history) <= chunk_chars:
        return [history]

    chunks: List[str] = []
    current: List[str] = []
    current_len = 0
    for line in history.splitlines(keepends=True):
        line_len = len(line)
        if current and current_len + line_len > chunk_chars:
            chunks.append("".join(current).strip())
            current = []
            current_len = 0
        if line_len > chunk_chars:
            for start in range(0, line_len, chunk_chars):
                part = line[start : start + chunk_chars].strip()
                if part:
                    chunks.append(part)
            continue
        current.append(line)
        current_len += line_len

    if current:
        chunks.append("".join(current).strip())
    return [chunk for chunk in chunks if chunk]


async def _summarize_once(
    *,
    agent,
    summary_session_id: str,
    history_str: str,
    language: str,
    task_description: str,
    step_name: str,
) -> Optional[str]:
    if not agent:
        return None
    model = getattr(agent, "model", None)
    if model is None:
        return None

    summary_prompt_template = PromptManager().get_agent_prompt(
        agent="FibreAgent",
        key="sub_agent_fallback_summary_prompt",
        language=language,
    )
    prompt = summary_prompt_template.format(
        task_description=task_description or "(not provided)",
        history_str=history_str,
    )
    messages_input = [{"role": "user", "content": prompt}]

    final_config: Dict[str, Any] = dict(getattr(agent, "model_config", {}) or {})
    model_name = str(
        final_config.pop("model", None)
        or getattr(model, "model_name", None)
        or "gpt-3.5-turbo"
    )
    for key in _MODEL_CONFIG_INTERNAL_KEYS:
        final_config.pop(key, None)
    if model.__class__.__name__ != "SageAsyncOpenAI":
        final_config.pop("model_type", None)
    extra_body = _build_summary_extra_body(model_name, step_name)

    from sagents.session_runtime import session_scope

    with session_scope(summary_session_id):
        summary_content = ""
        for attempt in range(_SUMMARY_MAX_RETRIES):
            try:
                response_stream = await create_chat_completion_with_fallback(
                    model,
                    model=model_name,
                    messages=messages_input,
                    model_config=final_config,
                    stream=True,
                    stream_options={"include_usage": True},
                    extra_body=extra_body,
                    **final_config,
                )

                async for chunk in response_stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        summary_content += chunk.choices[0].delta.content
                break
            except (
                RateLimitError,
                APIError,
                APIConnectionError,
                httpx.ReadTimeout,
                httpx.ConnectTimeout,
                httpx.ReadError,
            ) as exc:
                if summary_content or attempt >= _SUMMARY_MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(_retry_delay(attempt))

    return summary_content.strip() or None


async def summarize_subtask_history(
    *,
    agent,
    session_id: str,
    summary_session_id: str,
    history_str: str,
    language: str,
    task_description: str = "",
    subject_label: str = "Sub-agent",
    step_name: str = "subtask_summary",
    empty_message: Optional[str] = None,
) -> str:
    history_str = (history_str or "").strip()
    if not history_str:
        return (
            empty_message
            or f"SubSessionID: {session_id}\nNo response from {subject_label.lower()}"
        )

    chunks = split_history_chunks(history_str)
    try:
        if len(chunks) == 1:
            summary = await _summarize_once(
                agent=agent,
                summary_session_id=summary_session_id,
                history_str=chunks[0],
                language=language,
                task_description=task_description,
                step_name=step_name,
            )
        else:
            summary = None
            for index, chunk in enumerate(chunks, start=1):
                prior = f"【截至上一块的融合总结】\n{summary}\n\n" if summary else ""
                chunk_input = (
                    f"{prior}【当前执行日志块 {index}/{len(chunks)}】\n{chunk}"
                )
                summary = await _summarize_once(
                    agent=agent,
                    summary_session_id=summary_session_id,
                    history_str=chunk_input,
                    language=language,
                    task_description=task_description,
                    step_name=f"{step_name}_chunk_{index}",
                )
                if not summary:
                    summary = compact_subtask_history(chunk_input)

        if summary:
            return (
                f"SubSessionID: {session_id}, if you need to continue the task, "
                "please use this SubSessionID.\n"
                f"{subject_label} execution summary:\n{summary}"
            )
    except Exception as e:
        logger.warning(f"Failed to summarize subtask history via LLM: {e}")

    digest = compact_subtask_history(history_str)
    if task_description:
        digest = f"Task description:\n{task_description}\n\nExecution digest:\n{digest}"
    return (
        f"SubSessionID: {session_id}, if you need to continue the task, "
        "please use this SubSessionID.\n"
        f"{subject_label} response digest:\n{digest}"
    )
