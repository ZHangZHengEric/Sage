"""API-driven recovery for auxiliary inference views; canonical history is immutable."""

from __future__ import annotations
from sagents.v2.model.recovery import (
    collect_response,
    is_context_overflow,
    model_call_budget,
    recovery_error,
    reported_context_limit_error,
)
from sagents.v2.model.contracts import ModelEventKind, ModelMessage
from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock


async def stream_auxiliary_model(model, request):
    """Shared recovery used by selection, completion judging and memory queries."""
    from sagents.v2.context.contracts import ContextReductionScope
    from sagents.v2.context.plugins.summarizer_model import ModelConversationSummarizer
    from sagents.v2.context.summary import SummarizationRequest, summary_safe_block_text
    from sagents.v2.model.contracts import ModelStreamEvent

    original = request
    with model_call_budget():
        for attempt in range(7):
            try:
                response = await collect_response(model, request)
                capabilities_method = getattr(model, "capabilities", None)
                if capabilities_method is not None:
                    ceiling_error = reported_context_limit_error(
                        response, await capabilities_method(request.model_binding)
                    )
                    if ceiling_error is not None:
                        raise ceiling_error
                yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=response)
                return
            except SageV2Error as exc:
                if not is_context_overflow(exc) or attempt == 6:
                    raise
                payload = tuple(
                    m for m in request.messages if m.role not in {"system", "developer"}
                )
                if not payload:
                    raise recovery_error(
                        "model.context_irreducible",
                        "The API rejected mandatory auxiliary instructions",
                    ) from exc
                summarizer = ModelConversationSummarizer(model)
                summary = await summarizer.summarize(
                    SummarizationRequest(
                        scope=ContextReductionScope(
                            context_key=original.run_id,
                            session_id=original.run_id,
                            run_id=original.run_id,
                        ),
                        messages=payload,
                        target_tokens=1024,
                    )
                )
                source = "\n".join(
                    summary_safe_block_text(b) for m in payload for b in m.content
                )
                if not summary.strip() or len(summary) >= len(source):
                    raise recovery_error(
                        "context.summary_no_progress",
                        "Auxiliary context recovery did not reduce its source",
                    ) from exc
                request = request.model_copy(
                    update={
                        "request_id": new_id("auxiliary_context_retry"),
                        "messages": (
                            *(
                                m
                                for m in original.messages
                                if m.role in {"system", "developer"}
                            ),
                            ModelMessage(
                                role="user", content=(TextBlock(text=summary),)
                            ),
                        ),
                        "metadata": {
                            **original.metadata,
                            "context_recovery_attempt": attempt + 1,
                        },
                    }
                )
