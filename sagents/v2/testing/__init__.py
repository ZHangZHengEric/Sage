"""SAgents V2 module for testing/__init__.py."""

from sagents.v2.testing.contracts import (
    ScenarioDefinition,
    ScenarioExpectation,
    ScenarioInteractionReply,
    ScenarioResult,
    ScenarioSuiteReport,
)
from sagents.v2.testing.runner import ScenarioRunner
from sagents.v2.testing.runtime import ephemeral_runtime
from sagents.v2.testing.distributed import (
    run_scheduler_conformance,
    run_session_store_recovery_conformance,
)

from sagents.v2.testing.providers import (
    check_provider_contract,
    run_model_provider_conformance,
    run_skill_management_conformance,
    run_skill_provider_conformance,
    run_tool_provider_conformance,
)

__all__ = [
    "ScenarioDefinition",
    "ScenarioExpectation",
    "ScenarioInteractionReply",
    "ScenarioResult",
    "ScenarioRunner",
    "ScenarioSuiteReport",
    "ephemeral_runtime",
    "check_provider_contract",
    "run_model_provider_conformance",
    "run_skill_management_conformance",
    "run_skill_provider_conformance",
    "run_tool_provider_conformance",
    "run_scheduler_conformance",
    "run_session_store_recovery_conformance",
]
