import importlib.util
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common.services.llm_provider_probe_utils import friendly_provider_probe_error

@dataclass
class StubLLMProviderCreate:
    name: str | None = None
    base_url: str = ""
    api_keys: list[str] | None = None
    model: str = ""
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    presence_penalty: float | None = None
    max_model_len: int | None = None
    supports_multimodal: bool = False
    supports_structured_output: bool = False
    is_default: bool = False


@dataclass
class StubLLMProviderUpdate:
    name: str | None = None
    base_url: str | None = None
    api_keys: list[str] | None = None
    model: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    presence_penalty: float | None = None
    max_model_len: int | None = None
    supports_multimodal: bool | None = None
    supports_structured_output: bool | None = None
    is_default: bool | None = None


class StubLLMProvider:
    def __init__(
        self,
        id: str,
        name: str,
        base_url: str,
        api_keys: list[str],
        model: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        presence_penalty: float | None = None,
        max_model_len: int | None = None,
        supports_multimodal: bool = False,
        supports_structured_output: bool = False,
        is_default: bool = False,
        user_id: str = "",
    ):
        self.id = id
        self.name = name
        self.base_url = base_url
        self.api_keys = api_keys
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.presence_penalty = presence_penalty
        self.max_model_len = max_model_len
        self.supports_multimodal = supports_multimodal
        self.supports_structured_output = supports_structured_output
        self.is_default = is_default
        self.user_id = user_id


def _install_stub_modules():
    loguru_module = types.ModuleType("loguru")
    loguru_module.logger = types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
    sys.modules["loguru"] = loguru_module

    models_module = types.ModuleType("common.models.llm_provider")
    models_module.LLMProvider = StubLLMProvider
    models_module.LLMProviderDao = object
    sys.modules["common.models.llm_provider"] = models_module

    schemas_module = types.ModuleType("common.schemas.base")
    schemas_module.LLMProviderCreate = StubLLMProviderCreate
    schemas_module.LLMProviderUpdate = StubLLMProviderUpdate
    sys.modules["common.schemas.base"] = schemas_module

    sagents_llm_module = types.ModuleType("sagents.llm")

    async def _unexpected_probe(*args, **kwargs):
        raise AssertionError("probe stub should be replaced by the test")

    sagents_llm_module.probe_connection = _unexpected_probe
    sagents_llm_module.probe_llm_capabilities = _unexpected_probe
    sagents_llm_module.probe_multimodal = _unexpected_probe
    sagents_llm_module.probe_structured_output = _unexpected_probe
    sys.modules["sagents.llm"] = sagents_llm_module


def _load_service_module():
    _install_stub_modules()
    module_path = REPO_ROOT / "common" / "services" / "llm_provider_service.py"
    spec = importlib.util.spec_from_file_location("llm_provider_service_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeDao:
    def __init__(self, *, providers_by_config=None, provider_by_id=None):
        self.providers_by_config = list(providers_by_config or [])
        self.provider_by_id = provider_by_id
        self.saved = []
        self.cleared_defaults = []

    async def get_by_config(self, **kwargs):
        return list(self.providers_by_config)

    async def get_by_id(self, provider_id):
        if self.provider_by_id and self.provider_by_id.id == provider_id:
            return self.provider_by_id
        return None

    async def save(self, provider):
        self.saved.append(provider)
        return True

    async def clear_default_for_user(self, *, user_id=None, exclude_provider_id=None):
        self.cleared_defaults.append(
            {
                "user_id": user_id,
                "exclude_provider_id": exclude_provider_id,
            }
        )


class TestLLMProviderProbeRequired(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_service_module()

    async def test_create_provider_probes_before_save(self):
        dao = FakeDao()
        probe_calls = []

        async def fake_probe(api_key, base_url, model):
            probe_calls.append((api_key, base_url, model))
            return {"supported": True}

        self.module.LLMProviderDao = lambda: dao
        self.module.probe_connection = fake_probe

        provider_id = await self.module.create_provider(
            self.module.LLMProviderCreate(
                base_url="https://example.com/v1/",
                api_keys=["sk-test"],
                model="test-model",
            ),
            user_id="alice",
        )

        self.assertTrue(provider_id)
        self.assertEqual(probe_calls, [("sk-test", "https://example.com/v1", "test-model")])
        self.assertEqual(len(dao.saved), 1)
        self.assertEqual(dao.saved[0].base_url, "https://example.com/v1")

    async def test_create_provider_blocks_save_when_probe_fails(self):
        dao = FakeDao()

        async def fake_probe(api_key, base_url, model):
            raise RuntimeError("401 unauthorized")

        self.module.LLMProviderDao = lambda: dao
        self.module.probe_connection = fake_probe

        with self.assertRaises(ValueError) as ctx:
            await self.module.create_provider(
                self.module.LLMProviderCreate(
                    base_url="https://example.com/v1",
                    api_keys=["sk-test"],
                    model="test-model",
                ),
                user_id="alice",
            )

        self.assertEqual(
            str(ctx.exception),
            "Cannot save provider. Provider authentication failed. Please check the API key.",
        )
        self.assertEqual(dao.saved, [])

    async def test_create_provider_maps_model_not_found_probe_errors(self):
        dao = FakeDao()

        async def fake_probe(api_key, base_url, model):
            raise RuntimeError("model not found")

        self.module.LLMProviderDao = lambda: dao
        self.module.probe_connection = fake_probe

        with self.assertRaises(ValueError) as ctx:
            await self.module.create_provider(
                self.module.LLMProviderCreate(
                    base_url="https://example.com/v1",
                    api_keys=["sk-test"],
                    model="missing-model",
                ),
                user_id="alice",
            )

        self.assertEqual(
            str(ctx.exception),
            "Cannot save provider. Provider model is not available. Please check the model name.",
        )
        self.assertEqual(dao.saved, [])

    async def test_update_provider_probes_merged_config_before_save(self):
        existing = StubLLMProvider(
            id="provider-1",
            name="old-name",
            base_url="https://old.example.com/v1",
            api_keys=["sk-old"],
            model="old-model",
            user_id="alice",
        )
        dao = FakeDao(provider_by_id=existing)
        probe_calls = []

        async def fake_probe(api_key, base_url, model):
            probe_calls.append((api_key, base_url, model))
            return {"supported": True}

        self.module.LLMProviderDao = lambda: dao
        self.module.probe_connection = fake_probe

        updated = await self.module.update_provider(
            "provider-1",
            self.module.LLMProviderUpdate(
                base_url="https://new.example.com/v1/",
                model="new-model",
            ),
            user_id="alice",
            allow_system_default_update=True,
        )

        self.assertIs(updated, existing)
        self.assertEqual(probe_calls, [("sk-old", "https://new.example.com/v1", "new-model")])
        self.assertEqual(existing.base_url, "https://new.example.com/v1")
        self.assertEqual(existing.model, "new-model")
        self.assertEqual(len(dao.saved), 1)

    async def test_update_provider_name_only_still_requires_probe(self):
        existing = StubLLMProvider(
            id="provider-2",
            name="old-name",
            base_url="https://stable.example.com/v1",
            api_keys=["sk-stable"],
            model="stable-model",
            user_id="alice",
        )
        dao = FakeDao(provider_by_id=existing)
        probe_calls = []

        async def fake_probe(api_key, base_url, model):
            probe_calls.append((api_key, base_url, model))
            return {"supported": True}

        self.module.LLMProviderDao = lambda: dao
        self.module.probe_connection = fake_probe

        await self.module.update_provider(
            "provider-2",
            self.module.LLMProviderUpdate(name="renamed"),
            user_id="alice",
            allow_system_default_update=True,
        )

        self.assertEqual(probe_calls, [("sk-stable", "https://stable.example.com/v1", "stable-model")])
        self.assertEqual(existing.name, "renamed")
        self.assertEqual(len(dao.saved), 1)

    async def test_create_provider_as_default_clears_other_defaults(self):
        dao = FakeDao()

        async def fake_probe(api_key, base_url, model):
            return {"supported": True}

        self.module.LLMProviderDao = lambda: dao
        self.module.probe_connection = fake_probe

        provider_id = await self.module.create_provider(
            self.module.LLMProviderCreate(
                base_url="https://example.com/v1",
                api_keys=["sk-test"],
                model="test-model",
                is_default=True,
            ),
            user_id="alice",
        )

        self.assertTrue(provider_id)
        self.assertEqual(
            dao.cleared_defaults,
            [{"user_id": "alice", "exclude_provider_id": provider_id}],
        )
        self.assertEqual(len(dao.saved), 1)
        self.assertTrue(dao.saved[0].is_default)

    async def test_update_provider_maps_timeout_probe_errors(self):
        existing = StubLLMProvider(
            id="provider-3",
            name="old-name",
            base_url="https://stable.example.com/v1",
            api_keys=["sk-stable"],
            model="stable-model",
            user_id="alice",
        )
        dao = FakeDao(provider_by_id=existing)

        async def fake_probe(api_key, base_url, model):
            raise RuntimeError("connection timeout")

        self.module.LLMProviderDao = lambda: dao
        self.module.probe_connection = fake_probe

        with self.assertRaises(ValueError) as ctx:
            await self.module.update_provider(
                "provider-3",
                self.module.LLMProviderUpdate(model="stable-model-v2"),
                user_id="alice",
                allow_system_default_update=True,
            )

        self.assertEqual(
            str(ctx.exception),
            "Cannot update provider. Provider connection failed. Please check the base URL and network connectivity.",
        )
        self.assertEqual(existing.model, "stable-model")
        self.assertEqual(dao.saved, [])

    async def test_update_provider_set_default_clears_other_defaults(self):
        existing = StubLLMProvider(
            id="provider-4",
            name="old-name",
            base_url="https://stable.example.com/v1",
            api_keys=["sk-stable"],
            model="stable-model",
            user_id="alice",
            is_default=False,
        )
        dao = FakeDao(provider_by_id=existing)

        async def fake_probe(api_key, base_url, model):
            return {"supported": True}

        self.module.LLMProviderDao = lambda: dao
        self.module.probe_connection = fake_probe

        await self.module.update_provider(
            "provider-4",
            self.module.LLMProviderUpdate(is_default=True),
            user_id="alice",
            allow_system_default_update=True,
        )

        self.assertEqual(
            dao.cleared_defaults,
            [{"user_id": "alice", "exclude_provider_id": "provider-4"}],
        )
        self.assertEqual(len(dao.saved), 1)
        self.assertTrue(existing.is_default)


class TestProviderProbeFriendlyError(unittest.TestCase):
    def test_friendly_error_uses_subject_prefix(self):
        message = friendly_provider_probe_error(RuntimeError("401 unauthorized"), subject="Default provider")
        self.assertEqual(message, "Default provider authentication failed. Please check the API key.")


if __name__ == "__main__":
    unittest.main()
