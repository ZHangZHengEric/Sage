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
        server_v2_manifest(disabled).runtime.capabilities["observability.trace-sink"].plugin
        == "sage.trace.noop"
    )
    assert not disabled.trace_console_url


@pytest.mark.parametrize(
    "options",
    [
        {"trace_backend": "unknown"},
        {"trace_backend": "otlp"},
        {"trace_backend": "langfuse"},
        {"trace_backend": "phoenix"},
        {"trace_sample_rate": 2},
        {"trace_content_mode": "unknown"},
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


@pytest.mark.parametrize("backend", ["langfuse", "phoenix"])
def test_trace_health_and_admin_console(tmp_path: Path, monkeypatch, backend):
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    # Host startup really constructs the registered plugin; no external I/O is
    # needed until a Run emits spans.
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    service = make_test_service(
        tmp_path,
        trace_backend=backend,
        phoenix_endpoint="http://localhost:6006/v1/traces",
        phoenix_public_url="https://phoenix.example/projects/p",
        langfuse_base_url="https://internal.example",
        langfuse_public_url="https://lf.example/project/p",
    )
    with TestClient(create_app(service=service)) as client:
        health = client.get("/health").json()["data"]
        assert health["trace_enabled"] is True
        assert health["trace_backend"] == backend
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
        assert response.headers["location"] == (
            "https://lf.example/project/p" if backend == "langfuse"
            else "/traces"
        )


def test_phoenix_environment_manifest_and_admin_selection(tmp_path, monkeypatch):
    from app.v2.server.config.plugins import ServerPluginConfig, revision

    monkeypatch.setenv("SAGE_SERVER_MYSQL_URL", "mysql://localhost/db")
    monkeypatch.setenv("SAGE_SERVER_TRACE_BACKEND", "phoenix")
    monkeypatch.setenv("SAGE_SERVER_PHOENIX_ENDPOINT", "https://phoenix.example/v1/traces")
    monkeypatch.setenv("SAGE_SERVER_PHOENIX_PROJECT_NAME", "sage-test")
    monkeypatch.setenv("SAGE_SERVER_PHOENIX_API_KEY_ENV", "CUSTOM_PHOENIX_KEY")
    monkeypatch.setenv("CUSTOM_PHOENIX_KEY", "never-save-this-key")
    settings = ServerSettings.from_env(data_root=tmp_path)
    manifest = server_v2_manifest(settings)
    selection = manifest.runtime.capabilities["observability.trace-sink"]
    assert selection.plugin == "sage.trace.phoenix"
    assert selection.config["project_name"] == "sage-test"
    assert selection.config["api_key_env"] == "CUSTOM_PHOENIX_KEY"
    assert not settings.trace_console_url
    assert "never-save-this-key" not in manifest.model_dump_json()
    store = ServerPluginConfig(tmp_path)
    saved = store.save(
        {"observability.trace-sink": selection.model_dump(mode="json")}, revision({})
    )
    assert store.read() == saved
    assert "never-save-this-key" not in store.path.read_text()
    assert builtin_extension_registry().get(selection.plugin).descriptor.config_schema["required"] == ["endpoint"]


@pytest.mark.parametrize(
    "options, console",
    [
        ({"trace_backend": "noop"}, None),
        ({"trace_backend": "phoenix", "phoenix_endpoint": "http://internal/v1/traces",
          "phoenix_public_url": "https://phoenix.example"}, None),
        ({"trace_backend": "phoenix", "phoenix_endpoint": "http://internal/v1/traces"}, None),
        ({"trace_backend": "langfuse", "langfuse_base_url": "https://lf.example"},
         ("langfuse", "Langfuse", "https://lf.example")),
        ({"jaeger_url": "http://internal:4317", "jaeger_public_url": "https://jaeger.example"},
         ("jaeger", "Jaeger", "https://jaeger.example")),
        ({"trace_backend": "otlp", "trace_otlp_endpoint": "http://collector:4317"}, None),
    ],
)
def test_observability_services_follow_active_backend(tmp_path, monkeypatch, options, console):
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    service = make_test_service(tmp_path, **options)
    with TestClient(create_app(service=service)) as client:
        assert client.get("/api/observability/services").status_code == 401
        client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"})
        response = client.get("/api/observability/services")
        assert response.status_code == 200
        links = response.json()["data"]
        assert links == [
            *([{"id": "performance", "label": "运行性能", "href": "/performance", "external": False}]
              if service.diagnostics.available else []),
            *([{"id": "traces", "label": "调用链", "href": "/traces", "external": False}]
              if options.get("trace_backend") == "phoenix" else []),
            *([{"id": console[0], "label": console[1], "href": console[2], "external": True}]
              if console else []),
        ]
        if console is None:
            redirect = client.get("/api/observability/console", follow_redirects=False)
            if options.get("trace_backend") == "phoenix":
                assert redirect.status_code == 307
                assert redirect.headers["location"] == "/traces"
            else:
                assert redirect.status_code == 404
        # Availability is live; failed diagnostic capture must not be advertised.
        service.diagnostics.available = False
        assert all(link["id"] != "performance" for link in client.get("/api/observability/services").json()["data"])


def test_observability_uses_started_plugin_and_rejects_non_admin(tmp_path):
    from app.v2.server.config.plugins import ServerPluginConfig, revision

    service = make_test_service(
        tmp_path, trace_backend="phoenix", phoenix_endpoint="http://internal/v1/traces",
        phoenix_public_url="https://phoenix.example",
    )
    ServerPluginConfig(tmp_path).save(
        {"observability.trace-sink": {"plugin": "sage.trace.noop"}}, revision({})
    )
    with TestClient(create_app(service=service)) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"})
        links = client.get("/api/observability/services").json()["data"]
        assert [link["id"] for link in links] == ["performance"]
        assert client.get("/api/observability/console", follow_redirects=False).status_code == 404
        client.post("/api/auth/register", json={"username": "viewer", "password": "viewer12345"})
        client.post("/api/auth/login", json={"username": "viewer", "password": "viewer12345"})
        assert client.get("/api/observability/services").status_code == 403
        assert client.get("/api/observability/console", follow_redirects=False).status_code == 403


@pytest.mark.parametrize("explicit,expected", [(None,"raw"),("redacted","redacted"),("metadata","metadata"),("raw","raw")])
def test_server_phoenix_defaults_to_full_raw_capture_with_explicit_override(tmp_path, explicit, expected):
    settings = make_settings(tmp_path, trace_backend="phoenix", phoenix_endpoint="http://phoenix/v1/traces",
                             trace_content_mode=explicit)
    assert server_v2_manifest(settings).runtime.capabilities["observability.trace-sink"].config["content_mode"] == expected


def test_server_saved_phoenix_selection_without_content_mode_inherits_raw_default(tmp_path):
    settings = make_settings(tmp_path, plugin_overrides={"observability.trace-sink":{
        "plugin":"sage.trace.phoenix", "config":{"endpoint":"http://phoenix/v1/traces"}}})
    assert server_v2_manifest(settings).runtime.capabilities["observability.trace-sink"].config["content_mode"] == "raw"


def test_server_other_trace_backends_keep_redacted_default(tmp_path):
    settings = make_settings(tmp_path, trace_backend="otlp", trace_otlp_endpoint="http://collector:4317")
    assert server_v2_manifest(settings).runtime.capabilities["observability.trace-sink"].config["content_mode"] == "redacted"
