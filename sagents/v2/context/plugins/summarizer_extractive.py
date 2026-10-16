"""Deterministic task-state fallback for rolling context summaries."""
from sagents.v2.context.progress_summary import bounded_snapshot
from sagents.v2.context.summary import SummarizationRequest


class ExtractiveConversationSummarizer:
    plugin_id = "sage.context.summarizer.extractive"
    name = "Extractive conversation summarizer"
    description = "Preserves bounded task state and Tool outcomes without a model call."

    async def summarize(self, request: SummarizationRequest) -> str:
        return bounded_snapshot(request)
