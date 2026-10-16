"""Recovery hints for model-generated calls rejected before Tool execution."""

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo

ARGUMENT_ERROR_CODES = frozenset(
    {
        "model.tool_arguments_truncated",
        "model.tool_arguments_invalid_json",
        "model.tool_arguments_not_object",
        "model.tool_name_missing",
    }
)


def can_repair_model_arguments(error: RuntimeErrorInfo) -> bool:
    return (
        error.code in ARGUMENT_ERROR_CODES
        and error.category == ErrorCategory.VALIDATION
        and error.safe_to_resume
        and error.metadata.get("side_effect_state") == "not_applied"
        and error.metadata.get("tool_execution_started") is False
    )


def argument_recovery_guidance(error: RuntimeErrorInfo) -> str:
    tool = str(error.metadata.get("tool_name") or "unnamed Tool")[:128]
    truncated = error.code == "model.tool_arguments_truncated"
    reason = (
        "The previous model response reached its output limit and its Tool arguments were truncated."
        if truncated
        else "The previous model response contained invalid Tool arguments."
    )
    return (
        f"{reason} The rejected call was {tool!r}. "
        "No Tool from that rejected response was executed. Do not continue its partial JSON; "
        "generate fresh, complete calls with valid JSON objects and the available Tool schemas. "
        "Reuse the results of earlier successful calls; do not repeat completed operations. "
        "Keep reasoning brief and use smaller Tool batches. For large files, write one small "
        "file or chunk at a time, then use incremental edits without overwriting completed chunks."
    )
