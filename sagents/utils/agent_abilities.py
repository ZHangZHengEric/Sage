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
from sagents.llm.capabilities import create_chat_completion_with_fallback


class AgentAbilitiesGenerationError(Exception):
    """在生成 Agent 能力列表时出现的受控异常."""


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
        return "当前没有额外上下文。"

    parts: List[str] = []
    workspace = context.get("workspace") or context.get("workspace_name")
    if workspace:
        parts.append(f"- 当前工作空间：{workspace}")

    current_file = context.get("current_file") or context.get("file_path")
    if current_file:
        parts.append(f"- 当前文件：{current_file}")

    if not parts:
        return "当前没有额外上下文。"
    return "\n".join(parts)


def _build_system_context_message(language: str) -> str:
    now = datetime.now().astimezone()
    timezone_name = now.tzname() or "local"
    current_time = now.strftime("%Y-%m-%d %H:%M:%S")
    if str(language).lower().startswith("en"):
        return (
            "You are generating deterministic prompt suggestions for the current agent.\n"
            "Use the current runtime context as background facts when helpful.\n"
            f"Current local time: {current_time}\n"
            f"Current timezone: {timezone_name}\n"
            "Do not mention these system facts explicitly unless they materially help produce better prompts."
        )
    return (
        "你正在为当前 Agent 生成可直接使用的能力模板。\n"
        "如有必要，可以把当前运行环境基础信息当作背景事实使用。\n"
        f"当前本地时间：{current_time}\n"
        f"当前时区：{timezone_name}\n"
        "除非确实有助于生成更好的模板，否则不要在结果中直接复述这些系统信息。"
    )


async def generate_agent_abilities_from_config(
    agent_config: Dict[str, Any],
    context: Optional[Dict[str, Any]],
    client: Any,
    model: str,
    language: str = "zh",
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

    user_prompt = f"""
你是一个根据 Agent 描述和技能列表，生成「可直接运行、无需用户再提供任何输入」的问题模板的助手。

核心原则：每条 promptText 必须是「确定性的、可直接执行」的完整指令。用户复制后发送即可，Agent 能立即根据该指令完成任务，无需用户再上传文件、补充链接、填写占位符或说明「稍后给你」。

必须遵守的约束：
1) 可直接运行：禁止出现需要用户「提供文件/链接/数据」的表述。例如不可写「我给你一个 Excel 文件，你整理一下」「你帮我分析这个网站」——用户不会真的提供文件或链接，因此这类问题不可用。应改为：在提问中写明具体任务与可推断的内容（如「根据 2024 年 Q1 销售数据格式，生成一个示例 Excel 表头并说明各列含义」），或明确指定可公开访问的对象（如「分析 https://example.com 首页的 SEO 问题」）。
2) 明确指向性：所有引用必须具体化。
   - 若涉及「做一份 PPT」：必须写明具体主题，例如「做一份关于新能源汽车市场趋势的 5 页 PPT 大纲」。
   - 若涉及「某网站」：必须写出具体网站名称或 URL，例如「爬取豆瓣电影 Top250 前 10 条并整理成表格」。
   - 若涉及「某项目/某代码」：要么写成「用 Python 写一个冒泡排序」这类自包含任务，要么指定公开可用的仓库/示例。
3) 依据技能具体描述：严格根据下方「可用技能」及 Agent 简介中的能力描述来设计问题，使每条问题对应技能的真实用法，不虚构能力；这样模型才能实际执行。
4) 禁止在提问中直接提及具体技能或工作流的内部名称/ID（例如 "deep-research-agent"、"my-workflow-1" 等），只描述用户要完成的任务本身，不要让用户显式指定某个 skill 或 workflow。
5) 禁止占位符：promptText 中不得出现「请在这里粘贴」「在下方补充」「某个/某份」等需用户补充的内容；不要用「XXX」代替具体名称，必须写出示例性的具体名称或可执行的描述。

输出要求：
- 仅输出 JSON 字符串，不能包含任何额外说明。
- JSON 结构：
  {{
    "items": [
      {{
        "id": "kebab-case-id",
        "title": "短标题",
        "description": "1-2 句说明",
        "promptText": "用户可直接发送的完整、可执行的提问"
      }}
    ]
  }}

字段规范：
- id：全部小写、短横线分隔，例如 "code-review"。
- title：简洁概括场景或技能侧重点。
- description：说明适用场景/解决问题，1-2 句话。
- promptText：完整、确定性的自然语言指令，复制即用，不依赖用户再提供文件、链接或任何额外输入；主题、网站、示例等均需具体化。

内容约束：
- 严格依据给定的描述与技能信息，不要虚构技能。
- 覆盖不同技能/场景，避免同义重复；总数最多 4 条。
- 随机生成：每次生成时随机选择要体现的能力与场景，不要固定套路；输出的 4 条模板在主题、侧重点上应有随机性和多样性。
- 忽略输入顺序：下方「可用工具」「可用技能」「可用工作流」等列表的先后顺序仅供参考，不要优先选用排在前面或后面的项；应把列表中所有项视为平等，随机挑选不同项来设计模板，使每次生成的结果在覆盖面上更随机。

语言：生成语言为 "{language}"。

仅输出 JSON，不要在 JSON 外输出任何内容。

当前 Agent 配置：
- Agent 名称：{agent_name}
- Agent 简介：{agent_description}

{tools_line}
{skills_line}
{workflows_line}

可选上下文（如有）：
{context_summary}

请基于以上信息随机选取能力与场景，生成最多 4 条「可直接运行、确定性、有明确指向性」的提问模板，每条 promptText 必须具体、完整、无需用户再补充任何内容。不要按上述配置中列举顺序偏好选材，应随机覆盖。
""".strip()

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

        if len(results) >= 8:
            break

    if not results:
        raise AgentAbilitiesGenerationError("未生成任何有效的能力项")

    if len(results) < 4:
        logger.warning(
            "生成的能力项少于预期数量: {} 条".format(len(results))
        )

    logger.info(
        "成功为 Agent 生成 {} 条能力项".format(len(results))
    )

    return results
