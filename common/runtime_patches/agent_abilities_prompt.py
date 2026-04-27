"""Align bundled agent_abilities user prompts with sagents.utils.agent_abilities JSON shape.

The parser requires a top-level object: {\"items\": [...]}. Older prompt text asked for a bare
JSON array, which English models often follow literally → missing \"items\" field error.
This module patches PromptManager in memory at startup (no sagents file edits).
"""

from __future__ import annotations

from loguru import logger

_AGENT = "common_util"
_KEY = "agent_abilities_user_prompt"


def apply_agent_abilities_items_object_prompt_fix() -> None:
    try:
        from sagents.utils.prompt_manager import PromptManager
    except Exception as exc:  # pragma: no cover
        logger.warning(f"agent_abilities prompt patch skipped: {exc}")
        return

    pm = PromptManager()
    replacements: dict[str, tuple[tuple[str, str], ...]] = {
        "zh": (
            (
                "3. 输出必须是严格 JSON 数组。\n4. 每一项必须包含 id、title、description、promptText 四个字段。",
                '3. 输出必须是严格 JSON 对象，顶层只能有一个字段 "items"，其值为数组。\n4. "items" 中每一项必须包含 id、title、description、promptText 四个字段。',
            ),
            (
                "请只返回 JSON 数组，不要输出解释或额外文本。",
                '请只返回形如 {"items":[...]} 的 JSON，不要使用代码围栏，不要输出解释或额外文本。',
            ),
        ),
        "en": (
            (
                "3. The output must be a strict JSON array.\n4. Each item must contain the fields id, title, description, and promptText.",
                '3. The output must be one JSON object with a single top-level key "items" whose value is an array.\n4. Each object in "items" must contain id, title, description, and promptText.',
            ),
            (
                "Return JSON only, without explanations or extra text.",
                "Return only that JSON object (no markdown fences, no extra text).",
            ),
        ),
        "pt": (
            (
                "3. A saída deve ser um array JSON estrito.\n4. Cada item deve conter os campos id, title, description e promptText.",
                '3. A saída deve ser um objeto JSON com uma única chave de nível superior "items", cujo valor é um array.\n4. Cada objeto em "items" deve conter id, title, description e promptText.',
            ),
            (
                "Retorne apenas JSON, sem explicações ou texto extra.",
                "Retorne apenas esse objeto JSON (sem cercas de código markdown, sem texto extra).",
            ),
        ),
    }

    for lang, pairs in replacements.items():
        store = pm.agent_prompts_map.get(lang)
        if not store:
            continue
        block = store.get(_AGENT)
        if not block or _KEY not in block:
            continue
        text = block[_KEY]
        for old, new in pairs:
            if old in text:
                text = text.replace(old, new)
        block[_KEY] = text

    logger.debug("agent_abilities prompt patched for {\"items\": [...]} JSON shape")
