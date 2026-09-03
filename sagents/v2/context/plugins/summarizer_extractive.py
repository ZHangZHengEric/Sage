"""Official conversation-summarizer plugin: deterministic extractive fallback."""

from __future__ import annotations

import json

from sagents.v2.context.summary import SummarizationRequest
from sagents.v2.contracts.items import JsonBlock, TextBlock
from sagents.v2.model.contracts import ModelMessage


class ExtractiveConversationSummarizer:
    """Deterministic zero-network fallback that preserves exact recent facts."""

    plugin_id = "sage.context.summarizer.extractive"
    name = "Extractive conversation summarizer"
    description = "Builds summaries by extracting salient sentences from recent units."

    async def summarize(self, request: SummarizationRequest) -> str:
        labels = {
            "en": (
                "Previous summary:",
                "New history:",
                "Tool calls:",
                "[...history condensed...]",
            ),
            "zh": ("之前的摘要：", "新增历史：", "工具调用：", "[……历史已压缩……]"),
            "pt": (
                "Resumo anterior:",
                "Novo histórico:",
                "Chamadas de ferramentas:",
                "[...histórico condensado...]",
            ),
        }[request.response_language]
        lines = []
        if request.previous_summary:
            lines.extend([labels[0], request.previous_summary.strip(), labels[1]])
        for message in request.messages:
            label = message.role.upper()
            content = self._content(message)
            if message.tool_calls:
                calls = ", ".join(
                    f"{call.name}({json.dumps(call.arguments, ensure_ascii=False, sort_keys=True)})"
                    for call in message.tool_calls
                )
                content = f"{content}\n{labels[2]} {calls}".strip()
            lines.append(f"{label}: {content}".strip())
        maximum = max(256, request.target_tokens * 4)
        value = "\n".join(lines).strip()
        if len(value) <= maximum:
            return value
        head = value[: maximum // 3]
        tail = value[-(maximum - len(head) - 32) :]
        return f"{head}\n{labels[3]}\n{tail}"

    @staticmethod
    def _content(message: ModelMessage) -> str:
        values = []
        for block in message.content:
            if isinstance(block, TextBlock):
                values.append(block.text)
            elif isinstance(block, JsonBlock):
                values.append(
                    json.dumps(block.value, ensure_ascii=False, sort_keys=True)
                )
            else:
                values.append(
                    json.dumps(block.model_dump(mode="json"), ensure_ascii=False)
                )
        return "\n".join(values)
