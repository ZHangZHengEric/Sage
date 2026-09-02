from pathlib import Path

from sagents.v2.runtime.observability import StdoutLogSink

from app.server_v2.services.package import server_v2_manifest
from tests.app.server_v2.conftest import make_settings, make_test_service


def _stdout_log_sink(manifest):
    return manifest.runtime.capabilities["observability.log-sink"]


def test_package_has_no_yaml_credentials_or_model_routes():
    manifest = server_v2_manifest()
    assert manifest.credentials == {}
    assert manifest.models == {}
    assert manifest.entrypoint.agent == "main"
    assert manifest.interfaces["ag_ui"].plugin == "sage.protocol.ag-ui"
    log_sink = _stdout_log_sink(manifest)
    assert log_sink.plugin == "sage.logging.stdout"
    assert log_sink.config == {
        "stream": "stdout",
        "min_level": "info",
        "format": "json",
    }
    assert list(manifest.runtime.capabilities) == ["observability.log-sink"]


def test_package_always_registers_stdout_log_sink(tmp_path: Path):
    log_sink = _stdout_log_sink(server_v2_manifest(make_settings(tmp_path)))
    assert log_sink.plugin == "sage.logging.stdout"
    assert log_sink.config["stream"] == "stdout"


def test_package_selects_mysql_and_otlp_from_host_settings(tmp_path: Path):
    manifest = server_v2_manifest(
        make_settings(
            tmp_path,
            mysql_url="mysql://sage:sage@127.0.0.1:3306/sage",
            jaeger_url="http://sage-jaeger:4317",
            jaeger_service_name="sage-server",
        )
    )
    session = manifest.runtime.capabilities["session.store"]
    assert session.plugin == "sage.session.mysql"
    assert session.config == {
        "dsn": "mysql://sage:sage@127.0.0.1:3306/sage",
        "table_prefix": "",
    }
    assert _stdout_log_sink(manifest).plugin == "sage.logging.stdout"
    trace = manifest.runtime.capabilities["observability.trace-sink"]
    assert trace.plugin == "sage.trace.otlp"
    assert trace.config == {
        "endpoint": "http://sage-jaeger:4317",
        "service_name": "sage-server",
        "protocol": "grpc",
        "insecure": True,
    }


def test_package_skips_jaeger_when_endpoint_missing(tmp_path: Path):
    manifest = server_v2_manifest(
        make_settings(
            tmp_path,
            mysql_url="mysql://sage:sage@127.0.0.1:3306/sage",
        )
    )
    assert "observability.trace-sink" not in manifest.runtime.capabilities
    assert manifest.runtime.capabilities["session.store"].plugin == "sage.session.mysql"
    assert _stdout_log_sink(manifest).plugin == "sage.logging.stdout"


async def test_start_writes_sagents_registration_to_stdout(tmp_path: Path, capsys):
    service = make_test_service(tmp_path)
    await service.start()
    try:
        sink = service.application.service("observability.log-sink")
        assert isinstance(sink, StdoutLogSink)
        assert sink.stream == "stdout"
        assert service.backends()["log"] == "stdout"
        rows = [
            __import__("json").loads(line)
            for line in capsys.readouterr().out.splitlines()
            if '"format_version":"sage.log/v1"' in line
        ]
        registered = next(row for row in rows if row["event"] == "sagents.registered")
        assert registered["attributes"]["plugins"]
        assert sink.format == "json"
    finally:
        await service.close()
