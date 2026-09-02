"""Provider-boundary normalization for token usage accounting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sagents.v2.model.wire import wire_value


InputTokenMode = Literal["auto", "inclusive", "disjoint"]


@dataclass(frozen=True, slots=True)
class CanonicalTokenUsage:
    """Token counters with ``input_tokens`` including cached prompt tokens."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0


_TOKEN_USAGE_KEYS = frozenset(
    {
        "prompt_tokens",
        "completion_tokens",
        "input_tokens",
        "output_tokens",
        "cached_input_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "cache_write_input_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "prompt_tokens_details",
        "completion_tokens_details",
        "input_tokens_details",
        "output_tokens_details",
    }
)


def has_token_usage(raw: Any) -> bool:
    """Return whether a provider payload contains a recognized usage counter."""

    if raw is None:
        return False
    return any(wire_value(raw, key) is not None for key in _TOKEN_USAGE_KEYS)


def canonical_token_usage(
    raw: Any,
    *,
    input_mode: InputTokenMode = "auto",
) -> CanonicalTokenUsage:
    """Normalize common provider dialects to one inclusive-input contract.

    OpenAI reports prompt/input tokens inclusive of cache reads, while Anthropic
    and some OpenAI-compatible gateways report ordinary, cache-read, and
    cache-write prompt tokens as disjoint counters. ``auto`` recognizes the
    latter flattened dialect without changing standard OpenAI payloads.
    """

    prompt_details = wire_value(raw, "prompt_tokens_details")
    completion_details = wire_value(raw, "completion_tokens_details")
    input_details = wire_value(raw, "input_tokens_details")
    output_details = wire_value(raw, "output_tokens_details")

    input_tokens = _first_int(raw, "prompt_tokens", "input_tokens")
    output_tokens = _first_int(raw, "completion_tokens", "output_tokens")
    cached_tokens = _first_int(
        prompt_details,
        "cached_tokens",
        fallback_values=(
            wire_value(input_details, "cached_tokens"),
            wire_value(raw, "cached_input_tokens"),
            wire_value(raw, "cache_read_input_tokens"),
        ),
    )
    cache_write_tokens = _first_int(
        raw,
        "cache_creation_input_tokens",
        "cache_write_input_tokens",
        "cache_write_tokens",
    )
    reasoning_tokens = _first_int(
        completion_details,
        "reasoning_tokens",
        fallback_values=(
            wire_value(output_details, "reasoning_tokens"),
            wire_value(raw, "reasoning_tokens"),
        ),
    )

    resolved_mode = input_mode
    if input_mode == "auto":
        has_standard_prompt_total = wire_value(raw, "prompt_tokens") is not None
        has_nested_details = prompt_details is not None or input_details is not None
        has_flat_cache_counter = any(
            wire_value(raw, key) is not None
            for key in (
                "cached_input_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
                "cache_write_input_tokens",
                "cache_write_tokens",
            )
        )
        resolved_mode = (
            "disjoint"
            if not has_standard_prompt_total
            and not has_nested_details
            and has_flat_cache_counter
            else "inclusive"
        )

    if resolved_mode == "disjoint":
        input_tokens += cached_tokens + cache_write_tokens

    # Consumers derive uncached input as input minus cached. Preserve that
    # invariant even for malformed compatible-gateway payloads.
    input_tokens = max(input_tokens, cached_tokens)
    return CanonicalTokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_tokens,
        reasoning_tokens=reasoning_tokens,
    )


def _first_int(
    raw: Any,
    *names: str,
    fallback_values: tuple[Any, ...] = (),
) -> int:
    for name in names:
        value = wire_value(raw, name)
        if value is not None:
            return _nonnegative_int(value)
    for value in fallback_values:
        if value is not None:
            return _nonnegative_int(value)
    return 0


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
