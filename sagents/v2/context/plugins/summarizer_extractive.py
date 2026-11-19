"""Deterministic task-state fallback for rolling context summaries."""
from sagents.v2.context.plugins._shared.progress_summary import extract_snapshot
from sagents.v2.context.summary import SummarizationRequest


class ExtractiveConversationSummarizer:
    plugin_id = "sage.context.summarizer.extractive"
    name = "Extractive conversation summarizer"
    description = "Preserves bounded task state and Tool outcomes without a model call."

    async def summarize(self, request: SummarizationRequest) -> str:
        return await extract_snapshot(request)
