import inspect

import pytest

from sagents.utils.sandbox.factory import SandboxProviderFactory
from sagents.utils.sandbox.interface import ISandboxHandle, SandboxType
from sagents.utils.sandbox.providers.local.local import LocalSandboxProvider
from sagents.utils.sandbox.providers.passthrough.passthrough import (
    PassthroughSandboxProvider,
)
from sagents.utils.sandbox.providers.remote.firecracker import (
    FirecrackerSandboxProvider,
)
from sagents.utils.sandbox.providers.remote.kubernetes import (
    KubernetesSandboxProvider,
)
from sagents.utils.sandbox.providers.remote.opensandbox import OpenSandboxProvider


@pytest.mark.parametrize(
    "provider_class",
    [
        LocalSandboxProvider,
        PassthroughSandboxProvider,
        OpenSandboxProvider,
        KubernetesSandboxProvider,
        FirecrackerSandboxProvider,
    ],
)
def test_builtin_provider_follows_sandbox_interface(provider_class):
    assert issubclass(provider_class, ISandboxHandle)
    assert not inspect.isabstract(provider_class)
    assert callable(getattr(provider_class, "prepare_code_environment", None))
    assert callable(getattr(provider_class, "sync_skills", None))


def test_factory_rejects_provider_outside_interface():
    class InvalidProvider:
        pass

    with pytest.raises(TypeError, match="ISandboxHandle"):
        SandboxProviderFactory.register_local_provider(
            SandboxType.LOCAL, InvalidProvider
        )

    with pytest.raises(TypeError, match="ISandboxHandle"):
        SandboxProviderFactory.register_remote_provider("invalid", InvalidProvider)
