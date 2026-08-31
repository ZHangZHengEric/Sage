"""Resolve a validated manifest into immutable runtime specifications."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import Field

from sagents.v2.contracts.commands import RunConfig
from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.package.manifest.agents import AgentEntrypoint, AgentMemoryBehavior
from sagents.v2.package.manifest.flows import FlowDefinition
from sagents.v2.package.manifest.credentials import CredentialDeclaration
from sagents.v2.package.manifest.root import (
    InterfaceDeclaration,
    PluginDeclaration,
    SageManifest,
)
from sagents.v2.package.manifest.runtime import RuntimeConfig


class ResolvedAgent(StrictModel):
    name: str
    instructions: str
    mode: Literal["simple", "fibre", "team"] = "simple"
    model_bindings: dict[str, str] = Field(default_factory=dict)
    entrypoint: AgentEntrypoint
    max_steps: int | None = None
    tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    subagents: tuple[str, ...] = ()
    memory: AgentMemoryBehavior = Field(default_factory=AgentMemoryBehavior)


class PolicyCeiling(StrictModel):
    allowed_tools: frozenset[str] = frozenset()
    allowed_skills: frozenset[str] = frozenset()
    allowed_model_routes: frozenset[str] = frozenset()
    max_steps: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_total_tokens: int | None = None
    deadline_seconds: float | None = None


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


class CompositionResolver:
    def resolve(self, manifest: SageManifest) -> ResolvedSageManifest:
        for route_id, route in manifest.models.items():
            if (
                route.credential is not None
                and route.credential not in manifest.credentials
            ):
                raise _error(
                    "manifest.credential_not_found",
                    f"model {route_id!r} references unknown credential {route.credential!r}",
                )
        for agent_id, agent in manifest.agents.items():
            for binding, route_id in agent.models.items():
                if route_id not in manifest.models:
                    raise _error(
                        "manifest.model_not_found",
                        f"agent {agent_id!r} binding {binding!r} references unknown model {route_id!r}",
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
                name=agent.name,
                instructions=agent.instructions.inline or "",
                mode=agent.mode,
                model_bindings=dict(agent.models),
                entrypoint=agent.entrypoint,
                max_steps=max_steps,
                tools=agent.tools,
                skills=agent.skills,
                subagents=agent.subagents,
                memory=agent.memory,
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

        payload = manifest.model_dump(mode="json", exclude={"environments"})
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
                for route_id, route in manifest.models.items()
            },
            flows=dict(manifest.flows),
            policy_ceilings=ceilings,
            plugins=manifest.plugins,
            runtime=manifest.runtime,
            credentials=dict(manifest.credentials),
            interfaces=dict(manifest.interfaces),
        )

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
