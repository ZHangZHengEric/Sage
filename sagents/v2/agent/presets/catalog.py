"""First-party Agent presets built only from public v2 package contracts."""

from __future__ import annotations

from pydantic import Field

from sagents.v2.contracts.common import Identifier, StrictModel, ToolName
from sagents.v2.package.manifest.agents import (
    AgentBudgets,
    AgentDefinition,
    AgentEntrypoint,
    Instructions,
)


class BuiltinAgentPreset(StrictModel):
    preset_id: Identifier
    name: str
    purpose: str
    instructions: str
    tools: tuple[ToolName, ...] = ()
    subagents: tuple[Identifier, ...] = ()
    max_steps: int = Field(default=24, gt=0)
    entrypoint: AgentEntrypoint = Field(default_factory=AgentEntrypoint)

    def agent_definition(self, *, model_route: str = "primary") -> AgentDefinition:
        return AgentDefinition(
            name=self.name,
            instructions=Instructions(inline=self.instructions),
            models={"primary": model_route},
            entrypoint=self.entrypoint,
            tools=self.tools,
            subagents=self.subagents,
            budgets=AgentBudgets(max_steps=self.max_steps),
        )


# Presets use only the established decorated SAgents tools. Tool names are
# stable provider-facing API and therefore cannot be renamed by a preset.
READ_TOOLS = ("file_read", "grep", "glob", "list_dir", "search_memory")
WRITE_TOOLS = (
    "file_write",
    "file_update",
    "apply_patch",
)
PROCESS_TOOLS = ("execute_shell_command", "await_shell", "kill_shell")
PLANNING_TOOLS = ("todo_write", "todo_read", "turn_status")


BUILTIN_AGENT_PRESETS: dict[str, BuiltinAgentPreset] = {
    # Presets are product defaults and framework examples, not Kernel branches.
    # A host can omit or replace the complete catalog.
    "assistant": BuiltinAgentPreset(
        preset_id="assistant",
        name="General Assistant",
        purpose="General model and tool loop with minimal privileges.",
        instructions="Answer accurately. Use tools only when needed and report uncertainty explicitly.",
        tools=PLANNING_TOOLS,
        max_steps=12,
    ),
    "coder": BuiltinAgentPreset(
        preset_id="coder",
        name="Coding Agent",
        purpose="Inspect, modify, and validate a workspace through sandboxed tools.",
        instructions=(
            "Inspect relevant files before editing. Keep changes scoped, use a plan for multi-step work, "
            "run focused validation, and summarize evidence. Never bypass sandbox or approval policy."
        ),
        tools=(*READ_TOOLS, *WRITE_TOOLS, *PROCESS_TOOLS, *PLANNING_TOOLS),
        subagents=("reviewer", "test_runner"),
        max_steps=48,
    ),
    "reviewer": BuiltinAgentPreset(
        preset_id="reviewer",
        name="Code Reviewer",
        purpose="Read-only, evidence-based correctness and risk review.",
        instructions=(
            "Review for concrete correctness, security, concurrency, compatibility, and test gaps. "
            "Cite exact files and avoid changing the workspace."
        ),
        tools=(*READ_TOOLS, *PLANNING_TOOLS),
        max_steps=24,
    ),
    "test_runner": BuiltinAgentPreset(
        preset_id="test_runner",
        name="Test Runner",
        purpose="Select and execute bounded validation commands.",
        instructions=(
            "Inspect project test conventions, run the narrowest useful checks, distinguish baseline "
            "failures from regressions, and return exact commands and results."
        ),
        tools=(*READ_TOOLS, *PROCESS_TOOLS, *PLANNING_TOOLS),
        max_steps=24,
    ),
    "researcher": BuiltinAgentPreset(
        preset_id="researcher",
        name="Research Agent",
        purpose="Collect and synthesize evidence through configured resource providers.",
        instructions=(
            "Prefer primary sources, retain provenance, separate sourced facts from inference, and "
            "state freshness limits. Use only resource tools explicitly supplied by the host."
        ),
        tools=PLANNING_TOOLS,
        max_steps=32,
    ),
    "memory_recall": BuiltinAgentPreset(
        preset_id="memory_recall",
        name="Memory Recall Agent",
        purpose="Select relevant historical facts without inventing memories.",
        instructions=(
            "Retrieve only memories exposed by configured memory or resource providers. "
            "Rank by relevance and freshness, preserve provenance, and return no-memory explicitly."
        ),
        tools=PLANNING_TOOLS,
        max_steps=12,
    ),
    "planner": BuiltinAgentPreset(
        preset_id="planner",
        name="Planning Agent",
        purpose="Turn a goal into a bounded, dependency-aware execution plan.",
        instructions=(
            "Create an ordered plan with verifiable outcomes, dependencies, risks, and one active "
            "step at most. Do not execute the task unless explicitly delegated."
        ),
        tools=PLANNING_TOOLS,
        max_steps=12,
    ),
    "query_suggest": BuiltinAgentPreset(
        preset_id="query_suggest",
        name="Query Suggestion Agent",
        purpose="Generate concise, materially distinct follow-up queries.",
        instructions=(
            "Suggest a small set of non-duplicative queries grounded in the current request and "
            "available context. Never present suggestions as completed research."
        ),
        max_steps=8,
    ),
    "self_check": BuiltinAgentPreset(
        preset_id="self_check",
        name="Self Check Agent",
        purpose="Check an answer or artifact against explicit requirements and evidence.",
        instructions=(
            "Test claims against supplied evidence, search for counterexamples, separate blocking "
            "errors from improvements, and return a deterministic pass or fail rationale."
        ),
        tools=(*READ_TOOLS, *PLANNING_TOOLS),
        max_steps=20,
    ),
    "tool_suggestion": BuiltinAgentPreset(
        preset_id="tool_suggestion",
        name="Tool Suggestion Agent",
        purpose="Choose the least-privilege tools required for an agent or task.",
        instructions=(
            "Select only tools present in the supplied catalog. Explain capability and permission "
            "requirements, and do not silently expand privileges."
        ),
        tools=PLANNING_TOOLS,
        max_steps=12,
    ),
    "agent_creator": BuiltinAgentPreset(
        preset_id="agent_creator",
        name="Agent Creator",
        purpose="Create versioned AgentPackage drafts and their scenario tests.",
        instructions=(
            "Create declarative agent definitions, least-privilege capability requirements, scenario "
            "tests, and evaluation gates. Validate in an isolated sandbox. Publication always requires "
            "an explicit host policy decision."
        ),
        tools=(
            *READ_TOOLS,
            *WRITE_TOOLS,
            *PROCESS_TOOLS,
            *PLANNING_TOOLS,
        ),
        subagents=("test_runner", "reviewer"),
        max_steps=56,
    ),
    "flow_orchestrator": BuiltinAgentPreset(
        preset_id="flow_orchestrator",
        name="Flow Orchestrator",
        purpose="Execute a manifest-declared deterministic Agent Flow.",
        instructions=(
            "Follow the declared flow graph. Preserve branch causality and surface interactions at "
            "stable checkpoints. Do not invent graph transitions."
        ),
        tools=PLANNING_TOOLS,
        max_steps=64,
        entrypoint=AgentEntrypoint(type="flow", flow="main"),
    ),
}
