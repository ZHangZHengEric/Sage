from io import BytesIO
import json
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from app.v2.server.observability.diagnostics import REDACTED, SessionDiagnostics, redact
from app.v2.server.storage.downloads import prepare_session_export
from sagents.v2.runtime.observability.contracts import LogRecord
from tests.app.v2.server.test_file_downloads import identity, _run_input


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


def test_bundle_contains_actual_tool_proposal_and_result_and_legacy_gaps():
    events = [
        {
            "type": "tool.call.proposed",
            "data": {
                "tool_name": "todo_write",
                "tool_call_id": "t",
                "arguments": {"session_id": "external_old", "password": "hidden"},
            },
        },
        {
            "type": "tool.call.succeeded",
            "data": {"tool_name": "todo_write", "tool_call_id": "t"},
        },
        {
            "type": "item.completed",
            "data": {
                "item": {"data": {"tool_call_id": "t", "content": [{"text": "done"}]}}
            },
        },
        {
            "type": "tool.call.proposed",
            "data": {
                "tool_name": "mcp__remote",
                "tool_call_id": "m",
                "arguments": {"session_id": "external_old"},
            },
        },
        {
            "type": "tool.call.failed",
            "data": {"tool_call_id": "m", "error": {"message": "Bearer hidden"}},
        },
    ]
    state = {
        "sessions": [{"session_id": "external_old"}],
        "runs": [{"session_id": "external_old", "run_id": "r"}],
        "run_events": {"r": events},
    }
    stream, name = prepare_session_export("external_old", state)
    try:
        assert name.endswith("-diagnostics.zip")
        with ZipFile(stream) as archive:
            tools = json.loads(archive.read("external_old/tools.json"))
            assert len(tools) == 5
            assert (
                tools[0]["event"]["data"]["arguments"]["session_id"] == "external_old"
            )
            assert (
                tools[2]["event"]["data"]["item"]["data"]["content"][0]["text"]
                == "done"
            )
            assert b"hidden" not in b"".join(
                archive.read(n) for n in archive.namelist()
            )
            manifest = json.loads(archive.read("external_old/manifest.json"))
            assert manifest["models_missing_for_runs"] == ["r"]
            assert manifest["restorable_backup"] is False
            assert manifest["tool_failures"] == 1
            assert manifest["tool_failures_without_stack_trace"] == [
                {"run_id": "r", "tool_call_id": "m"}
            ]
            failures = json.loads(archive.read("external_old/failures.json"))
            assert failures[0]["stack_trace_available"] is False
            assert failures[0]["exceptions"] == []
    finally:
        stream.close()
    with pytest.raises(ValueError, match="identity mismatch"):
        prepare_session_export("other", state)


def admin_headers(client):
    token = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin12345"}
    ).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


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
        _step(1, "", "analyze_image", {"image_path": "/workspace/frame.png"}),
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
            state = archive.read("thread-1/state.json")
            assert b"broken_image_encoder" not in state
            assert b"stack_trace" not in state
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
    store = service.application.entrypoint().runtime.session_store
    state = client.portal.call(store.export_session_state, legacy_id)
    for run in state["runs"]:
        run["start_command"]["config"]["metadata"].pop(
            "server_v2.workspace_user_id", None
        )
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
    monkeypatch.setattr(store, "export_session_state", AsyncMock(return_value=state))
    response = client.get(
        f"/api/threads/{legacy_id}/download", headers=admin_headers(client)
    )
    assert response.status_code == 200, response.text
    with ZipFile(BytesIO(response.content)) as archive:
        assert (
            json.loads(archive.read(f"{legacy_id}/manifest.json"))["session_id"]
            == legacy_id
        )
