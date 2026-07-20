import asyncio

from sagents.utils.sandbox.config import SandboxConfig
from sagents.utils.sandbox.factory import SandboxProviderFactory
from sagents.utils.sandbox.interface import SandboxType
from sagents.utils.sandbox.providers.passthrough.passthrough import (
    PassthroughSandboxProvider,
)


def test_factory_initializes_provider_before_returning(monkeypatch, tmp_path):
    calls = []

    class FakeProvider(PassthroughSandboxProvider):
        async def initialize(self):
            calls.append("initialize")

    monkeypatch.setitem(
        SandboxProviderFactory._providers, SandboxType.PASSTHROUGH, FakeProvider
    )

    provider = asyncio.run(
        SandboxProviderFactory.create(
            SandboxConfig(
                sandbox_id="test-sandbox",
                mode=SandboxType.PASSTHROUGH,
                sandbox_agent_workspace=str(tmp_path),
            )
        )
    )

    assert isinstance(provider, FakeProvider)
    assert calls == ["initialize"]
