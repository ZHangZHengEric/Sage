"""Read-only recovery streams use the exact Run's durable event history."""

from contextlib import aclosing

import pytest
from fastapi.testclient import TestClient

from app.v2.server.conversations.external_runs import recover_run
from app.v2.server.main import create_app
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
from sagents.v2.contracts.events import RunEventData, ToolEventData, TurnEventData
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime.session.contracts import EventDraft
from sagents.v2.runtime.session.state import SessionStoreCoordinator
from tests.app.v2.server.test_agui_chat import _parse_sse_frames
from tests.app.v2.server.test_external_chat import make_host, setup_agent
from tests.app.v2.server.test_external_run_lookup import _seed, _service


def test_recover_http_authorizes_the_original_run_and_resumes(tmp_path):
    tenant = {"SAGE-TENANT-ID": "tenant"}
    with TestClient(create_app(make_host(tmp_path))) as client:
        owner_token = setup_agent(client)
        agent = client.headers["SAGE-AGENT-ID"]
        base = f"/api/agents/{agent}/runs"
        path = f"{base}/work/first/recover"
        assert client.get(path, headers=tenant).status_code == 404
        for run_id in ("first", "second"):
            response = client.post(base, headers=tenant, json={
                "threadId": "work", "runId": run_id,
                "messages": [{"id": run_id, "role": "user", "content": "private prompt"}],
            })
            assert response.status_code == 200 and "RUN_FINISHED" in response.text

        response = client.get(path, headers=tenant)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "private, no-store"
        [(event_id, payload)] = _parse_sse_frames(response.text)
        assert payload == {
            "agentId": agent, "threadId": "work", "runId": "first", "state": "completed",
        }
        assert client.get(path, headers={**tenant, "Last-Event-ID": event_id}).text == ""
        for cursor in ("invalid", "9999999999999999999", "-1"):
            assert client.get(path, headers={**tenant, "Last-Event-ID": cursor}).status_code == 422
        assert client.get(path, headers={"SAGE-TENANT-ID": "another"}).status_code == 404
        assert client.get(f"{base}/other/first/recover", headers=tenant).status_code == 404
        assert client.get(path.replace(f"/{agent}/", "/other-agent/"), headers=tenant).status_code == 403
        assert client.get(path, headers={**tenant, "Authorization": "Bearer invalid"}).status_code == 401
        issued = client.post("/api/keys", headers={"Authorization": f"Bearer {owner_token}"}, json={
            "agent_id": agent, "name": "invoke only", "scopes": ["a2a:invoke"],
        })
        assert issued.status_code == 200, issued.text
        key = issued.json()["data"]["api_key"]
        assert client.get(path, headers={**tenant, "Authorization": f"Bearer {key}"}).status_code == 403


@pytest.mark.parametrize("stop", [
    RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED, RunState.SUSPENDED,
])
async def test_recover_projects_durable_events_across_replay_and_live_handoff(stop, monkeypatch):
    monkeypatch.setattr("app.v2.server.conversations.external_runs._RECOVERY_PAGE_SIZE", 1)
    store = SessionStoreCoordinator()
    service = _service(store)
    native_id, _ = await _seed(service)
    context = service.context_for("owner")
    identity = {"agentId": "agent", "threadId": "work", "runId": "first"}

    async def commit(state, *drafts):
        current = await store.get_run(native_id)
        return await store.commit_run(
            run_id=native_id, expected_revision=current.revision, expected_states={current.state},
            new_state=state, drafts=drafts, context=context,
            idempotency_key=f"fixture:{current.revision}",
        )

    def tool_event(status):
        return EventDraft(type=f"tool.call.{status}", data=ToolEventData(
            tool_call_id="call-1", tool_name="lookup", state=status,
            arguments={"private": "arguments"}, execution_result={"private": "result"},
        ))

    async def open_stream(last_event_id=None):
        return await recover_run(
            service, tenant_id="tenant", agent_id="agent", thread_id="work",
            run_id="first", last_event_id=last_event_id,
        )

    await commit(RunState.RUNNING, EventDraft(type="run.started", data=RunEventData(state="running")))
    proposed = await commit(RunState.RUNNING, tool_event("proposed"))
    async with aclosing(await open_stream()) as stream:
        assert _parse_sse_frames(await anext(stream)) == [
            (str(proposed.run.last_run_sequence), {
                **identity, "toolCallId": "call-1", "toolName": "lookup", "state": "proposed",
            }),
        ]
        assert _parse_sse_frames(await anext(stream)) == [
            (f"{proposed.run.last_run_sequence}:state", {**identity, "state": "running"}),
        ]
        # A client may disconnect between a tool event and the state snapshot
        # that shares its sequence number.
        async with aclosing(await open_stream(str(proposed.run.last_run_sequence))) as resumed:
            assert _parse_sse_frames(await anext(resumed)) == [
                (f"{proposed.run.last_run_sequence}:state", {**identity, "state": "running"}),
            ]
        # These events land after the authorization snapshot and before the
        # live iterator first reads, so its exclusive cursor must bridge them.
        started = await commit(
            RunState.RUNNING,
            EventDraft(type="turn.started", data=TurnEventData(state="private turn")),
            tool_event("started"),
        )
        [(tool_id, data)] = _parse_sse_frames(await anext(stream))
        assert tool_id == str(started.run.last_run_sequence)
        assert data == {
            **identity, "toolCallId": "call-1", "toolName": "lookup", "state": "started",
        }

        # The subscription has now delivered from the store. Following writes
        # are sent to the already-open iterator.
        error = RuntimeErrorInfo(
            code="test.failure", category=ErrorCategory.INTERNAL, message="private failure",
        ) if stop == RunState.FAILED else None
        final = await commit(
            stop, tool_event("succeeded"),
            EventDraft(type=f"run.{stop.value}", data=RunEventData(
                state=stop.value, reason="private reason", error=error,
            )),
        )
        tail = _parse_sse_frames("".join([frame async for frame in stream]))
        state_id = f"{final.run.last_run_sequence}:state"
        assert tail == [
            (str(final.run.last_run_sequence - 1), {
                **identity, "toolCallId": "call-1", "toolName": "lookup", "state": "succeeded",
            }),
            (state_id, {**identity, "state": stop.value}),
        ]
    assert not store._subscribers[native_id]
    assert _parse_sse_frames("".join([frame async for frame in await open_stream(tool_id)])) == tail
    assert [frame async for frame in await open_stream(state_id)] == []
    assert await store.get_run(native_id) == final.run
    service.runs.start_detached_run.assert_not_awaited()

    if stop == RunState.SUSPENDED:
        await commit(RunState.RESUMING, EventDraft(
            type="run.resume_requested", data=RunEventData(state="resuming"),
        ))
        resumed = await commit(RunState.RUNNING, EventDraft(
            type="run.resumed", data=RunEventData(state="running"),
        ))
        async with aclosing(await open_stream(tool_id)) as stream:
            assert _parse_sse_frames(await anext(stream)) == tail[:1]
            assert _parse_sse_frames(await anext(stream))[0][1] == {**identity, "state": "resuming"}
            assert _parse_sse_frames(await anext(stream))[0][1] == {**identity, "state": "running"}
        assert await store.get_run(native_id) == resumed.run
