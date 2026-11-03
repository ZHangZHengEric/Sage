from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.v2.server.conversations.agui.service import ConversationService
from app.v2.server.conversations.agui.sse import canonical_agui_sse
from sagents.v2.context.session_history import SessionEventModelProjector
from sagents.v2.contracts.events import ItemEventData, RunEventData
from sagents.v2.contracts.items import MessageItemData, TextBlock, Visibility
from sagents.v2.interfaces.protocols.ag_ui import AgUiProtocolAdapter
from tests.sagents.v2.test_protocol_adapters_matrix import event, item_snapshot


def message(visibility, item_id="hidden", role="user"):
    return item_snapshot(item_id, MessageItemData(
        role=role, content=(TextBlock(text=f"{visibility.value} content"),),
    )).model_copy(update={"visibility": visibility})


@pytest.mark.parametrize("visibility", list(Visibility))
@pytest.mark.parametrize("extensions", [True, False])
def test_snapshot_visibility_separates_display_from_inference(visibility, extensions):
    source = event("message.completed", item_id="hidden", data=ItemEventData(
        operation="completed", item=message(visibility),
    ))
    result = AgUiProtocolAdapter(enable_sage_extensions=extensions).translate(source)
    assert bool(result.frames) == (visibility == Visibility.PUBLIC)
    projected = SessionEventModelProjector().project((source,))
    assert bool(projected) == (visibility in {Visibility.PUBLIC, Visibility.MODEL_VISIBLE})


@pytest.mark.parametrize("visibility", [Visibility.MODEL_VISIBLE, Visibility.AUDIT, Visibility.DIAGNOSTIC])
def test_hidden_stream_never_emits_text_or_custom_frames(visibility):
    adapter = AgUiProtocolAdapter()
    sources = (
        event("message.started", item_id="hidden", data=ItemEventData(
            operation="started", visibility=visibility,
        )),
        event("message.delta", item_id="hidden", data=ItemEventData(
            operation="delta", delta="private delta",
        )),
        event("message.completed", item_id="hidden", data=ItemEventData(
            operation="completed", item=message(visibility),
        )),
    )
    for source in sources:
        assert adapter.translate(source).frames == ()
    # A reconnect/page can begin at a delta, with no preceding started event.
    delta = event("message.delta", item_id="hidden", data=ItemEventData(
        operation="delta", visibility=visibility, delta="private delta",
    ))
    assert AgUiProtocolAdapter().translate(delta).frames == ()


def test_event_cannot_override_snapshot_visibility():
    with pytest.raises(ValidationError, match="visibility must match"):
        ItemEventData(operation="completed", visibility=Visibility.PUBLIC,
                      item=message(Visibility.MODEL_VISIBLE))


@pytest.mark.asyncio
async def test_live_sse_and_paginated_history_hide_model_visible_messages():
    hidden = event("message.completed", sequence=2, item_id="hidden", data=ItemEventData(
        operation="completed", item=message(Visibility.MODEL_VISIBLE),
    ))
    public = event("message.completed", sequence=3, item_id="public", data=ItemEventData(
        operation="completed", item=message(Visibility.PUBLIC, "public", "assistant"),
    ))
    sources = (event("run.started", data=RunEventData(state="running")), hidden, public)

    async def events():
        for source in sources:
            yield source

    stream = "".join([chunk async for chunk in canonical_agui_sse(
        events(), thread_id="session_1", run_id="run_1", last_event_id=None,
    )])
    assert "model_visible content" not in stream
    assert "public content" in stream

    service = ConversationService(
        threads=SimpleNamespace(find=AsyncMock(return_value=SimpleNamespace(user_id="owner"))),
        admission=None, runs=None, application=None, log_sink=None, language="en",
        context_for=lambda user: user,
        session_access=SimpleNamespace(read_session_event_page=AsyncMock(return_value=SimpleNamespace(
            events=(hidden, public), total=3, after_sequence=1,
        ))),
    )
    page = await service.events("session_1", "owner", limit=2, offset=1)
    assert "model_visible content" not in str(page["events"])
    assert "public content" in str(page["events"])
    assert page["total"] == 3
    assert page["offset"] == 1
