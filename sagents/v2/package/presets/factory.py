"""SAgents V2 module for package/presets/factory.py."""

from __future__ import annotations

from sagents.v2.agent.presets.catalog import BUILTIN_AGENT_PRESETS
from sagents.v2.package.manifest.agents import ApplicationEntrypoint
from sagents.v2.package.manifest.credentials import CredentialDeclaration
from sagents.v2.package.manifest.flows import FlowDefinition, FlowEdge, FlowNode
from sagents.v2.package.manifest.models import (
    ModelCapabilityDeclaration,
    ModelLimits,
    ModelRequestDefaults,
    ModelRoute,
)
from sagents.v2.package.manifest.root import (
    ManifestMetadata,
    SageManifest,
    TestDeclaration,
)


class BuiltinPackageFactory:
    """Creates single-Agent packages without embedding credentials."""

    @staticmethod
    def dependencies(preset_id: str, package: SageManifest) -> dict[str, SageManifest]:
        """Direct child Packages; load them before binding this preset."""
        return {name: package.model_copy(update={
            "metadata": package.metadata.model_copy(update={
                "id": f"{package.metadata.id}.{name}", "name": BUILTIN_AGENT_PRESETS[name].name}),
            "agents": {name: BUILTIN_AGENT_PRESETS[name].agent_definition()},
            "entrypoint": ApplicationEntrypoint(agent=name),
            "flows": {},
        }) for name in BUILTIN_AGENT_PRESETS[preset_id].subagents}

    @staticmethod
    def create(
        preset_id: str,
        *,
        package_id: str,
        model: str,
        base_url: str | None = None,
        credential_env: str = "SAGE_MODEL_API_KEY",
        context_window: int | None = None,
        max_output_tokens: int | None = None,
    ) -> SageManifest:
        preset = BUILTIN_AGENT_PRESETS[preset_id]
        included = {preset_id: preset.agent_definition()}
        flows = {}
        if preset.entrypoint.type == "flow":
            flows["main"] = FlowDefinition(
                version="1.0.0",
                start="start",
                nodes=(
                    FlowNode(id="start", type="interaction", interaction="user_input"),
                    FlowNode(id="done", type="end"),
                ),
                edges=(FlowEdge(**{"from": "start", "to": "done"}),),
            )
        return SageManifest(
            kind="agent-package",
            metadata=ManifestMetadata(
                id=package_id,
                version="0.1.0",
                name=preset.name,
                description=preset.purpose,
            ),
            credentials={
                "model_api_key": CredentialDeclaration(source="env", key=credential_env)
            },
            models={
                "primary": ModelRoute(
                    provider="openai-compatible",
                    base_url=base_url,
                    credential="model_api_key",
                    model=model,
                    request=ModelRequestDefaults(max_output_tokens=max_output_tokens),
                    limits=ModelLimits(
                        context_window=context_window,
                        max_output_tokens=max_output_tokens,
                    ),
                    capabilities=ModelCapabilityDeclaration(
                        tool_calling=True,
                        reasoning=True,
                        parallel_tool_calls=True,
                    ),
                )
            },
            agents=included,
            flows=flows,
            entrypoint=ApplicationEntrypoint(agent=preset_id),
            tests=TestDeclaration(
                scenarios=(
                    {
                        "id": "smoke",
                        "input": "Complete a representative task for this agent.",
                        "assert": {
                            "run_state": "completed",
                            "no_unhandled_error": True,
                        },
                    },
                ),
                gates={"required_pass_rate": 1.0},
            ),
        )
