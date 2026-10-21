"""One selected provider owns collection, evidence and lifecycle."""

from typing import cast
from sagents.v2.package.manifest.runtime import CapabilityBinding

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.runtime.observability.contracts import LogLevel
    from sagents.v2.runtime.observability.provider import ObservabilityProvider
    from typing import Any

import json

import pytest

from sagents.v2.package.manifest.runtime import RuntimeConfig
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.runtime.observability.provider import create_observability_provider
from sagents.v2.runtime.observability import LogRecord


@pytest.mark.parametrize(
    "capability",
    [
        "observability.log-sink",
        "observability.diagnostic-sink",
        "observability.trace-sink",
    ],
)
def test_removed_observation_capabilities_are_rejected(capability):
    with pytest.raises(ValueError, match="removed capability"):
        RuntimeConfig(capabilities=cast('dict[str, CapabilityBinding]', {capability: {"plugin": "custom.observer"}}))


def test_inventory_only_offers_unified_observation_plugins():
    descriptors = [
        item.descriptor for item in builtin_extension_registry().registrations()
    ]
    observed = [
        d
        for d in descriptors
        if any(o.capability.startswith("observability.") for o in d.provides)
    ]
    assert {d.plugin_id for d in observed} == {
        "sage.observability.local",
        "sage.observability.noop",
        "sage.observability.otlp",
        "sage.observability.langfuse",
        "sage.observability.phoenix",
    }
    assert all(
        {o.capability for o in d.provides} == {"observability.provider"}
        for d in observed
    )


@pytest.mark.asyncio
async def test_provider_keeps_process_logs_without_trace_and_owns_shutdown(
    tmp_path, capsys
):
    provider = create_observability_provider(
        "sage.observability.local",
        {
            "log_root": str(tmp_path / "logs"),
            "log_level": "warning",
            "diagnostics_root": str(tmp_path / "diagnostics"),
        },
    )
    provider.logs.write(
        LogRecord(level=cast('LogLevel', "info"), event="hidden", message="info", component="test")
    )
    provider.logs.write(
        LogRecord(
            level=cast('LogLevel', "error"), event="startup.failed", message="failed", component="test"
        )
    )
    await provider.close()
    await provider.close()
    assert provider.closed
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["event"] for r in rows] == ["startup.failed"]
    disk = [
        json.loads(line)
        for line in (tmp_path / "logs" / "sage.jsonl").read_text().splitlines()
    ]
    assert disk == rows


@pytest.mark.asyncio
async def test_raw_evidence_is_independent_of_trace_sampling_and_content(monkeypatch):
    from sagents.v2.runtime.observability import provider as module

    transports = []

    class Transport:
        def __init__(self, options):
            self.options, self.spans, self.closed = options, [], False

        def start_span(self, span):
            self.spans.append(span)

        def end_span(self, span):
            pass

        def close(self):
            self.closed = True

    def transport(backend, options):
        value = Transport(options)
        transports.append(value)
        return value

    monkeypatch.setattr(module, "_trace_backend", transport)
    provider = create_observability_provider(
        "sage.observability.phoenix",
        {
            "endpoint": "http://example/v1/traces",
            "sample_rate": 0,
            "content_mode": "metadata",
            "diagnostic_content_mode": "raw",
            "log_stdout": False,
        },
    )
    provider.logs.write(
        LogRecord(
            level=cast('LogLevel', "debug"),
            event="captured",
            message="raw model evidence",
            component="test",
            session_id="s",
            run_id="r",
        )
    )
    await getattr(provider.diagnostics, 'flush_raw')()
    await provider.close()
    assert len(transports) == 2
    assert transports[0].options.sample_rate == 0
    assert transports[1].options.sample_rate == 1
    assert transports[1].options.content_mode == "raw"
    assert any(span.name == "sage.diagnostic.record" for span in transports[1].spans)
    assert all(value.closed for value in transports)


@pytest.mark.asyncio
async def test_sqlite_evidence_retains_debug_independently_of_console_level(
    tmp_path, capsys
):
    provider = create_observability_provider(
        "sage.observability.local",
        {
            "log_level": "error",
            "diagnostics_storage": "sqlite",
            "diagnostics_root": str(tmp_path),
        },
    )
    provider.logs.write(
        LogRecord(
            level=cast('LogLevel', "debug"),
            event="model.request.completed",
            message="model done",
            component="test",
            session_id="owned",
            run_id="allowed",
        )
    )
    provider.logs.write(
        LogRecord(
            level=cast('LogLevel', "error"),
            event="other",
            message="other run",
            component="test",
            session_id="owned",
            run_id="excluded",
        )
    )
    evidence = await provider.export_evidence("owned", {"allowed"})
    assert [r["run_id"] for r in evidence["logs"]] == ["allowed"]
    assert capsys.readouterr().out.count("model done") == 0
    await provider.close()


@pytest.mark.asyncio
async def test_shutdown_flushes_evidence_before_exporters_and_closes_all_outputs():
    from sagents.v2.runtime.observability.provider import ObservabilityProvider

    closed = []

    class Evidence:
        async def close(self):
            closed.append("evidence")

    class Exporter:
        def close(self):
            closed.append("trace")

    class Output:
        def __init__(self, name, fail=False):
            self.name, self.fail = name, fail

        def close(self):
            closed.append(self.name)
            if self.fail:
                raise RuntimeError("output unavailable")

    provider = ObservabilityProvider(
        plugin_id="test.observation", diagnostics=Evidence(), traces=Exporter(),
        outputs=(Output("broken", fail=True), Output("remaining")),
    )
    with pytest.raises(ExceptionGroup):
        await provider.close()
    assert closed == ["evidence", "trace", "broken", "remaining"]
    await provider.close()
    assert len(closed) == 4


@pytest.mark.asyncio
async def test_model_history_queries_work_with_external_evidence_and_run_allowlist():
    from sagents.v2.runtime.observability.provider import ObservabilityProvider

    queried = []

    class ExternalEvidence:
        async def export_evidence(self, session_id, run_ids):
            queried.append((session_id, run_ids))
            return {"models": [{"request_id": "q", "run_id": "owned", "response": {"text": "result"}}]}

    provider = ObservabilityProvider(plugin_id="test.external", diagnostics=ExternalEvidence())
    assert await provider.list_model_requests(session_id="s", run_ids=set()) == ()
    request = await provider.get_model_request(session_id="s", run_id="owned", request_id="q")
    assert request["response"]["text"] == "result"
    assert queried == [("s", {"owned"})]
    with pytest.raises(KeyError):
        await provider.get_model_request(session_id="s", run_id="owned", request_id="unknown")
    await provider.close()


@pytest.mark.asyncio
async def test_desktop_same_provider_parameter_changes_require_restart(tmp_path):
    from app.v2.desktop.backend.service import DesktopV2Service
    from app.v2.desktop.backend.schemas import ComponentSelectionRequest

    service = DesktopV2Service(root=tmp_path)
    await service.start()
    try:
        selected = await service.select_component(
            "observability.provider",
            ComponentSelectionRequest(plugin_id="sage.observability.local", config={"log_level": "error"}),
            "owner",
        )
        assert selected["pending_restart"] is True
        assert cast("Any", service.observability).config["log_level"] == "info"
        entry = next(row for row in await service.component_inventory("owner")
                     if row["component"]["component_id"] == "observability.provider")
        assert entry["active"]["pending_restart"] is True
    finally:
        await service.close()
    restarted = DesktopV2Service(root=tmp_path)
    await restarted.start()
    try:
        assert cast("Any", restarted.observability).config["log_level"] == "error"
        entry = next(row for row in await restarted.component_inventory("owner")
                     if row["component"]["component_id"] == "observability.provider")
        assert entry["active"]["pending_restart"] is False
    finally:
        await restarted.close()
