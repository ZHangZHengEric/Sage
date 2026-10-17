from __future__ import annotations
from tests.sagents.v2.model_fixture import TEST_MODELS

import asyncio

import pytest

from sagents.v2.context import (
    ContextReductionScope,
)
from sagents.v2.context.runtime_metadata import RunMetadataContextProvider
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model import ModelMessage


def message(text, role="assistant", **kwargs):
    return ModelMessage(role=role, content=(TextBlock(text=text),), **kwargs)


def scope(key="session"):
    return ContextReductionScope(context_key=key, session_id=key, run_id=key)


class Summary:
    def __init__(self, text="history summary"):
        self.requests = []
        self.text = text

    async def summarize(self, request):
        self.requests.append(request)
        return self.text


def test_workspace_memory_is_bounded_but_core_instructions_are_not_silently_cut():
    provider = RunMetadataContextProvider()
    memory = provider._identity_document("MEMORY", "记忆" * 100000, "zh")
    assert len(memory) < 4200
    assert "仅为节选" in memory
    with pytest.raises(SageV2Error):
        provider._identity_document("AGENT", "instruction " * 5000, "en")


def test_manifest_system_and_protected_limits_respect_global_ceiling():
    from sagents.v2.package.presets.factory import BuiltinPackageFactory
    from sagents.v2.package.manifest.resolver import CompositionResolver

    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.context-zones",
    )
    data = package.model_dump(mode="json")
    agent_id = data["entrypoint"]["agent"]
    data["agents"][agent_id]["budgets"].update(
        system_tokens=12000, protected_recent_tokens=4096
    )
    data["policies"]["budgets"].update(system_tokens=8000, protected_recent_tokens=0)
    resolved = CompositionResolver(models=TEST_MODELS).resolve(
        type(package).model_validate(data)
    )
    assert resolved.policy_ceilings[agent_id].max_system_tokens == 8000
    assert resolved.policy_ceilings[agent_id].protected_recent_tokens == 0


@pytest.mark.asyncio
async def test_summary_capacity_is_shared_across_plugin_instances():
    from sagents.v2.context import ModelConversationSummarizer
    from sagents.v2.context.summary import SummarizationRequest

    active = peak = 0

    class SummaryPlugin(ModelConversationSummarizer):
        async def _summarize(self, request, progress):
            nonlocal active, peak
            active += 1
            peak = max(active, peak)
            try:
                await asyncio.sleep(0.01)
                return "summary"
            finally:
                active -= 1

    request = SummarizationRequest(scope=scope(), messages=(), target_tokens=512)
    values = await asyncio.gather(
        *(SummaryPlugin(None).summarize(request) for _ in range(16))
    )
    assert values == ["summary"] * 16
    assert peak == 4
