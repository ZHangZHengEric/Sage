"""Fail closed when a provider cannot enforce a resolved resource policy."""

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from .contracts import IsolationLevel, ResolvedSandboxSpec, SandboxCapabilities


def validate_resource_support(
    spec: ResolvedSandboxSpec, caps: SandboxCapabilities
) -> None:
    if not spec.resources.require_hard_limits:
        return
    missing = [
        name
        for name in ("cpu", "memory", "disk", "process_count")
        if not getattr(caps.resources, name)
    ]
    if caps.isolation_level == IsolationLevel.NONE:
        missing.append("OS isolation")
    if missing:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="sandbox.resource_limits_unsupported",
                category=ErrorCategory.POLICY_DENIED,
                message="Required sandbox limits are unavailable: "
                + ", ".join(missing),
                metadata={
                    "missing_limits": missing,
                    "side_effect_state": "not_applied",
                },
            )
        )
