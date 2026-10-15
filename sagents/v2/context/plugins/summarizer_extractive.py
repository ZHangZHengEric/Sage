"""Official conversation-summarizer plugin: deterministic extractive fallback."""

from __future__ import annotations

import json

from sagents.v2.prompt_i18n import prompt_text
from sagents.v2.context.summary import SummarizationRequest, summary_safe_block_text
from sagents.v2.model.contracts import ModelMessage


class ExtractiveConversationSummarizer:
    """Deterministic zero-network fallback that preserves exact recent facts."""

    plugin_id = "sage.context.summarizer.extractive"
    name = "Extractive conversation summarizer"
    description = "Builds summaries by extracting salient sentences from recent units."

    async def summarize(self, request: SummarizationRequest) -> str:
        labels = tuple(prompt_text(key, request.response_language) for key in (
            "summary_previous", "summary_history", "summary_tools", "summary_condensed"
        ))
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
        return "\n".join(summary_safe_block_text(block) for block in message.content)
