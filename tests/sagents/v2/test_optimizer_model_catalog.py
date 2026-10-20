"""Model selection for opt-in examples never needs an application's settings."""

import json
from types import SimpleNamespace

import pytest

from examples.v2.model_catalog import load_model_provider


def write_catalog(tmp_path, records):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"model_providers": records}))
    return path


def provider(name, **overrides):
    return {
        "name": name,
        "protocol": "openai-responses",
        "model": "configured-model",
        "base_url": "https://model.example/v1",
        "api_key": "test-key",
        **overrides,
    }


def test_selects_default_provider_from_explicit_catalog(tmp_path):
    selected = provider("primary", is_default=True, max_model_len=32000)
    catalog = write_catalog(tmp_path, [provider("other"), selected])
    assert load_model_provider(catalog) == selected


def test_explicit_provider_overrides_catalog_default(tmp_path):
    selected = provider("chosen", model="another-model")
    catalog = write_catalog(tmp_path, [provider("primary", is_default=True), selected])
    assert load_model_provider(catalog, "chosen") == selected


@pytest.mark.parametrize(
    "records,name",
    [([], None), ([provider("other")], None), ([provider("other")], "missing"),
     ([provider("primary", is_default=True, api_key="")], None)],
)
def test_missing_selection_or_credentials_fails_before_model_calls(tmp_path, records, name):
    catalog = write_catalog(tmp_path, records)
    with pytest.raises(ValueError, match="configured provider with credentials is required"):
        load_model_provider(catalog, name)


@pytest.mark.asyncio
async def test_domain_benchmark_builds_with_catalog_model_and_credentials(tmp_path, monkeypatch):
    from examples.v2 import optimizer_domains as example

    selected = provider("chosen", model="another-model", max_model_len=32000)
    catalog = write_catalog(tmp_path, [selected])
    providers = []

    def make_provider(config, credential):
        providers.append(SimpleNamespace(config=config, credential=credential))
        return providers[-1]

    class ConfigurationCaptured(Exception):
        pass

    def capture_runner(*, builder_factory, authorize):
        package = example.AgentPackageBundle.model_validate({
            "manifest": example.BuiltinPackageFactory.create(
                "assistant", package_id="catalog-test",
            ).model_dump(mode="json"),
        })
        configuration = builder_factory(package, tmp_path / "runner", None)
        model = configuration.models["models"]["primary"]
        assert model["model"] == "another-model"
        assert model["base_url"] == selected["base_url"]
        assert model["limits"]["context_window"] == 32000
        assert providers[0].credential.secret.get_secret_value() == "test-key"
        assert providers[0].config.model == "another-model"
        raise ConfigurationCaptured

    monkeypatch.setattr(example, "OpenAIResponsesModelProvider", make_provider)
    monkeypatch.setattr(example, "IsolatedOptimizationRunner", capture_runner)
    with pytest.raises(ConfigurationCaptured):
        await example.run(SimpleNamespace(
            catalog=catalog, provider="chosen", revision=1, domain="support",
            preflight_probe=False, mode="instructions", output=tmp_path / "output",
        ))


@pytest.mark.asyncio
async def test_domain_benchmark_rejects_wrong_protocol_before_creating_output(tmp_path):
    from examples.v2 import optimizer_domains as example

    catalog = write_catalog(tmp_path, [provider(
        "primary", is_default=True, protocol="openai-chat-completions",
    )])
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="requires an openai-responses provider"):
        await example.run(SimpleNamespace(catalog=catalog, provider=None, output=output))
    assert not output.exists()
