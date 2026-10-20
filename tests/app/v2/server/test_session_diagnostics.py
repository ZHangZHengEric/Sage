from io import BytesIO
import json
from types import SimpleNamespace
from threading import Event
from zipfile import ZipFile

import pytest

from app.v2.server.observability.diagnostics import REDACTED, SessionDiagnostics, redact
from app.v2.server.storage.downloads import prepare_session_export
from sagents.v2.runtime.observability.contracts import LogRecord
from tests.app.v2.server.test_file_downloads import identity, _run_input


async def test_slow_diagnostics_do_not_block_model_or_log_producers(tmp_path, monkeypatch):
    import asyncio
    from tests.app.v2.server.conftest import scripted_hello
    from sagents.v2.model import ModelRequest, RecordingModelProvider

    sink = SessionDiagnostics(tmp_path / "private")
    entered, release = Event(), Event()
    update = sink._update

    def slow_update(*args):
        entered.set()
        assert release.wait(timeout=5)
        return update(*args)

    monkeypatch.setattr(sink, "_update", slow_update)
    async def session_id(_):
        return "session"
    model = RecordingModelProvider(scripted_hello(), sink=sink, session_id_resolver=session_id)
    request = ModelRequest(request_id="request", run_id="run", model_binding="primary", messages=())
    try:
        async def consume():
            return [event async for event in model.stream(request)]
        events = await asyncio.wait_for(consume(), timeout=1)
        assert events[-1].response.text == "hello"
        assert await asyncio.to_thread(entered.wait, 1)
        sink.write(LogRecord(level="debug", event="test", message="测试", component="test",
                             session_id="session", run_id="run"))
    finally:
        release.set()
        await sink.close()
    evidence = sink.snapshot("session", {"run"})
    assert evidence["models"][0]["status"] == "completed"
    assert evidence["models"][0]["first_token_at"]
    assert evidence["logs"][0]["message"] == "测试"


async def test_diagnostic_queue_is_bounded_and_reports_overflow(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setattr(SessionDiagnostics, "max_pending_writes", 2)
    sink = SessionDiagnostics(tmp_path / "private")
    entered, release = Event(), Event()
    update = sink._update

    def slow_update(*args):
        entered.set()
        assert release.wait(timeout=5)
        return update(*args)

    monkeypatch.setattr(sink, "_update", slow_update)
    request = SimpleNamespace(run_id="run", request_id="request", metadata={})
    try:
        await sink.begin_model_request(session_id="session", request=request, provider={}, wire_request={})
        assert await asyncio.to_thread(entered.wait, 1)
        await sink.complete_model_request(session_id="session", request=request,
            response=SimpleNamespace(model_dump=lambda **_: {"text": "done"}))
        sink.write(LogRecord(level="debug", event="test", message="测试", component="test",
                             session_id="session", run_id="run"))
        assert sink.capture_failures == 1
    finally:
        release.set()
        await sink.close()
    assert sink.snapshot("session", {"run"})["models"][0]["status"] == "completed"


async def test_large_model_stream_preserves_request_and_export_after_restart(tmp_path):
    sink = SessionDiagnostics(tmp_path / "private")
    request = SimpleNamespace(run_id="run-large", request_id="req-large", metadata={})
    await sink.begin_model_request(
        session_id="large", request=request, provider={},
        wire_request={"messages": ["Create the project"], "api_key": "never-export-this"},
    )
    # Reproduce the real long tool-output capture: each stream is within its
    # own budget, but their combined record exceeds the former 8 MiB limit.
    delta = "x" * (4 * 1024 * 1024 + 512 * 1024)
    stream = {"wire_events": [{"delta": delta}], "normalized_events": [{"text": delta}],
              "wire_capture_available": True, "dropped_wire_events": 0,
              "dropped_normalized_events": 0}
    await sink.record_model_stream(session_id="large", request=request, evidence=stream)
    await sink.complete_model_request(
        session_id="large", request=request,
        response=SimpleNamespace(model_dump=lambda **_: {"output": "saved"}),
    )
    await sink.close()
    evidence = SessionDiagnostics(tmp_path / "private").snapshot("large", {"run-large"})
    record = evidence["models"][0]
    assert record["request"]["messages"] == ["Create the project"]
    assert record["stream"] == stream
    assert record["status"] == "completed"
    assert record["purpose"] == "agent"
    assert not record.get("truncated")
    state = {"sessions": [{"session_id": "large"}],
             "runs": [{"session_id": "large", "run_id": "run-large"}]}
    output, _ = prepare_session_export("large", {"run-large"}, evidence)
    with output, ZipFile(output) as archive:
        index = json.loads(archive.read("large/requests/index.json"))
        exported = json.loads(archive.read("large/" + index[0]["path"]))
        assert exported["stream"] == stream
        assert "never-export-this" not in json.dumps(exported)
        manifest = json.loads(archive.read("large/manifest.json"))
        assert manifest["truncated_model_records"] == 0
        assert manifest["stream_evidence_missing_for_requests"] == []


def test_redaction_covers_nested_json_free_text_urls_and_sibling_secret():
    value = {
        "api_key": "arbitrary-value",
        "message": "failed arbitrary-value",
        "content": '{"password":"nested-value","result":"nested-value"}',
        "url": "mysql://alice:db-pass@localhost/db?access_token=query-pass",
        "error": "failed Bearer abc.def and api_key=another-value",
        "schema": {"properties": {"password": {"type": "string"}}},
    }
    result = json.dumps(redact(value))
    for secret in (
        "arbitrary-value",
        "nested-value",
        "db-pass",
        "query-pass",
        "abc.def",
        "another-value",
    ):
        assert secret not in result
    assert REDACTED in result
    assert redact(value) == redact(redact(value))


async def test_capture_survives_restart_is_scoped_and_reports_limits(tmp_path):
    sink = SessionDiagnostics(tmp_path / "private")
    request = SimpleNamespace(run_id="run-a", request_id="req", metadata={})
    await sink.begin_model_request(
        session_id="a",
        request=request,
        provider={},
        wire_request={"messages": ["hello"], "api_key": "very-secret"},
    )
    await sink.fail_model_request(
        session_id="a", request=request, error=ValueError("Bearer leaked-token")
    )
    sink.max_logs_per_run = 2
    for i in range(4):
        sink.write(
            LogRecord(
                level="info",
                event="test",
                message=f"event {i} password=log-secret",
                component="test",
                session_id="a",
                run_id="run-a",
            )
        )
    sink.write(
        LogRecord(
            level="info",
            event="test",
            message="OTHER TENANT",
            component="test",
            session_id="b",
            run_id="run-a",
        )
    )
    sink.write(
        LogRecord(
            level="info",
            event="test",
            message="UNRELATED RUN",
            component="test",
            session_id="a",
            run_id="run-b",
        )
    )
    await sink.close()
    sink = SessionDiagnostics(tmp_path / "private")
    evidence = sink.snapshot("a", {"run-a"})
    assert len(evidence["models"]) == 1
    assert evidence["models"][0]["status"] == "failed"
    assert len(evidence["logs"]) == 2
    assert evidence["dropped_logs"] == 2
    encoded = json.dumps(evidence)
    for value in (
        "very-secret",
        "leaked-token",
        "log-secret",
        "OTHER TENANT",
        "UNRELATED RUN",
    ):
        assert value not in encoded
    assert sink.snapshot("b", {"run-b"})["models"] == []
    assert (sink.path.stat().st_mode & 0o777) == 0o600
    assert (sink.path.parent.stat().st_mode & 0o777) == 0o700
    sink.max_record_bytes = 10
    await sink.begin_model_request(
        session_id="a", request=request, provider={}, wire_request={"large": "x" * 50}
    )
    truncated = sink.snapshot("a", {"run-a"})["models"][0]
    assert truncated["truncated"] is True
    assert truncated["run_id"] == "run-a"


def test_bundle_has_explicit_legacy_gaps_without_business_reconstruction():
    stream, name = prepare_session_export("external_old", {"r"})
    with stream, ZipFile(stream) as archive:
        assert name.endswith("-diagnostics.zip")
        assert json.loads(archive.read("external_old/tools.json")) == []
        assert json.loads(archive.read("external_old/failures.json")) == []
        manifest = json.loads(archive.read("external_old/manifest.json"))
        assert manifest["models_missing_for_runs"] == ["r"]
        assert manifest["restorable_backup"] is False
        assert manifest["diagnostic_storage_available"] is False
        assert manifest["tool_results_available"] is False
        assert "external_old/state.json" not in archive.namelist()


def admin_headers(client):
    token = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin12345"}
    ).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_direct_package_uses_server_model_diagnostics(client, service):
    from tests.app.v2.server.test_packages import settled

    headers = admin_headers(client)
    bundle = client.get("/api/agent-packages/template", headers=headers).json()["data"]
    saved = client.post("/api/agent-packages", headers=headers, json=bundle)
    assert saved.status_code == 200, saved.text
    response = client.post("/api/agent-packages/runs", headers=headers, json={
        "ref": saved.json()["data"]["ref"], "agent_id": "assistant",
        "content": "hello", "operation": "package-diagnostics",
    })
    assert response.status_code == 200, response.text
    state = settled(client, headers, "package-diagnostics")
    assert state["run"]["state"] == "completed", state
    run = state["run"]
    evidence = service.diagnostics.snapshot(run["session_id"], {run["run_id"]})
    records = evidence["models"]
    assert records, "Direct Package model calls must reach Server diagnostics"
    assert any(record["response"].get("text") == "hello" for record in records)
    assert all(record["request"] and record["status"] == "completed" for record in records)
    assert {record["purpose"] for record in records} >= {"agent", "continuation_judge"}
    session_id = run["session_id"]
    output, _ = prepare_session_export(session_id, {run["run_id"]}, evidence)
    with output, ZipFile(output) as archive:
        manifest = json.loads(archive.read(f"{session_id}/manifest.json"))
        assert manifest["model_records"] == len(records)
        assert not manifest["models_missing_for_runs"]
        index = json.loads(archive.read(f"{session_id}/requests/index.json"))
        assert len(index) == len(records)
        assert all(archive.read(f"{session_id}/" + entry["path"]) for entry in index)


def test_web_export_captures_real_model_response_and_correlated_logs(client, service):
    alice, _ = identity(client, "alice")
    assert (
        client.post("/api/agent", json=_run_input(), headers=alice).status_code == 200
    )
    response = client.get(
        "/api/threads/thread-1/download", headers=admin_headers(client)
    )
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        models = json.loads(archive.read("thread-1/models.json"))
        index = json.loads(archive.read("thread-1/requests/index.json"))
        assert len(index) == len(models)
        for attempt, model in zip(index, models, strict=True):
            assert json.loads(archive.read("thread-1/" + attempt["path"])) == model
            assert attempt["request_id"] == model["request_id"]
        assert any(row["response"].get("text") == "hello" for row in models)
        assert all(row["request"] and row["status"] == "completed" for row in models)
        logs = json.loads(archive.read("thread-1/logs.json"))
        assert any(row["event"] == "model.request.completed" for row in logs)
        assert all(row["session_id"] == "thread-1" for row in logs)
        manifest = json.loads(archive.read("thread-1/manifest.json"))
        assert not manifest["models_missing_for_runs"]
        assert not manifest["logs_missing_for_runs"]


@pytest.mark.timeout(30)
@pytest.mark.parametrize("typed_error", [False, True])
def test_web_export_captures_image_tool_exception_stack(tmp_path, monkeypatch, typed_error):
    from fastapi.testclient import TestClient
    from PIL import Image

    from app.v2.server.main import create_app
    from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from tests.app.v2.server.conftest import make_test_service
    from tests.app.v2.server.test_a2a_resume import _step

    def broken_image_encoder(image):
        if typed_error:
            raise SageV2Error(RuntimeErrorInfo(
                code="image.test_failure", category=ErrorCategory.PROVIDER_PERMANENT,
                message="encoder failed password=diagnostic-secret",
            ))
        callback = "encoder"
        callback()  # Reproduce the exact exception from the reported Session.

    monkeypatch.setattr(
        "sagents.v2.tool.official.media.compress_image_to_jpeg_bytes_for_llm",
        broken_image_encoder,
    )
    provider = ScriptedModelProvider((
        _step(1, "", "analyze_image", {"image_path": "frame.png"}),
        _step(2, "Image tool failed."),
    ))
    service = make_test_service(tmp_path, model_provider=provider)
    with TestClient(create_app(service=service)) as client:
        alice, owner = identity(client, "alice")
        agent = client.get("/api/agents", headers=alice).json()["data"][0]
        agent_id = agent["id"]
        updated = client.put(
            f"/api/agents/{agent_id}", headers=alice,
            json={"name": agent["name"], "tools": ["analyze_image"]},
        )
        assert updated.status_code == 200, updated.text
        root = service.paths.workspace_dir(owner, agent_id)
        Image.new("RGB", (32, 32), "red").save(root / "frame.png")
        response = client.post("/api/agent", json=_run_input(), headers=alice)
        assert response.status_code == 200, response.text
        download = client.get(
            "/api/threads/thread-1/download", headers=admin_headers(client)
        )
        assert download.status_code == 200, download.text
        with ZipFile(BytesIO(download.content)) as archive:
            failures = json.loads(archive.read("thread-1/failures.json"))
            assert len(failures) == 1
            failure = failures[0]
            assert failure["tool_name"] == "analyze_image"
            assert failure["stack_trace_available"]
            exception = failure["exceptions"][0]
            assert exception["type"] == ("SageV2Error" if typed_error else "TypeError")
            assert "broken_image_encoder" in exception["stack_trace"]
            assert "media.py" in exception["stack_trace"]
            if not typed_error:
                assert "'str' object is not callable" in exception["stack_trace"]
            logs = json.loads(archive.read("thread-1/logs.json"))
            log = next(row for row in logs if row["event"] == "tool.execution.exception")
            assert log["session_id"] == "thread-1"
            assert log["run_id"] == failure["run_id"]
            assert log["tool_call_id"] == failure["tool_call_id"]
            assert log["step_id"] and log["turn_id"]
            manifest = json.loads(archive.read("thread-1/manifest.json"))
            assert not manifest["tool_failures_without_stack_trace"]
            assert not manifest["logs_missing_for_runs"]
            assert "thread-1/state.json" not in archive.namelist()
            assert b"diagnostic-secret" not in b"".join(
                archive.read(name) for name in archive.namelist()
            )


def test_download_is_admin_only_and_excludes_other_sessions(client, service):
    alice, _ = identity(client, "alice")
    bob, _ = identity(client, "bob")
    assert (
        client.post("/api/agent", json=_run_input(), headers=alice).status_code == 200
    )
    assert (
        client.post(
            "/api/agent",
            json={**_run_input(), "threadId": "bob-session", "runId": "bob-run"},
            headers=bob,
        ).status_code
        == 200
    )
    assert client.get("/api/threads/thread-1/download", headers=bob).status_code == 403
    service.diagnostics.write(
        LogRecord(
            level="info",
            event="test",
            message="BOB PRIVATE EVIDENCE",
            component="test",
            session_id="bob-session",
            run_id="run-1",
        )
    )
    response = client.get(
        "/api/threads/thread-1/download", headers=admin_headers(client)
    )
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        combined = b"".join(archive.read(n) for n in archive.namelist())
        assert b"bob-session" not in combined
        assert b"BOB PRIVATE EVIDENCE" not in combined


@pytest.mark.parametrize("mismatch", ["owner", "agent", "tenant"])
def test_owner_or_agent_mismatch_fails_before_reading_diagnostics(
    client, service, monkeypatch, mismatch
):
    from unittest.mock import AsyncMock, Mock
    from app.v2.server.conversations.bindings import SessionBinding

    alice, owner = identity(client, "alice")
    assert (
        client.post("/api/agent", json=_run_input(), headers=alice).status_code == 200
    )
    record = client.portal.call(service.threads.find, "thread-1")
    monkeypatch.setattr(
        service.threads,
        "binding",
        AsyncMock(
            return_value=SessionBinding(
                "thread-1",
                "other-owner" if mismatch == "owner" else owner,
                "other-tenant" if mismatch == "tenant" else owner,
                "different-agent" if mismatch == "agent" else record.agent_id,
            )
        ),
    )
    snapshot = Mock(side_effect=AssertionError("diagnostics must not be read"))
    monkeypatch.setattr(service.diagnostics, "snapshot", snapshot)
    assert (
        client.get(
            "/api/threads/thread-1/download", headers=admin_headers(client)
        ).status_code
        == 404
    )
    snapshot.assert_not_called()


async def test_diagnostic_failure_does_not_stop_model_stream(tmp_path, monkeypatch):
    from sagents.v2.model.middleware.recording import RecordingModelProvider
    from tests.app.v2.server.conftest import scripted_hello
    from sagents.v2.model.contracts import ModelRequest

    sink = SessionDiagnostics(tmp_path / "private")
    monkeypatch.setattr(
        sink, "_connect", lambda: (_ for _ in ()).throw(OSError("disk full"))
    )

    async def session_id(run_id):
        return "session"

    model = RecordingModelProvider(
        scripted_hello(), sink=sink, session_id_resolver=session_id
    )
    request = ModelRequest(
        request_id="r", run_id="run", model_binding="primary", messages=()
    )
    events = [event async for event in model.stream(request)]
    assert events[-1].response.text == "hello"
    await sink.close()
    assert sink.capture_failures > 0


def test_corrupt_diagnostic_database_does_not_block_startup_or_download(tmp_path):
    root = tmp_path / "private"
    root.mkdir()
    (root / "evidence.sqlite3").write_bytes(b"broken database")
    sink = SessionDiagnostics(root)
    assert not sink.available
    assert sink.snapshot("s", {"r"})["unavailable"]


def test_legacy_binding_without_run_tenant_metadata_remains_downloadable(
    client, service, monkeypatch
):
    from unittest.mock import AsyncMock
    from app.v2.server.conversations.bindings import SessionBinding

    alice, owner = identity(client, "alice")
    legacy_id = "external_" + "a" * 64
    assert (
        client.post(
            "/api/agent", json={**_run_input(), "threadId": legacy_id}, headers=alice
        ).status_code
        == 200
    )
    access = service.conversations.session_access
    context = service.conversations.context_for(owner)
    runs = client.portal.call(access.list_session_runs, legacy_id, context)
    command = client.portal.call(access.get_start_command, runs[0].run_id, context)
    metadata = dict(command.config.metadata)
    metadata.pop("server_v2.workspace_user_id", None)
    monkeypatch.setattr(access, "get_start_command", AsyncMock(return_value=command.model_copy(
        update={"config": command.config.model_copy(update={"metadata": metadata})})))
    record = client.portal.call(service.threads.find, legacy_id)
    monkeypatch.setattr(
        service.threads,
        "binding",
        AsyncMock(
            return_value=SessionBinding(
                legacy_id, owner, "historical-business-tenant", record.agent_id
            )
        ),
    )
    response = client.get(
        f"/api/threads/{legacy_id}/download", headers=admin_headers(client)
    )
    assert response.status_code == 200, response.text
    with ZipFile(BytesIO(response.content)) as archive:
        assert (
            json.loads(archive.read(f"{legacy_id}/manifest.json"))["session_id"]
            == legacy_id
        )


def test_repeated_stream_redaction_is_scoped_to_each_snapshot():
    # Repeated wire/normalized payloads may be reused inside one call, but the
    # same text in another Session must use that Session's discovered secrets.
    payload = "ordinary-value " + "x" * (128 * 1024)
    original = {"wire": payload, "normalized": payload}
    first = redact({"password": "ordinary-value", **original})
    assert first["wire"] == first["normalized"] == payload.replace("ordinary-value", REDACTED)
    assert redact(original) == original
    assert original["wire"] == payload


def test_repeated_embedded_json_still_redacts_secrets_in_sibling_text():
    embedded = '{"password":"embedded-value","message":"embedded-value"}'
    result = redact({"wire": embedded, "normalized": embedded, "message": "embedded-value"})
    assert result["wire"] == result["normalized"]
    assert "embedded-value" not in json.dumps(result)
    assert result["message"] == REDACTED
