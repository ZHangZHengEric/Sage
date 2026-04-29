"""根据 Agent 配置生成能力卡片的通用工具函数.

该模块不直接依赖具体的 FastAPI 服务, 仅依赖:
- Agent 配置字典
- 一个兼容 OpenAI Async 客户端的 chat.completions 接口
- 模型名称字符串

用于 server 和 desktop 两端的 service 调用.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from .logger import logger
from sagents.utils.prompt_manager import PromptManager
from sagents.llm.capabilities import create_chat_completion_with_fallback


class AgentAbilitiesGenerationError(Exception):
    """在生成 Agent 能力列表时出现的受控异常."""


# 能力与 prompt `agent_abilities_user_prompt` 中的 {abilities_count} 保持一致
AGENT_ABILITIES_TARGET_COUNT = 4


def _build_no_thinking_extra_body(model: str) -> Dict[str, Any]:
    model_name = (model or "").lower()
    is_openai_reasoning_model = (
        model_name.startswith("o1")
        or model_name.startswith("o3")
        or model_name.startswith("gpt-5")
    )
    if is_openai_reasoning_model:
        return {
            "reasoning_effort": "low",
        }
    return {
        "chat_template_kwargs": {"enable_thinking": False},
        "enable_thinking": False,
        "thinking": {"type": "disabled"},
    }


def _normalize_id(raw: str) -> str:
    """将任意字符串规范化为 kebab-case id.

    - 转小写
    - 非字母数字统一替换为 '-'
    - 合并重复的 '-'
    - 去掉首尾 '-'
    """

    value = (raw or "").strip().lower()
    if not value:
        return ""
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value)
    value = value.strip("-")
    return value


def _format_name_list(label: str, values: Iterable[str] | None, max_count: int = 10) -> str:
    names = [str(v) for v in (values or []) if str(v).strip()]
    if not names:
        return f"{label}：无"
    display = "、".join(names[:max_count])
    if len(names) > max_count:
        display += " 等"
    return f"{label}：{display}"


def _build_context_summary(context: Optional[Dict[str, Any]]) -> str:
    if not context or not isinstance(context, dict):
        return "There is no additional context."

    parts: List[str] = []
    workspace = context.get("workspace") or context.get("workspace_name")
    if workspace:
        parts.append(f"- Current workspace: {workspace}")

    current_file = context.get("current_file") or context.get("file_path")
    if current_file:
        parts.append(f"- Current file: {current_file}")

    if not parts:
        return "There is no additional context."
    return "\n".join(parts)


def _build_system_context_message(language: str) -> str:
    now = datetime.now().astimezone()
    timezone_name = now.tzname() or "local"
    current_time = now.strftime("%Y-%m-%d %H:%M:%S")
    return PromptManager().get_prompt(
        "auto_gen_agent_system_context_prompt",
        agent="common_util",
        language=language,
    ).format(current_time=current_time, timezone_name=timezone_name)


async def generate_agent_abilities_from_config(
    agent_config: Dict[str, Any],
    context: Optional[Dict[str, Any]],
    client: Any,
    model: str,
    language: str = "en",
    skills: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    """基于 Agent 配置调用 LLM 生成能力卡片列表.

    Args:
        agent_config: Agent 配置字典, 来自现有 Agent 服务.
        context: 可选上下文(预留字段), 例如当前 workspace / 文件等.
        client: 兼容 OpenAI Async 客户端的实例, 需要支持
            `await client.chat.completions.create(...)` 接口.
        model: 使用的模型名称.
        language: 生成语言
        skills: 可选技能列表, 来自 Agent 配置.
    Returns:
        List[Dict[str, str]]: 每个元素包含 id/title/description/promptText.

    Raises:
        AgentAbilitiesGenerationError: 当模型调用或结果解析失败时抛出.
    """

    if not client:
        raise AgentAbilitiesGenerationError("模型客户端未配置")

    agent_name = agent_config.get("name") or agent_config.get("id") or "Sage 助手"
    agent_description = (
        agent_config.get("description")
        or agent_config.get("systemPrefix")
        or agent_config.get("system_prefix")
        or "这是一个通用智能助手。"
    )

    tools = agent_config.get("availableTools") or agent_config.get("available_tools") or []

    # 如果调用方显式传入了 skills（通常包含 name/description 等详情），优先使用；
    # 否则退回到 agent_config 中的 availableSkills/available_skills 仅名称列表。
    display_skills: List[str] = []
    if skills:
        for s in skills:
            if isinstance(s, dict):
                name = s.get("name") or s.get("id") or s.get("title")
                desc = s.get("description") or s.get("desc")
                if name and desc:
                    desc_text = str(desc or "").strip()
                    if len(desc_text) > 500:
                        short_desc = desc_text[:500] + "..."
                    else:
                        short_desc = desc_text
                    display_skills.append(f"{name}（{short_desc}）")
                elif name:
                    display_skills.append(str(name))
            else:
                text = str(s).strip()
                if text:
                    display_skills.append(text)
    else:
        raw_skills = agent_config.get("availableSkills") or agent_config.get("available_skills") or []
        for s in raw_skills:
            text = str(s).strip()
            if text:
                display_skills.append(text)

    workflows_cfg = agent_config.get("availableWorkflows") or agent_config.get("available_workflows") or {}

    if isinstance(workflows_cfg, dict):
        workflow_names: List[str] = list(workflows_cfg.keys())
    elif isinstance(workflows_cfg, list):
        workflow_names = [str(x) for x in workflows_cfg]
    else:
        workflow_names = []

    tools_line = _format_name_list("可用工具", tools)
    skills_line = _format_name_list("可用技能", display_skills)
    workflows_line = _format_name_list("可用工作流", workflow_names)

    context_summary = _build_context_summary(context)

    user_prompt = PromptManager().get_prompt(
        "agent_abilities_user_prompt",
        agent="common_util",
        language=language,
    ).format(
        language=language,
        agent_name=agent_name,
        agent_description=agent_description,
        tools_line=tools_line,
        skills_line=skills_line,
        workflows_line=workflows_line,
        context_summary=context_summary,
        abilities_count=AGENT_ABILITIES_TARGET_COUNT,
    )

    try:
        response = await create_chat_completion_with_fallback(
            client,
            model=model,
            messages=[
                {"role": "system", "content": _build_system_context_message(language)},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=1500,
            extra_body=_build_no_thinking_extra_body(model),
        )
    except Exception as e:  # pragma: no cover - 具体异常类型由底层 SDK 决定
        logger.error(f"生成 Agent 能力列表时调用模型失败: {e}")
        raise AgentAbilitiesGenerationError("调用模型失败，请稍后重试") from e

    # 解析模型返回的 JSON
    try:
        choice = response.choices[0].message
    except Exception as e:  # pragma: no cover
        logger.error(f"解析模型返回结果失败: {e}")
        raise AgentAbilitiesGenerationError("模型返回结果格式不正确") from e

    data_obj: Any
    parsed = getattr(choice, "parsed", None)
    if parsed is not None:
        data_obj = parsed
    else:
        content = getattr(choice, "content", None)
        if isinstance(content, list):
            # 兼容部分 SDK 将 content 表示为片段列表的情况
            content_text = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        else:
            content_text = str(content or "")

        try:
            data_obj = json.loads(content_text)
        except Exception as e:  # pragma: no cover
            logger.error(
                "解析能力卡 JSON 失败: {} | 原始内容开头: {}".format(
                    e, content_text[:500]
                )
            )
            raise AgentAbilitiesGenerationError("解析模型返回的能力列表失败") from e

    if not isinstance(data_obj, dict) or "items" not in data_obj:
        raise AgentAbilitiesGenerationError("能力列表结果缺少 items 字段")

    items_raw = data_obj.get("items") or []
    if not isinstance(items_raw, list):
        raise AgentAbilitiesGenerationError("能力列表 items 字段格式不正确")

    results: List[Dict[str, str]] = []
    seen_ids: set[str] = set()

    for raw in items_raw:
        if not isinstance(raw, dict):
            continue

        raw_id = str(raw.get("id") or "").strip()
        title = str(raw.get("title") or "").strip()
        desc = str(raw.get("description") or "").strip()
        prompt = str(raw.get("promptText") or "").strip()

        if not (raw_id and title and desc and prompt):
            continue

        norm_id = _normalize_id(raw_id)
        if not norm_id:
            continue

        if norm_id in seen_ids:
            base = norm_id
            suffix = 2
            while f"{base}-{suffix}" in seen_ids:
                suffix += 1
            norm_id = f"{base}-{suffix}"

        seen_ids.add(norm_id)
        results.append(
            {
                "id": norm_id,
                "title": title,
                "description": desc,
                "promptText": prompt,
            }
        )

        if len(results) >= AGENT_ABILITIES_TARGET_COUNT:
            break

    if not results:
        raise AgentAbilitiesGenerationError("未生成任何有效的能力项")

    if len(results) < AGENT_ABILITIES_TARGET_COUNT:
        logger.warning(
            "生成的能力项少于预期数量: {} 条（预期 {}）".format(
                len(results), AGENT_ABILITIES_TARGET_COUNT
            )
        )

    logger.info(
        "成功为 Agent 生成 {} 条能力项".format(len(results))
    )

    return results
