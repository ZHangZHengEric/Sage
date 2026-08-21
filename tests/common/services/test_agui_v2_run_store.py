import json

import pytest

from common.services.agui_v2_run_store import (
    AguiRunConflict,
    AguiV2RunStore,
)


@pytest.mark.asyncio
async def test_claim_is_idempotent_per_user_and_rejects_thread_rebinding() -> None:
    store = AguiV2RunStore(ttl_seconds=60)

    first = await store.claim_run(
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
    )
    repeated = await store.claim_run(
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
    )
    other_user = await store.claim_run(
        user_id="user-2",
        thread_id="thread-1",
        run_id="run-1",
    )

    assert first.created is True
    assert repeated.created is False
    assert other_user.created is True
    with pytest.raises(AguiRunConflict):
        await store.claim_run(
            user_id="user-1",
            thread_id="thread-2",
            run_id="run-1",
        )


@pytest.mark.asyncio
async def test_subscribe_replays_after_cursor_and_stops_on_terminal_event() -> None:
    store = AguiV2RunStore(ttl_seconds=60, heartbeat_seconds=0.01)
    claim = await store.claim_run(
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
    )
    first_id = await store.publish(
        claim.run,
        {"type": "RUN_STARTED", "threadId": "thread-1", "runId": "run-1"},
    )
    await store.publish(
        claim.run,
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "message-1", "delta": "hello"},
    )
    await store.publish(
        claim.run,
        {"type": "RUN_FINISHED", "threadId": "thread-1", "runId": "run-1"},
    )
    await store.finish(claim.run, status="completed")

    chunks = [
        chunk
        async for chunk in store.subscribe(
            claim.run,
            last_event_id=first_id,
        )
    ]
    events = [json.loads(chunk.split("data: ", 1)[1]) for chunk in chunks]

    assert [event["type"] for event in events] == [
        "TEXT_MESSAGE_CONTENT",
        "RUN_FINISHED",
    ]
    assert chunks[0].startswith("id: 2-0\ndata: ")
    assert chunks[1].startswith("id: 3-0\ndata: ")


@pytest.mark.asyncio
async def test_subscriber_receives_live_events_without_owning_the_run() -> None:
    store = AguiV2RunStore(ttl_seconds=60, heartbeat_seconds=0.1)
    claim = await store.claim_run(
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
    )
    subscription = store.subscribe(claim.run, last_event_id=None)

    first_chunk_task = anext(subscription)
    await store.publish(
        claim.run,
        {"type": "RUN_STARTED", "threadId": "thread-1", "runId": "run-1"},
    )
    first_chunk = await first_chunk_task
    await subscription.aclose()

    assert first_chunk.startswith("id: 1-0\ndata: ")
    assert claim.run.status == "running"


@pytest.mark.asyncio
async def test_event_buffer_is_bounded_without_deleting_run_metadata() -> None:
    store = AguiV2RunStore(ttl_seconds=60, max_events=2)
    claim = await store.claim_run(
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
    )

    for index in range(3):
        await store.publish(
            claim.run,
            {"type": "CUSTOM", "name": str(index), "value": index},
        )

    events = await store.list_events(claim.run)
    repeated = await store.claim_run(
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
    )

    assert [event.payload["value"] for event in events] == [1, 2]
    assert repeated.created is False
