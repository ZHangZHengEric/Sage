"""Explicit host injections collected by the fluent Builder."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from sagents.v2.agent.policy import (
    ApprovalMemory,
    DefaultToolPolicy,
)
from sagents.v2.composition.contracts import (
    ApplicationResource,
)
from sagents.v2.memory import (
    MemoryProvider,
)
from sagents.v2.model import ModelProvider
from sagents.v2.runtime.execution import (
    ExecutionBindingProvider,
)
from sagents.v2.runtime.observability import (
    DiagnosticSink,
    LogSink,
)
from sagents.v2.runtime.session import (
    DerivedStateStore,
    SessionStore,
)
from sagents.v2.sagent import DriverFactory
from sagents.v2.session_memory import (
    SessionMemoryProvider,
)
from sagents.v2.tool import (
    ToolCatalog,
    ToolExecutor,
    ToolSelectionPolicy,
)
from sagents.v2.tool.official import OfficialToolRuntime


class BuildOptions:
    def __init__(self) -> None:
        self.session_root: Path | None = None
        self.session_store: SessionStore | None = None
        self.derived_state_store: DerivedStateStore | None = None
        self.memory_provider: MemoryProvider | None = None
        self.session_memory_provider: SessionMemoryProvider | None = None
        self.model_provider: ModelProvider | None = None
        self.model_provider_factory = None
        self.extra_tools = []
        self.scheduler = None
        self.tool_catalog: ToolCatalog | None = None
        self.tool_executor: ToolExecutor | None = None
        self.tool_runtime: OfficialToolRuntime | None = None
        self.tool_selection: ToolSelectionPolicy | None = None
        self.tool_policy: DefaultToolPolicy | None = None
        self.approval_memory: ApprovalMemory | None = None
        self.approval_memory_layer: (
            Callable[[ApprovalMemory], ApprovalMemory] | None
        ) = None
        self.execution_binding_provider: ExecutionBindingProvider | None = None
        self.log_sink: LogSink | None = None
        self.diagnostic_sink: DiagnosticSink | None = None
        self.model_client: Any | None = None
        self.agent_management = None
        self.self_configuration_factory = None
        self.flow_tool_nodes = {}
        self.skill_provider = None
        self.model_budget = None
        self.job_runtime = None
        self.run_driver_factory: DriverFactory | None = None
        self.admitted_run_contract = None
        self.owned_resources: list[ApplicationResource] = []
        self.check_readiness = False
        self.dispatcher = None
        self.defer_dispatcher_start = False
        self.manual_dispatcher_start = False
        self.revision_identity = False
