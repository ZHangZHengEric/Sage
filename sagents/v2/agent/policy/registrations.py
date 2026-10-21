"""Official tool, approval and continuation policy registrations."""

from __future__ import annotations

from sagents.v2.agent.policy import (
    ApprovalStrategy,
    BudgetRule,
    CompositeContinuationPolicy,
    DefaultToolPolicy,
    ExplicitStatusContinuationPolicy,
    ExplicitStatusRule,
    FlowBoundaryRule,
    HybridContinuationPolicy,
    LLMContinuationJudge,
    LLMJudgeContinuationPolicy,
    LoopRecoveryRule,
    SessionApprovalMemory,
    ToolOrTextRule,
)
from sagents.v2.contracts.common import StrictModel
from sagents.v2.model.provider import DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS
from sagents.v2.runtime.extensions.contracts import ExtensionDependency, ExtensionScope
from sagents.v2.runtime.extensions.registration import (
    register_plugin,
    service_registration,
)
from sagents.v2.runtime.extensions.registry import ExtensionRegistry


class ToolPolicyConfig(StrictModel):
    approval_strategy: ApprovalStrategy = ApprovalStrategy.CONFIGURED


def register_policy_plugins(registry: ExtensionRegistry) -> None:
    register_plugin(
        registry,
        CompositeContinuationPolicy,
        "agent.continuation-policy",
        lambda context, dependencies: CompositeContinuationPolicy(
            rules=(
                BudgetRule(),
                ExplicitStatusRule(),
                LoopRecoveryRule(int(context.config.get("repeat_threshold", 3))),
                FlowBoundaryRule(),
                ToolOrTextRule(),
            )
        ),
        scopes={ExtensionScope.AGENT, ExtensionScope.RUN},
        config_schema=_continuation_config_schema(),
    )

    register_plugin(
        registry,
        LLMJudgeContinuationPolicy,
        "agent.continuation-policy",
        lambda context, dependencies: LLMJudgeContinuationPolicy(
            LLMContinuationJudge(
                dependencies.require_unique("model.provider"),
                model_binding=str(context.config.get("model_binding", "fast")),
                timeout_seconds=float(
                    context.config.get(
                        "timeout_seconds", DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS
                    )
                ),
            ),
        ),
        dependencies=(ExtensionDependency(capability="model.provider"),),
        scopes={ExtensionScope.AGENT, ExtensionScope.RUN},
        config_schema=_continuation_config_schema(uses_model=True),
    )

    register_plugin(
        registry,
        HybridContinuationPolicy,
        "agent.continuation-policy",
        lambda context, dependencies: HybridContinuationPolicy(
            LLMContinuationJudge(
                dependencies.require_unique("model.provider"),
                model_binding=str(context.config.get("model_binding", "fast")),
                timeout_seconds=float(
                    context.config.get(
                        "timeout_seconds", DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS
                    )
                ),
            ),
            repeat_threshold=int(context.config.get("repeat_threshold", 3)),
        ),
        dependencies=(ExtensionDependency(capability="model.provider"),),
        scopes={ExtensionScope.AGENT, ExtensionScope.RUN},
        config_schema=_continuation_config_schema(uses_model=True),
    )

    register_plugin(
        registry,
        ExplicitStatusContinuationPolicy,
        "agent.continuation-policy",
        lambda context, dependencies: ExplicitStatusContinuationPolicy(
            repeat_threshold=int(context.config.get("repeat_threshold", 3))
        ),
        scopes={ExtensionScope.AGENT, ExtensionScope.RUN},
        config_schema=_continuation_config_schema(),
    )

    registry.register(
        service_registration(
            DefaultToolPolicy.plugin_id,
            "agent.tool-policy",
            lambda context, deps: DefaultToolPolicy(
                **ToolPolicyConfig.model_validate(context.config).model_dump()
            ),
            config_model=ToolPolicyConfig,
        )
    )
    registry.register(
        service_registration(
            SessionApprovalMemory.plugin_id,
            "agent.approval-memory",
            lambda context, deps: SessionApprovalMemory(
                deps.require("derived-state.store")
            ),
            dependencies=("derived-state.store",),
        )
    )


def _continuation_config_schema(*, uses_model: bool = False) -> dict:
    properties = {
        "repeat_threshold": {"type": "integer", "minimum": 1, "default": 3},
    }
    required = []
    if uses_model:
        properties.update(
            {
                "model_binding": {"type": "string", "minLength": 1, "default": "fast"},
                "timeout_seconds": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "default": DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS,
                },
            }
        )
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
