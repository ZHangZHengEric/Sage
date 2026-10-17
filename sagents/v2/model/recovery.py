"""API-driven bounded recovery for read-only auxiliary model requests.

No input token estimates are made. The original request is immutable; only a
retry projection is replaced. Model calls never execute returned Tool calls.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.model.contracts import ModelEventKind


@dataclass
class ModelCallBudget:
    remaining: int = 64

    def consume(self):
        if self.remaining <= 0:
            raise recovery_error(
                "model.context_recovery_exhausted",
                "Context recovery reached its model-call limit",
            )
        self.remaining -= 1


_active_budget = ContextVar("model_context_recovery_budget", default=None)


@contextmanager
def model_call_budget():
    budget = _active_budget.get() or ModelCallBudget()
    token = _active_budget.set(budget)
    try:
        yield budget
    finally:
        _active_budget.reset(token)


def consume_model_call():
    budget = _active_budget.get()
    if budget is not None:
        budget.consume()


def recovery_error(code, message):
    return SageV2Error(
        RuntimeErrorInfo(
            code=code,
            category=ErrorCategory.VALIDATION,
            message=message,
            safe_to_resume=True,
        )
    )


def is_context_overflow(error):
    return (
        isinstance(error, SageV2Error)
        and error.info.code == "model.context_window_exceeded"
    )


async def adaptive_summary(text, summarize, *, depth=0, merge=None):
    """Try the complete source first; only API rejection permits splitting.

    Both halves are processed before merging. No prefix/tail is discarded and
    no canonical coverage may advance until the complete operation succeeds.
    """
    try:
        result = await summarize(text)
        if not result or not result.strip():
            raise recovery_error(
                "context.summary_empty", "Summary returned no usable content"
            )
        return result
    except SageV2Error as exc:
        if not is_context_overflow(exc):
            raise
        if depth >= 12 or len(text) < 2:
            raise recovery_error(
                "model.context_irreducible",
                "The API rejected the smallest recoverable summary source",
            ) from exc
        middle = len(text) // 2
        first = await adaptive_summary(
            text[:middle], summarize, depth=depth + 1, merge=merge
        )
        second = await adaptive_summary(
            text[middle:], summarize, depth=depth + 1, merge=merge
        )
        merged = merge(first, second) if merge is not None else first + "\n" + second
        # This is a direct content-length comparison, never a token estimate.
        if len(merged) >= len(text):
            raise recovery_error(
                "context.summary_no_progress",
                "Summary splitting did not reduce its source",
            ) from exc
        if merge is not None:
            # Structured children already succeeded through the API. Preserve
            # their facts instead of asking another LLM pass to discard some.
            return merged
        return await adaptive_summary(merged, summarize, depth=depth + 1)


def reported_context_limit_error(response, capabilities):
    """A configured model ceiling is a trigger even if the API accepts input."""
    maximum = capabilities.max_input_tokens
    if maximum and response.usage.reported and response.usage.input_tokens >= maximum:
        return SageV2Error(
            RuntimeErrorInfo(
                code="model.context_window_exceeded",
                category=ErrorCategory.VALIDATION,
                message="Reported input usage reached the configured model limit",
                safe_to_resume=True,
                metadata={
                    "trigger": "reported_input_limit",
                    "input_tokens": response.usage.input_tokens,
                    "max_input_tokens": maximum,
                },
            )
        )
    return None


async def collect_response(model, request, *, transient_retries=3):
    for attempt in range(transient_retries + 1):
        consume_model_call()
        stream = model.stream(request)
        response = None
        try:
            async for event in stream:
                if event.kind == ModelEventKind.COMPLETED:
                    response = event.response
                    if response is not None:
                        break
            if response is None:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="model.stream_incomplete",
                        category=ErrorCategory.PROVIDER_TRANSIENT,
                        message="Auxiliary stream ended without a completed response",
                        retryable=True,
                        safe_to_resume=True,
                    )
                )
            return response
        except SageV2Error as exc:
            if not (
                exc.info.retryable
                and exc.info.category
                in {ErrorCategory.PROVIDER_TRANSIENT, ErrorCategory.RATE_LIMITED}
                and attempt < transient_retries
            ):
                raise
        finally:
            closer = getattr(stream, "aclose", None)
            if closer is not None:
                await closer()
        await asyncio.sleep(2**attempt)
