"""Resolve a validated manifest into immutable runtime specifications."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from sagents.v2.agent.policy.approval_config import ToolApprovalConfig
from pydantic import Field, PrivateAttr, model_validator, model_serializer

from sagents.v2.contracts.commands import RunConfig
from sagents.v2.contracts.common import Identifier, StrictModel, VerbatimText
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.package.manifest.agents import AgentEntrypoint, AgentMemoryBehavior, AgentSandboxConfig
from sagents.v2.package.manifest.flows import FlowDefinition
from sagents.v2.package.manifest.credentials import CredentialDeclaration
from sagents.v2.package.manifest.root import (
    InterfaceDeclaration,
    PluginDeclaration,
    SageManifest,
)
from sagents.v2.package.manifest.runtime import RuntimeConfig
from sagents.v2.package.manifest.legacy_budgets import historical_budget_payload, historical_policy_values


class ResolvedAgent(StrictModel):
    source_package_id: str | None = None
    source_agent_id: str | None = None
    source_package_version: str | None = None
    name: str
    instructions: VerbatimText
    mode: Literal["simple", "fibre", "team"] = "simple"
    model_bindings: dict[str, str] = Field(default_factory=dict)
    delegation_model_bindings: dict[str, str] = Field(default_factory=dict)
    entrypoint: AgentEntrypoint
    max_steps: int | None = None
    tools: tuple[str, ...] = ()
    tool_approval: ToolApprovalConfig | None = None
    skills: tuple[str, ...] = ()
    preload_skills: tuple[str, ...] = ()
    subagents: tuple[str, ...] = ()
    memory: AgentMemoryBehavior = Field(default_factory=AgentMemoryBehavior)
    sandbox: AgentSandboxConfig = Field(default_factory=AgentSandboxConfig)

    @model_validator(mode="after")
    def validate_preload_skills(self) -> "ResolvedAgent":
        outside = set(self.preload_skills) - set(self.skills)
        if outside:
            raise ValueError(f"preload_skills must be a subset of skills: {sorted(outside)}")
        return self


class PolicyCeiling(StrictModel):
    _legacy_hash_values: dict = PrivateAttr(default_factory=dict)
    allowed_tools: frozenset[str] = frozenset()
    allowed_skills: frozenset[str] = frozenset()
    allowed_model_routes: frozenset[str] = frozenset()
    max_steps: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_total_tokens: int | None = None
    deadline_seconds: float | None = None

    @model_validator(mode="wrap")
    @classmethod
    def preserve_archive_identity(cls, value, handler):
        ceiling = handler(value)
        if isinstance(value, dict):
            ceiling._legacy_hash_values = {
                key: value.get(key)
                for key in ("max_system_tokens", "protected_recent_tokens")
            }
        return ceiling

    @model_validator(mode="before")
    @classmethod
    def retire_estimated_ceilings(cls, value):
        # Saved Agent revisions predate the retirement and must still restore.
        if isinstance(value, dict):
            return {
                key: item
                for key, item in value.items()
                if key not in {"max_system_tokens", "protected_recent_tokens"}
            }
        return value


class ResolvedSageManifest(StrictModel):
    package_id: Identifier
    package_version: str
    manifest_hash: str
    entrypoint_agent: Identifier | None = None
    entrypoint_flow: Identifier | None = None
    agents: dict[Identifier, ResolvedAgent]
    model_routes: dict[Identifier, dict[str, Any]]
    flows: dict[Identifier, FlowDefinition]
    policy_ceilings: dict[Identifier, PolicyCeiling]
    plugins: tuple[PluginDeclaration, ...] = ()
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    credentials: dict[Identifier, CredentialDeclaration] = Field(default_factory=dict)
    interfaces: dict[Identifier, InterfaceDeclaration] = Field(default_factory=dict)

    @model_serializer(mode="wrap")
    def serialize_archive_identity(self, handler):
        payload = handler(self)
        # Compiled graph digests and recovery archives included the old ceilings.
        # Serialize their provenance here; PolicyCeiling itself stays clean.
        for key, ceiling in payload.get("policy_ceilings", {}).items():
            values = self.policy_ceilings[key]._legacy_hash_values
            ceiling.update({name: values.get(name) for name in (
                "max_system_tokens", "protected_recent_tokens")})
        return payload


class CompositionResolver:
    def __init__(self, *, models=None):
        self.models = models

    def resolve(self, manifest: SageManifest, *, models=None) -> ResolvedSageManifest:
        from sagents.v2.model.catalog import model_catalog_input
        catalog = model_catalog_input(models if models is not None else self.models).selected(
            route for agent in manifest.agents.values()
            for route in (*agent.models.values(), *agent.delegation_model_bindings.values())
        )
        for route_id, route in catalog.models.items():
            if (
                route.credential is not None
                and route.credential not in catalog.credentials
            ):
                raise _error(
                    "manifest.credential_not_found",
                    f"model {route_id!r} references unknown credential {route.credential!r}",
                )
        for agent_id, agent in manifest.agents.items():
            for binding, route_id in agent.models.items():
                if route_id not in catalog.models:
                    raise _error(
                        "manifest.model_not_found",
                        f"agent {agent_id!r} binding {binding!r} references unknown model {route_id!r}",
                    )
            if not set(agent.delegation_model_bindings) <= set(agent.models):
                raise _error(
                    "manifest.model_binding_not_found",
                    f"agent {agent_id!r} delegation overrides require declared model slots",
                )
            if not set(agent.delegation_model_bindings.values()) <= set(
                agent.models.values()
            ):
                raise _error(
                    "manifest.model_override_denied",
                    f"agent {agent_id!r} delegation models exceed its policy ceiling",
                )
            for child_id in agent.subagents:
                if child_id not in manifest.agents:
                    raise _error(
                        "manifest.subagent_not_found",
                        f"agent {agent_id!r} references unknown subagent {child_id!r}",
                    )
            if (
                agent.entrypoint.type == "flow"
                and agent.entrypoint.flow not in manifest.flows
            ):
                raise _error(
                    "manifest.flow_not_found",
                    f"agent {agent_id!r} references unknown flow {agent.entrypoint.flow!r}",
                )
        if (
            manifest.entrypoint.agent is not None
            and manifest.entrypoint.agent not in manifest.agents
        ):
            raise _error(
                "manifest.agent_not_found",
                f"entrypoint references unknown agent {manifest.entrypoint.agent!r}",
            )
        if (
            manifest.entrypoint.flow is not None
            and manifest.entrypoint.flow not in manifest.flows
        ):
            raise _error(
                "manifest.flow_not_found",
                f"entrypoint references unknown flow {manifest.entrypoint.flow!r}",
            )

        global_budget = manifest.policies.budgets
        resolved_agents: dict[str, ResolvedAgent] = {}
        ceilings: dict[str, PolicyCeiling] = {}
        for agent_id, agent in manifest.agents.items():
            entrypoint_steps = agent.entrypoint.config.get("max_steps")
            max_steps = _minimum(
                agent.budgets.max_steps
                if agent.budgets.max_steps is not None
                else entrypoint_steps,
                global_budget.max_steps,
            )
            resolved_agents[agent_id] = ResolvedAgent(
                source_package_id=manifest.metadata.id, source_agent_id=agent_id,
                source_package_version=manifest.metadata.version,
                name=agent.name,
                instructions=agent.instructions.inline or "",
                mode=agent.mode,
                model_bindings=dict(agent.models),
                delegation_model_bindings=dict(agent.delegation_model_bindings),
                entrypoint=agent.entrypoint,
                max_steps=max_steps,
                tools=agent.tools,
                tool_approval=agent.tool_approval,
                skills=agent.skills,
                preload_skills=agent.preload_skills,
                subagents=agent.subagents,
                memory=agent.memory, sandbox=agent.sandbox,
            )
            ceilings[agent_id] = PolicyCeiling(
                allowed_tools=frozenset(agent.tools),
                allowed_skills=frozenset(agent.skills),
                allowed_model_routes=frozenset(agent.models.values()),
                max_steps=max_steps,
                max_input_tokens=_minimum(
                    agent.budgets.input_tokens, global_budget.input_tokens
                ),
                max_output_tokens=_minimum(
                    agent.budgets.output_tokens, global_budget.output_tokens
                ),
                max_total_tokens=_minimum(
                    agent.budgets.total_tokens, global_budget.total_tokens
                ),
                deadline_seconds=_minimum(
                    agent.budgets.wall_time_seconds,
                    global_budget.wall_time_seconds,
                ),
            )
            ceilings[agent_id]._legacy_hash_values = historical_policy_values(manifest, agent_id)

        payload = manifest.model_dump(mode="json", exclude={"environments"})
        # Preserve pre-field hashes for packages that do not opt in.
        for definition in payload["agents"].values():
            if not definition.get("preload_skills"):
                definition.pop("preload_skills", None)
        historical_budget_payload(payload)
        payload["models"] = catalog.model_dump(mode="json")
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return ResolvedSageManifest(
            package_id=manifest.metadata.id,
            package_version=manifest.metadata.version,
            manifest_hash=f"sha256:{digest}",
            entrypoint_agent=manifest.entrypoint.agent,
            entrypoint_flow=manifest.entrypoint.flow,
            agents=resolved_agents,
            model_routes={
                route_id: route.model_dump(mode="json")
                for route_id, route in catalog.models.items()
            },
            flows=dict(manifest.flows),
            policy_ceilings=ceilings,
            plugins=manifest.plugins,
            runtime=manifest.runtime,
            credentials=dict(catalog.credentials),
            interfaces=dict(manifest.interfaces),
        )

    def resolve_child_run_config(
        self,
        resolved: ResolvedSageManifest,
        agent_id: str,
        *,
        parent_config: RunConfig,
        tools: tuple[str, ...] | None = None,
        skills: tuple[str, ...] | None = None,
    ) -> RunConfig:
        """Resolve a child's durable selection before allocating its Run.

        Priority: explicit delegation overrides > parent's resolved choices >
        child defaults. Inherit the primary slot and slots declared by the child;
        parent-only auxiliary slots do not grant the child additional routes.
        A disallowed inherited selection is rejected, never silently replaced.
        Resume must reuse the stored RunConfig rather than call this again.
        """
        agent = resolved.agents[agent_id]
        bindings = dict(agent.model_bindings)
        bindings.update(
            {
                slot: route
                for slot, route in parent_config.model_bindings.items()
                if slot == "primary" or slot in agent.model_bindings
            }
        )
        bindings.update(agent.delegation_model_bindings)
        config = self.resolve_run_config(
            resolved,
            agent_id,
            model_bindings=bindings,
            tools=tools,
            skills=skills,
        )
        execution_policy = None
        if parent_config.execution_snapshot is not None and agent.sandbox.network == "none":
            execution_policy = {"network": {"mode": "none", "deny_private_networks": True}}
        # These are ceilings, not a fresh allocation per child. Runtime checks
        # also account for siblings and the ancestor's original creation time.
        return config.model_copy(update={
            "execution_policy": execution_policy,
            "max_total_tokens": _minimum(config.max_total_tokens, parent_config.max_total_tokens),
            "deadline_seconds": _minimum(config.deadline_seconds, parent_config.deadline_seconds),
            "max_stages": parent_config.max_stages,
            "automatic_stage_continuation": parent_config.automatic_stage_continuation,
            "transient_retry_limit": parent_config.transient_retry_limit,
            "priority": parent_config.priority,
        })

    def resolve_run_config(
        self,
        resolved: ResolvedSageManifest,
        agent_id: str,
        *,
        model_bindings: dict[str, str] | None = None,
        tools: tuple[str, ...] | None = None,
        skills: tuple[str, ...] | None = None,
        max_steps: int | None = None,
        max_output_tokens: int | None = None,
        max_total_tokens: int | None = None,
        deadline_seconds: float | None = None,
        priority: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> RunConfig:
        agent = resolved.agents[agent_id]
        ceiling = resolved.policy_ceilings[agent_id]
        selected_models = dict(model_bindings or agent.model_bindings)
        if not set(selected_models.values()) <= ceiling.allowed_model_routes:
            raise _error(
                "manifest.model_override_denied",
                "model override exceeds policy ceiling",
            )
        selected_tools = tuple(agent.tools if tools is None else tools)
        if not set(selected_tools) <= ceiling.allowed_tools:
            raise _error(
                "manifest.tool_override_denied", "tool override exceeds policy ceiling"
            )
        selected_skills = tuple(agent.skills if skills is None else skills)
        if not set(selected_skills) <= ceiling.allowed_skills:
            raise _error(
                "manifest.skill_override_denied",
                "skill override exceeds policy ceiling",
            )
        values = {
            "max_steps": max_steps if max_steps is not None else ceiling.max_steps,
            "max_output_tokens": (
                max_output_tokens
                if max_output_tokens is not None
                else ceiling.max_output_tokens
            ),
            "max_total_tokens": (
                max_total_tokens
                if max_total_tokens is not None
                else ceiling.max_total_tokens
            ),
            "deadline_seconds": (
                deadline_seconds
                if deadline_seconds is not None
                else ceiling.deadline_seconds
            ),
        }
        for name, value in values.items():
            limit = getattr(ceiling, name)
            if value is not None and limit is not None and value > limit:
                raise _error(
                    "manifest.budget_override_denied",
                    f"{name} override exceeds policy ceiling",
                )
        run_metadata = dict(metadata or {})
        run_metadata["enabled_tools"] = list(selected_tools)
        run_metadata["enabled_skills"] = list(selected_skills)
        return RunConfig(
            model_bindings=selected_models,
            enabled_tools=selected_tools,
            enabled_skills=selected_skills,
            priority=priority,
            metadata=run_metadata,
            **values,
        )


def _minimum(left, right):
    values = [value for value in (left, right) if value is not None]
    return min(values) if values else None


def _error(code: str, message: str) -> SageV2Error:
    category = (
        ErrorCategory.POLICY_DENIED
        if code.endswith("override_denied")
        else ErrorCategory.VALIDATION
    )
    return SageV2Error(RuntimeErrorInfo(code=code, category=category, message=message))
