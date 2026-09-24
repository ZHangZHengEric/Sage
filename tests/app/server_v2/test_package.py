import json
import logging
from pathlib import Path

import pytest
from sagents.v2.runtime.observability import StructuredLogger, structured_log_context

from app.server_v2.main import create_app
from app.server_v2.application.manifest import server_v2_manifest
from app.server_v2.core.observability.logging import ServerLogSink, get_logger
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


def test_package_requires_the_store_guarantees_the_server_depends_on(tmp_path: Path):
    guarantees = server_v2_manifest().runtime.required_guarantees["session.store"]
    assert guarantees == {
        "transactional_run_events": True,
        "transactional_suspension": True,
        "supports_actor_authorization": True,
    }
    durable = server_v2_manifest(
        make_settings(tmp_path, mysql_url="mysql://sage:sage@127.0.0.1:3306/sage")
    ).runtime.required_guarantees["session.store"]
    assert durable["durable_across_process_restart"] is True


async def test_lifespan_closes_runtime_when_runtime_start_fails(
    tmp_path: Path, monkeypatch
):
    service = make_test_service(tmp_path)
    closed = False

    async def fail_start():
        raise RuntimeError("runtime start failed")

    async def close():
        nonlocal closed
        closed = True

    monkeypatch.setattr(service, "start", fail_start)
    monkeypatch.setattr(service, "close", close)
    application = create_app(service=service)

    with pytest.raises(RuntimeError, match="runtime start failed"):
        async with application.router.lifespan_context(application):
            pass

    assert closed is True


async def test_start_writes_sagents_registration_to_stdout(tmp_path: Path, capsys):
    service = make_test_service(tmp_path, log_directory=str(tmp_path / "logs"))
    await service.start()
    try:
        sink = service.application.service("observability.log-sink")
        assert isinstance(sink, ServerLogSink)
        assert sink.stdout.stream == "stdout"
        assert service.agent_management.package_builder_factory.log_sink is sink
        rows = [
            __import__("json").loads(line)
            for line in capsys.readouterr().out.splitlines()
            if '"format_version":"sage.log/v1"' in line
        ]
        registered = next(row for row in rows if row["event"] == "sagents.registered")
        assert registered["attributes"]["plugins"]
        assert sink.stdout.format == "json"
    finally:
        await service.close()


async def test_host_and_sagents_logs_share_record_and_outputs(tmp_path: Path, capsys):
    service = make_test_service(tmp_path, log_directory=str(tmp_path / "logs"))
    await service.start()
    try:
        sink = service.application.service("observability.log-sink")
        capsys.readouterr()
        with structured_log_context(request_id="request-123"):
            logging.getLogger("test.host").info("host message")
            get_logger("test.server").info("server.event", "server message")
            get_logger("sagents.v2.test").info("runtime.event", "runtime message")
            StructuredLogger(sink, "test.agent").info("agent.event", "agent message")
        stdout = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        file_rows = [
            json.loads(line)
            for line in (tmp_path / "logs" / "sage-server.log").read_text().splitlines()
        ]
        for event in ("python.log", "server.event", "runtime.event", "agent.event"):
            row = next(item for item in stdout if item["event"] == event)
            assert row in file_rows
            assert row["format_version"] == "sage.log/v1"
            assert row["request_id"] == "request-123"
    finally:
        await service.close()


async def test_log_level_and_text_format_apply_to_both_outputs(tmp_path: Path, capsys):
    service = make_test_service(
        tmp_path,
        log_level="warning",
        log_format="text",
        log_directory=str(tmp_path / "logs"),
    )
    await service.start()
    try:
        sink = service.application.service("observability.log-sink")
        capsys.readouterr()
        logging.getLogger("test.host").info("filtered host message")
        logging.getLogger("test.host").warning("host warning")
        StructuredLogger(sink, "test.agent").info("agent.filtered", "filtered agent message")
        StructuredLogger(sink, "test.agent").warning("agent.warning", "agent warning")
        stdout = capsys.readouterr().out
        file_text = (tmp_path / "logs" / "sage-server.log").read_text()
        assert stdout == file_text
        assert "host warning" in stdout
        assert "agent warning" in stdout
        assert "filtered host message" not in stdout
        assert "filtered agent message" not in stdout
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_server_concurrency_settings_reach_runtime(tmp_path, monkeypatch):
    from app.server_v2.core.settings import ServerSettings

    monkeypatch.setenv("SAGE_SERVER_MYSQL_URL", "mysql://localhost/test")
    monkeypatch.setenv("SAGE_SERVER_MAX_CONCURRENT_RUNS", "24")
    monkeypatch.setenv("SAGE_SERVER_MAX_CONCURRENT_RUNS_PER_USER", "6")
    monkeypatch.setenv("SAGE_SERVER_MAX_PENDING_RUNS", "128")
    monkeypatch.setenv("SAGE_SERVER_MAX_MODEL_CLIENTS", "16")
    parsed = ServerSettings.from_env(data_root=tmp_path)
    service = make_test_service(
        tmp_path,
        max_concurrent_runs=parsed.max_concurrent_runs,
        max_concurrent_runs_per_user=parsed.max_concurrent_runs_per_user,
        max_pending_runs=parsed.max_pending_runs,
        max_model_clients=parsed.max_model_clients,
    )
    await service.start()
    try:
        dispatcher = service.application.service("execution.dispatcher")
        assert (await service.execution.model_pool.pool.snapshot())["max_clients"] == 16
        assert dispatcher.max_concurrent_runs == 24
        assert dispatcher.max_concurrent_runs_per_tenant == 6
        assert (await dispatcher.scheduler.capabilities()).max_pending_items == 128
    finally:
        await service.close()


@pytest.mark.parametrize(
    "field",
    [
        "max_concurrent_runs",
        "max_concurrent_runs_per_user",
        "max_pending_runs",
        "max_model_clients",
    ],
)
def test_server_rejects_nonpositive_concurrency(tmp_path, field):
    with pytest.raises(ValueError, match="positive"):
        make_settings(tmp_path, **{field: 0})
