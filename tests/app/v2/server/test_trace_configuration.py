"""Tracing selection, credential references and console authorization."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.v2.server.config.manifest import server_v2_manifest
from app.v2.server.config.settings import ServerSettings
from app.v2.server.main import create_app
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from tests.app.v2.server.conftest import make_settings, make_test_service


def test_langfuse_config_contains_only_credential_references(tmp_path, monkeypatch):
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-never-in-manifest")
    settings = make_settings(
        tmp_path, trace_backend="langfuse", langfuse_base_url="https://lf.example"
    )
    manifest = server_v2_manifest(settings)
    selection = manifest.runtime.capabilities["observability.trace-sink"]
    assert selection.plugin == "sage.trace.langfuse"
    assert selection.config["secret_key_env"] == "LANGFUSE_SECRET_KEY"
    assert "sk-never-in-manifest" not in manifest.model_dump_json()
    registration = builtin_extension_registry().get(selection.plugin)
    assert registration.descriptor.config_schema["required"] == ["base_url"]


def test_trace_env_settings_and_explicit_noop_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_SERVER_MYSQL_URL", "mysql://localhost/db")
    monkeypatch.setenv("SAGE_SERVER_TRACE_BACKEND", "langfuse")
    monkeypatch.setenv("SAGE_SERVER_LANGFUSE_BASE_URL", "https://lf.example")
    monkeypatch.setenv("SAGE_SERVER_TRACE_CONTENT_MODE", "metadata")
    monkeypatch.setenv("SAGE_SERVER_TRACE_SAMPLE_RATE", "0.25")
    settings = ServerSettings.from_env(data_root=tmp_path)
    assert settings.effective_trace_backend == "langfuse"
    assert settings.trace_content_mode == "metadata"
    assert settings.trace_sample_rate == 0.25
    disabled = make_settings(
        tmp_path, trace_backend="noop", jaeger_url="http://localhost:4317"
    )
    assert disabled.effective_trace_backend == "noop"
    assert (
        "observability.trace-sink"
        not in server_v2_manifest(disabled).runtime.capabilities
    )
    assert not disabled.trace_console_url


@pytest.mark.parametrize(
    "options",
    [
        {"trace_backend": "unknown"},
        {"trace_backend": "otlp"},
        {"trace_backend": "langfuse"},
        {"trace_sample_rate": 2},
        {"trace_content_mode": "raw"},
        {"trace_max_content_chars": 1},
    ],
)
def test_invalid_trace_settings_fail_at_startup(tmp_path, options):
    with pytest.raises(ValueError):
        make_settings(tmp_path, **options)


def test_generic_otlp_http_configuration(tmp_path):
    manifest = server_v2_manifest(
        make_settings(
            tmp_path,
            trace_backend="otlp",
            trace_otlp_endpoint="https://collector.example/v1/traces",
            trace_otlp_protocol="http",
        )
    )
    config = manifest.runtime.capabilities["observability.trace-sink"].config
    assert config["protocol"] == "http"
    assert config["endpoint"] == "https://collector.example/v1/traces"
    assert config["insecure"] is False


def test_langfuse_health_and_admin_console(tmp_path: Path, monkeypatch):
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    # Host startup really constructs the registered plugin; no external I/O is
    # needed until a Run emits spans.
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    service = make_test_service(
        tmp_path,
        trace_backend="langfuse",
        langfuse_base_url="https://internal.example",
        langfuse_public_url="https://lf.example/project/p",
    )
    with TestClient(create_app(service=service)) as client:
        health = client.get("/health").json()["data"]
        assert health["trace_enabled"] is True
        assert health["trace_backend"] == "langfuse"
        assert health["trace_console"] is True
        metrics = client.get("/metrics").text
        assert "trace_failed_exports" in metrics
        assert "trace_dropped_spans" in metrics
        spec = client.get("/openapi.json").json()
        assert "/api/observability/jaeger" not in spec["paths"]
        assert (
            client.get("/api/observability/console", follow_redirects=False).status_code
            == 401
        )
        response = client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin12345"}
        )
        assert response.status_code == 200
        response = client.get("/api/observability/console", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "https://lf.example/project/p"
