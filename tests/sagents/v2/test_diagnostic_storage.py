"""Session-local media and nested diagnostics retain the complete safe request."""

import asyncio
import base64
import json
import shutil

import pytest

from sagents.v2.contracts.common import utc_now
from sagents.v2.model import ModelRequest, ModelResponse
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.observability.plugins.filesystem import FilesystemDiagnosticSink
from sagents.v2.runtime.observability.plugins.filesystem.media import DiagnosticMediaStore
from sagents.v2.runtime.session import FilesystemSessionStore
from sagents.v2.runtime.session.plugins._shared.filesystem_layout import resolve_session_directory
from tests.sagents.v2.test_delegated_task_session import child_command
from tests.sagents.v2.test_session_history_context_matrix import CONTEXT, command


def request(index):
    return ModelRequest(
        request_id=f"req{index}", run_id="run", model_binding="primary", messages=()
    )


@pytest.mark.asyncio
async def test_media_is_deduplicated_but_requests_restore_after_restart_and_export(
    tmp_path,
):
    sink = FilesystemDiagnosticSink(tmp_path / "sessions")
    uri = "data:image/png;base64," + base64.b64encode(b"image" * 5000).decode()
    wire = {
        "model": "m",
        "messages": [{"content": [{"type": "input_image", "image_url": uri}]}],
    }
    await asyncio.gather(
        *(
            sink.begin_model_request(
                session_id="s", request=request(i), provider={}, wire_request=wire
            )
            for i in range(4)
        )
    )
    for i in range(4):
        await sink.record_model_first_token(
            session_id="s", request=request(i), observed_at=utc_now()
        )
        await sink.complete_model_request(
            session_id="s",
            request=request(i),
            response=ModelResponse(
                response_id=str(i), text="done", finish_reason="stop"
            ),
        )
    owner = tmp_path / "sessions/s"
    blobs = list(owner.glob("diagnostics/media/*.txt"))
    records = list(owner.glob("runs/run/llm_requests/*.json"))
    assert len(blobs) == 1 and len(records) == 4
    assert all(uri not in path.read_text() for path in records)
    assert sum(p.stat().st_size for p in [*blobs, *records]) < len(uri) * 2
    # A Session can be exported alone, with no original root or parent needed.
    exported = tmp_path / "export/sessions/s"
    shutil.copytree(owner, exported)
    shutil.rmtree(tmp_path / "sessions")
    restarted = FilesystemDiagnosticSink(exported.parent)
    restored = await restarted.list_model_requests(session_id="s")
    assert len(restored) == 4
    assert all(r["request"] == wire and r["status"] == "completed" for r in restored)
    assert all("first_token_at" in r for r in restored)
    for i in range(4):
        value = await restarted.get_model_request(
            session_id="s", run_id="run", request_id=f"req{i}"
        )
        assert value["request"] == wire


@pytest.mark.asyncio
async def test_child_diagnostics_follow_store_location_after_restart_and_adopt_flat_logs(
    tmp_path,
):
    store = FilesystemSessionStore(tmp_path)
    runtime = HarnessRuntime(store)
    parent = await runtime.start_run(command("parent", "p"), CONTEXT)
    child = await runtime.start_run(child_command(parent), CONTEXT)
    grandchild = await runtime.start_run(child_command(child, "grandchild"), CONTEXT)
    owner = await store.session_directory(grandchild.session_id)
    assert (
        owner
        == tmp_path
        / "sessions"
        / parent.session_id
        / "sub_sessions"
        / child.session_id
        / "sub_sessions"
        / grandchild.session_id
    )
    await store.close()
    # Reproduce the old sink's misplaced record before the repaired sink opens.
    flat = tmp_path / "sessions" / grandchild.session_id
    misplaced = flat / "runs/run/llm_requests/00000000_agent_old.json"
    misplaced.parent.mkdir(parents=True)
    uri = "data:image/png;base64," + base64.b64encode(b"abc" * 200).decode()
    old = {
        "session_id": grandchild.session_id,
        "run_id": "run",
        "request_id": "old",
        "kind": "agent",
        "started_at": utc_now().isoformat(),
        "request": {"image": uri},
        "index": 0,
    }
    misplaced.write_text(json.dumps(old))
    sink = FilesystemDiagnosticSink(tmp_path / "sessions")
    assert (
        await sink.get_model_request(
            session_id=grandchild.session_id, run_id="run", request_id="old"
        )
    )["request"] == old["request"]
    await sink.begin_model_request(
        session_id=grandchild.session_id,
        request=request(1),
        provider={},
        wire_request={"image": uri},
    )
    assert not misplaced.exists()
    assert len(list(owner.glob("runs/run/llm_requests/*.json"))) == 2
    assert len(list(owner.glob("diagnostics/media/*.txt"))) == 1
    assert not list(flat.glob("runs/*/llm_requests/*.json"))
    restarted = FilesystemDiagnosticSink(tmp_path / "sessions")
    assert (
        len(await restarted.list_model_requests(session_id=grandchild.session_id)) == 2
    )
    assert (
        await restarted.get_model_request(
            session_id=grandchild.session_id, run_id="run", request_id="old"
        )
    )["request"] == old["request"]
    store = FilesystemSessionStore(tmp_path)
    assert await store.session_directory(grandchild.session_id) == owner
    await store.close()


def test_media_formats_restore_exactly_and_corruption_is_explicit(tmp_path):
    data = base64.b64encode(b"media" * 200).decode()
    value = [
        {"source": {"type": "base64", "media_type": "image/png", "data": data}},
        {"inline_data": {"mime_type": "audio/wav", "data": data}},
        {"input_audio": {"format": "wav", "data": data}},
        {"file_data": "data:application/pdf;base64," + data},
        {"b64_json": data},
        {"content": "ordinary text " * 1000},
        {"format": {"type": "json_schema"}, "data": "ordinary text " * 1000},
    ]
    store = DiagnosticMediaStore(tmp_path)
    encoded = store.externalize(value)
    assert store.restore(encoded) == value
    assert encoded[-1] == value[-1]
    assert len(list(store.root.glob("*.txt"))) == 2
    for path in store.root.glob("*.txt"):
        path.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="integrity"):
        store.restore(encoded)


def test_invalid_locations_and_media_refs_cannot_escape_session(tmp_path):
    locations = tmp_path / ".session-store/locations"
    locations.mkdir(parents=True)
    (locations / "child.json").write_text(
        json.dumps(
            {
                "format": "sage.filesystem-session-layout/v1",
                "session_id": "child",
                "relative_path": "../../outside",
            }
        )
    )
    with pytest.raises(ValueError):
        resolve_session_directory(tmp_path / "sessions", "child")
    with pytest.raises(ValueError, match="reference"):
        DiagnosticMediaStore(tmp_path).restore(
            {"$sage_diagnostic_media": {"sha256": "../../secret", "encoding": "utf-8"}}
        )
