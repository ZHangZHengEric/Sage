"""Shared APP catalog selection and real runtime route/credential wiring."""
import argparse
import json
import os

import pytest

from app.v2.cli import config
from app.v2.cli.app_model import APP_CREDENTIAL_ENV
from app.v2.cli.commands import resolve_package, resolve_models
from app.v2.cli.errors import CLIError


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith("SAGE_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SAGE_LOCAL_DATA_ROOT", str(tmp_path / "cli-data"))
    monkeypatch.setenv("SAGE_DESKTOP_DATA_ROOT", str(tmp_path / "app-data"))
    monkeypatch.setenv(APP_CREDENTIAL_ENV, "stale-process-key")
    path = tmp_path / "app-data" / "runtime" / "desktop-catalog.json"
    path.parent.mkdir(parents=True)
    providers = [
        {"id": "other", "user_id": "another-user", "is_default": True,
         "model": "private-model", "api_key": "other-key", "base_url": "https://other.example/v1"},
        {"id": "first", "user_id": "default_user", "is_default": False,
         "model": "chat-model", "api_key": "chat-key", "base_url": "https://chat.example/v1",
         "protocol": "openai-chat-completions"},
        {"id": "default", "user_id": "default_user", "is_default": True,
         "model": "responses-model", "api_key": "app-secret", "base_url": "https://responses.example/v1",
         "protocol": "openai-responses", "max_tokens": 777, "max_model_len": 32000,
         "temperature": 0.2, "supports_tool_calling": False},
    ]
    def save():
        path.write_text(json.dumps({"format_version": "sage.desktop-catalog/v2", "model_providers": providers}))
    save()
    return path, providers, save


def package():
    cfg = config.configure_cli_logging(verbose=False)
    return resolve_models(argparse.Namespace(models=None, package=None, preset="coder", user_id="default_user"), cfg)


def test_defaults_share_app_route_and_keep_credentials_out_of_manifest(catalog):
    manifest = package()
    route = manifest.models["primary"]
    assert route.provider == "openai-responses"
    assert route.model == "responses-model"
    assert route.base_url == "https://responses.example/v1"
    assert route.request.max_output_tokens == 777
    assert route.request.temperature == 0.2
    assert route.limits.context_window == 32000
    assert not route.capabilities.tool_calling
    assert manifest.credentials[route.credential].key == APP_CREDENTIAL_ENV
    assert os.environ[APP_CREDENTIAL_ENV] == "app-secret"
    assert "app-secret" not in manifest.model_dump_json()


def test_app_default_changes_are_read_on_next_invocation(catalog):
    path, providers, save = catalog
    package()
    providers[1]["is_default"] = True
    providers[2]["is_default"] = False
    save()
    assert package().models["primary"].model == "chat-model"
    assert os.environ[APP_CREDENTIAL_ENV] == "chat-key"
    assert json.loads(path.read_text())["model_providers"] == providers


def test_user_scope_never_falls_back_to_another_users_model(catalog):
    assert config.app_default_model("missing-user") is None
    assert config.app_default_model("another-user")["model"] == "private-model"


def test_explicit_environment_route_overrides_app(catalog, monkeypatch):
    monkeypatch.setenv("SAGE_DEFAULT_LLM_MODEL_NAME", "explicit-model")
    monkeypatch.setenv("SAGE_DEFAULT_LLM_API_BASE_URL", "https://explicit.example/v1")
    monkeypatch.setenv("SAGE_DEFAULT_LLM_API_KEY", "explicit-key")
    route = package().models["primary"]
    assert route.model == "explicit-model"
    assert route.base_url == "https://explicit.example/v1"
    assert os.environ[APP_CREDENTIAL_ENV] == "stale-process-key"


def test_model_name_override_reuses_app_protocol_and_credentials(catalog, monkeypatch):
    monkeypatch.setenv("SAGE_DEFAULT_LLM_MODEL_NAME", "selected-model")
    route = package().models["primary"]
    assert route.model == "selected-model"
    assert route.provider == "openai-responses"
    assert route.base_url == "https://responses.example/v1"
    assert os.environ[APP_CREDENTIAL_ENV] == "app-secret"


def test_custom_package_bypasses_app_catalog(catalog, monkeypatch):
    path, _, _ = catalog
    path.write_text("invalid JSON")
    sentinel = object()
    monkeypatch.setattr("app.v2.cli.commands.load_package", lambda _: sentinel)
    cfg = config.configure_cli_logging(verbose=False)
    assert resolve_package(argparse.Namespace(package="custom.yaml"), cfg) is sentinel


@pytest.mark.parametrize("broken", ["invalid JSON", '{"format_version":"wrong"}'])
def test_invalid_catalog_reports_configuration_error(catalog, broken):
    path, _, _ = catalog
    path.write_text(broken)
    with pytest.raises(CLIError, match="APP v2 model configuration"):
        package()


def test_incomplete_app_default_does_not_silently_pick_another_model(catalog):
    _, providers, save = catalog
    providers[2]["api_key"] = ""
    save()
    with pytest.raises(CLIError, match="APP v2 model configuration"):
        package()
