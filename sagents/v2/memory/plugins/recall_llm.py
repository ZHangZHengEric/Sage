"""Official Memory recall-query plugin: compact keywords from a fast model."""

from __future__ import annotations

import json

from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model import ModelMessage, ModelRequest
from sagents.v2.model.provider import ModelProvider


class LLMMemoryRecallQueryGenerator:
    """Use a model to turn the current request into compact search keywords."""

    plugin_id = "sage.memory.recall-query.llm"
    name = "LLM-generated keywords"
    description = (
        "Uses a fast model to generate compact keywords before calling search_memory."
    )

    def __init__(self, model: ModelProvider, *, language: str = "en") -> None:
        self.model = model
        self.language = language

    async def generate(self, user_input: str, *, run_id: str) -> str:
        source = user_input.strip()
        if not source:
            return ""
        chinese = self.language.lower().startswith("zh")
        system = (
            "你是 Sage AI 的记忆召回专家。请把用户当前请求转换成精准、简短的记忆检索词。"
            if chinese
            else "You are Sage AI's Memory recall expert. Convert the current user request into a precise, compact Memory search query."
        )
        prompt = (
            "提取 3-10 个关键词。优先保留项目名、文件名、路径、函数名、产品名和核心需求；忽略客套、运行时信息和已完成的旧动作。"
            "只返回 JSON：{\"query\":\"检索词\"}\n\n用户请求：\n"
            if chinese
            else "Extract 3-10 keywords. Prefer project names, filenames, paths, functions, products, and the core request; ignore chatter, runtime details, and completed old actions. "
            "Return JSON only: {\"query\":\"search terms\"}\n\nUser request:\n"
        )
        request = ModelRequest(
            request_id=new_id("memory_query"),
            run_id=run_id,
            model_binding="fast",
            messages=(
                ModelMessage(role="system", content=(TextBlock(text=system),)),
                ModelMessage(role="user", content=(TextBlock(text=prompt + source),)),
            ),
            tools=(),
            tool_choice="none",
            metadata={"purpose": "memory_recall_query"},
        )
        try:
            response = None
            stream = self.model.stream(request)
            try:
                async for event in stream:
                    if event.response is not None:
                        response = event.response
            finally:
                closer = getattr(stream, "aclose", None)
                if closer is not None:
                    await closer()
            if response is None:
                return source
            text = response.text.strip()
            if text.startswith("```"):
                lines = text.splitlines()
                text = "\n".join(lines[1:-1]).strip() if len(lines) > 2 else text
            value = json.loads(text)
            query = value.get("query") if isinstance(value, dict) else None
            return query.strip() if isinstance(query, str) and query.strip() else source
        except Exception:
            return source
