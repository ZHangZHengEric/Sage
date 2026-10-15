import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.v2.desktop.backend.app import create_app
from app.v2.desktop.backend import run_service
from app.v2.desktop.backend.openui import OpenUiProjector
from app.v2.desktop.backend.run_service import DesktopRunServiceMixin
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.events import ItemEventData, RunEventData
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime.observability import NoopLogSink, StructuredLogger
from sagents.v2.runtime.session.access import AuthorizedSessionAccess
from sagents.v2.runtime.session.contracts import EventDraft
from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore


CONTEXT = RequestContext(
    actor=ActorRef(
        principal_id="user",
        principal_type=PrincipalType.USER,
        tenant_id="tenant",
    )
)


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", [RunState.CANCELLED, RunState.FAILED])
async def test_desktop_reconnect_replays_only_unseen_previews_and_terminal_text(
    tmp_path,
    terminal,
    monkeypatch,
):
    projected_texts = []

    class RecordingProjector(OpenUiProjector):
        async def project(self, event):
            self.remember(event)
            projected_texts.append(dict(self.texts))
            return []

    monkeypatch.setattr(run_service, "OpenUiProjector", RecordingProjector)
    store = FilesystemSessionStore(tmp_path)
    service = SimpleNamespace(
        start=AsyncMock(),
        _context=lambda user: CONTEXT,
        session_access=AuthorizedSessionAccess(store),
        _index_run=AsyncMock(),
    )
    try:
        created = await store.create_run(
            StartRun(
                agent_id="agent",
                input=(InputItem(role="user", content=(TextBlock(text="hi"),)),),
                resolved_spec_hash="sha256:agent",
                idempotency_key="start",
            ),
            CONTEXT,
        )
        running = await store.commit_run(
            run_id=created.handle.run_id,
            expected_revision=created.handle.run_revision,
            expected_states={RunState.QUEUED},
            new_state=RunState.RUNNING,
            drafts=(),
            context=CONTEXT,
            idempotency_key="running",
        )
        run = await store.commit_model_stream_batch(
            run=running.run,
            context=CONTEXT,
            idempotency_key="preview",
            drafts=(
                EventDraft(
                    type="message.started",
                    item_id="message",
                    data=ItemEventData(operation="started"),
                ),
                EventDraft(
                    type="message.delta",
                    item_id="message",
                    data=ItemEventData(operation="delta", delta="partial"),
                ),
                EventDraft(
                    type="message.delta",
                    item_id="message",
                    data=ItemEventData(operation="delta", delta=" answer"),
                ),
            ),
        )
        previews = await service.session_access.read_stream_previews(
            run.run_id, CONTEXT
        )
        first, second = previews
        stream = DesktopRunServiceMixin.subscribe_events(
            service,
            run.run_id,
            run.last_run_sequence,
            "user",
            preview_sequence=first.preview_sequence,
            preview_epoch=first.preview_epoch,
        )
        frame = json.loads(await asyncio.wait_for(anext(stream), 1))
        assert frame["preview_sequence"] == second.preview_sequence
        assert frame["data"]["delta"] == " answer"
        assert frame["run_sequence"] == run.last_run_sequence
        await store.commit_run(
            run_id=run.run_id,
            expected_revision=run.revision,
            expected_states={RunState.RUNNING},
            new_state=terminal,
            drafts=(
                EventDraft(
                    type=f"run.{terminal.value}",
                    data=RunEventData(state=terminal.value),
                ),
            ),
            context=CONTEXT,
            idempotency_key="stop",
        )
        remaining = [json.loads(frame) async for frame in stream]
        assert [row["type"] for row in remaining] == [
            "message.completed",
            f"run.{terminal.value}",
        ]
        assert (
            remaining[0]["data"]["item"]["data"]["content"][0]["text"]
            == "partial answer"
        )
        assert remaining[0]["data"]["item"]["status"] == terminal.value
        assert projected_texts[0]["message"] == "partial answer"
        service._index_run.assert_awaited_once_with(run.run_id)
        assert await store.read_stream_previews(run.run_id) == ()
        assert not any(
            event.type == "message.delta"
            for event in await store.read_events(run.run_id)
        )
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_preview_reads_require_the_session_owner(tmp_path):
    store = FilesystemSessionStore(tmp_path)
    try:
        created = await store.create_run(
            StartRun(
                agent_id="agent",
                input=(InputItem(role="user", content=(TextBlock(text="hi"),)),),
                resolved_spec_hash="sha256:agent",
                idempotency_key="start",
            ),
            CONTEXT,
        )
        other = RequestContext(
            actor=CONTEXT.actor.model_copy(update={"principal_id": "other"})
        )
        from sagents.v2.contracts.errors import SageV2Error

        with pytest.raises(SageV2Error):
            await AuthorizedSessionAccess(store).read_stream_previews(
                created.handle.run_id, other
            )
    finally:
        await store.close()


def test_desktop_events_endpoint_forwards_preview_cursor():
    received = []

    async def subscribe(run_id, after_sequence, user_id, **kwargs):
        received.append((run_id, after_sequence, kwargs))
        yield '{"type":"run.cancelled"}\n'

    service = SimpleNamespace(
        initialize_agent_workspace=AsyncMock(),
        close=AsyncMock(),
        logger=StructuredLogger(NoopLogSink(), "test"),
        subscribe_events=subscribe,
    )
    app = create_app(service=service, auth_token="test-token")
    with TestClient(app) as client:
        response = client.get(
            "/api/v2/runs/run-1/events",
            params={
                "after_sequence": 4,
                "preview_sequence": 7,
                "preview_epoch": "host-1",
            },
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 200
    assert received == [
        ("run-1", 4, {"preview_sequence": 7, "preview_epoch": "host-1"})
    ]
