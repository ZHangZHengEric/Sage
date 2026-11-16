"""Exact-run access for external Agent Runs.

This service resolves persisted Agent, tenant, thread and run bindings.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import aclosing

from app.v2.server.conversations.agui.sse import events_with_heartbeats, format_sse
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.events import RunEventData, RuntimeEvent, ToolEventData
from sagents.v2.contracts.run_state import EventCursor, RunSnapshot, RunState, TERMINAL_RUN_STATES


_RECOVERY_PAGE_SIZE = 500
_RECENT_TOOL_EVENTS = 100
_RECOVERY_STOP_STATES = TERMINAL_RUN_STATES | {RunState.SUSPENDED}
_RECOVERY_RUN_STATES = frozenset(RunState)


def _error(code: str, category: ErrorCategory, message: str) -> SageV2Error:
    return SageV2Error(RuntimeErrorInfo(
        code="server.external_runs." + code, category=category, message=message,
    ))


def _require_run_binding(command, agent_id: str, tenant_id: str) -> None:
    if (command.agent_id != agent_id
            or command.config.metadata.get("server_v2.workspace_user_id") != tenant_id):
        raise _error("forbidden", ErrorCategory.AUTHORIZATION,
                     "Run does not belong to the requested Agent and tenant")


async def selected_run(service, *, tenant_id: str, agent_id: str,
                       thread_id: str, run_id: str):
    """Resolve an exact AG-UI run; never fall back to the latest Run."""
    if not all(isinstance(value, str) and value.strip() for value in
               (tenant_id, agent_id, thread_id, run_id)):
        raise _error("invalid_identity", ErrorCategory.VALIDATION,
                     "tenant, Agent, thread and run are required")
    payload, native_run_id = await service._result_with_native_run(
        user_id=tenant_id, agent_id=agent_id, session_id=thread_id,
        run_id=run_id,
    )
    owner, internal_thread = await service._scope(tenant_id, agent_id, thread_id)
    context = service.context_for(owner)
    access = service.session_access
    command = await access.get_start_command(native_run_id, context)
    _require_run_binding(command, agent_id, tenant_id)
    return payload, native_run_id, owner, internal_thread, context, access, command


async def recover_run(service, *, tenant_id: str, agent_id: str, thread_id: str,
                      run_id: str, last_event_id: str | None) -> AsyncIterator[str]:
    """Authorize before opening an SSE response for the exact existing Run."""
    owner, internal_thread = await service._scope(
        tenant_id, agent_id, thread_id, bind_legacy=False,
    )
    context = service.context_for(owner)
    found = await service._find_client_run(internal_thread, run_id, context, external=True)
    if found is None:
        raise _error("result_not_found", ErrorCategory.VALIDATION, "Run not found")
    run, command = found
    _require_run_binding(command, agent_id, tenant_id)

    after = None
    if last_event_id:
        match = re.fullmatch(r"([0-9]{1,19})(:state)?", last_event_id)
        if match is None or int(match[1]) > run.last_run_sequence:
            raise _error("invalid_event_cursor", ErrorCategory.VALIDATION,
                         "Invalid Last-Event-ID for this Run")
        after = (int(match[1]), bool(match[2]))
    return _recover_events(
        service.session_access, context, run, after,
        {"agentId": agent_id, "threadId": thread_id, "runId": run_id},
    )


def _recovery_event(event: RuntimeEvent, identity: dict[str, str]) -> str | None:
    data = event.data
    if isinstance(data, ToolEventData):
        return format_sse(str(event.run_sequence), {
            **identity, "toolCallId": data.tool_call_id, "toolName": data.tool_name,
            "state": data.state,
        })
    if isinstance(data, RunEventData) and data.state in _RECOVERY_RUN_STATES:
        return format_sse(f"{event.run_sequence}:state", {**identity, "state": data.state})
    return None


async def _recent_tool_frames(access, context, run: RunSnapshot, identity: dict[str, str]):
    frames = []
    end = run.last_run_sequence
    while end:
        start = max(0, end - _RECOVERY_PAGE_SIZE)
        events = await access.read_events(run.run_id, context, after_sequence=start,
                                          limit=end - start)
        for event in reversed(events):
            if event.run_sequence <= end and isinstance(event.data, ToolEventData):
                frames.append(_recovery_event(event, identity))
                if len(frames) == _RECENT_TOOL_EVENTS:
                    return reversed(frames)
        end = start
    return reversed(frames)


async def _recover_events(access, context, run: RunSnapshot,
                          after: tuple[int, bool] | None,
                          identity: dict[str, str]) -> AsyncIterator[str]:
    head = run.last_run_sequence
    stopped = run.state in _RECOVERY_STOP_STATES
    head_state_delivered = after == (head, True)
    if after is None:
        for frame in await _recent_tool_frames(access, context, run, identity):
            yield frame
    else:
        sequence, _ = after
        while sequence < head:
            events = await access.read_events(
                run.run_id, context, after_sequence=sequence,
                limit=min(_RECOVERY_PAGE_SIZE, head - sequence),
            )
            if not events:
                break
            for event in events:
                sequence = event.run_sequence
                if sequence > head:
                    break
                # A previous suspension can have been superseded by a resume.
                # Send the stop state from the authorized snapshot below.
                if (isinstance(event.data, RunEventData)
                        and event.data.state in _RECOVERY_STOP_STATES):
                    continue
                frame = _recovery_event(event, identity)
                if frame is not None:
                    if sequence == head and isinstance(event.data, RunEventData):
                        head_state_delivered = True
                    yield frame
    if not head_state_delivered:
        yield format_sse(f"{head}:state", {**identity, "state": run.state.value})
    if stopped:
        return

    # The durable cursor bridges the snapshot read and subscription setup.
    events = access.subscribe_events(EventCursor(run_id=run.run_id, run_sequence=head), context)
    async with aclosing(events_with_heartbeats(events, heartbeat_seconds=20)) as stream:
        async for event in stream:
            if event is None:
                yield ": heartbeat\n\n"
                continue
            if event.preview_sequence is not None:
                continue
            frame = _recovery_event(event, identity)
            if frame is not None:
                yield frame
            if (isinstance(event.data, RunEventData)
                    and event.data.state in _RECOVERY_STOP_STATES):
                return


async def run_details(service, *, tenant_id: str, agent_id: str,
                      thread_id: str, run_id: str) -> dict:
    payload, native_run_id, _, _, context, access, _ = await selected_run(
        service, tenant_id=tenant_id, agent_id=agent_id,
        thread_id=thread_id, run_id=run_id,
    )
    details = {**payload, "threadId": thread_id, "items": [], "interaction": None}
    run = await access.get_run(native_run_id, context)
    if run.state in TERMINAL_RUN_STATES:
        result = await access.get_run_result(run.run_id, context)
        details["items"] = [item.model_dump(mode="json") for item in result.final_items]
    if run.state == RunState.SUSPENDED and run.suspension_id:
        suspension = await access.get_suspension(run.suspension_id, context)
        if suspension.interaction_id:
            interaction = await access.get_interaction(suspension.interaction_id, context)
            details["interaction"] = {
                "request": interaction.model_dump(mode="json"),
                "expected": {
                    "interaction_id": interaction.interaction_id,
                    "revision": run.revision,
                    "suspension_revision": suspension.expected_revision,
                    "interaction_revision": interaction.expected_revision,
                },
            }
    return details


async def cancel_run(service, *, tenant_id: str, agent_id: str,
                     thread_id: str, run_id: str) -> dict:
    selected, native_run_id, _, _, context, access, _ = await selected_run(
        service, tenant_id=tenant_id, agent_id=agent_id,
        thread_id=thread_id, run_id=run_id,
    )
    run = await access.get_run(native_run_id, context)
    if run.state in TERMINAL_RUN_STATES:
        return {"session_id": selected["session_id"], "cancelled": False}
    await service.runs.cancel_run(run.run_id, context, expected_revision=run.revision)
    return {"session_id": selected["session_id"], "cancelled": True}


async def reply_run(service, *, tenant_id: str, agent_id: str, thread_id: str,
                    run_id: str, interaction_id: str, decision: str,
                    payload: dict, expected: dict) -> str:
    selected, native_run_id, owner, internal_thread, context, _, _ = await selected_run(
        service, tenant_id=tenant_id, agent_id=agent_id,
        thread_id=thread_id, run_id=run_id,
    )
    if selected["state"] != RunState.SUSPENDED.value:
        raise _error("not_suspended", ErrorCategory.CONFLICT,
                     "Run is not waiting for input")
    await service.runs.resume_detached_run(
        native_run_id, context, user_id=owner, session_id=internal_thread,
        label="external", expected=expected,
        decide=lambda interaction: (decision, payload)
        if interaction.interaction_id == interaction_id
        and decision in interaction.allowed_decisions else None,
    )

    return internal_thread


async def current_run_workspace(service, *, tenant_id: str, agent_id: str,
                                thread_id: str, run_id: str) -> str:
    """Return the bound relative path only while this run is latest."""
    if not all(isinstance(value, str) and value.strip() for value in
               (tenant_id, agent_id, thread_id, run_id)):
        raise _error("invalid_identity", ErrorCategory.VALIDATION,
                     "tenant, Agent, thread and run are required")
    owner, internal_thread = await service._scope(tenant_id, agent_id, thread_id)
    context = service.context_for(owner)
    access = service.session_access
    found = await service._find_client_run(internal_thread, run_id, context, external=True)
    if found is None:
        raise _error("result_not_found", ErrorCategory.VALIDATION, "Run not found")
    _, command = found
    _require_run_binding(command, agent_id, tenant_id)
    latest = await access.latest_session_start_command(internal_thread, context)
    if latest is None or latest.idempotency_key != command.idempotency_key:
        raise _error("stale_workspace", ErrorCategory.CONFLICT,
                     "Workspace has a newer Run")
    from app.v2.server.storage.external_workspaces import workspace_parts
    path = command.config.metadata.get("server_v2.external.workspace_path")
    try:
        return "/".join(workspace_parts(path))
    except ValueError as exc:
        raise _error("workspace_missing", ErrorCategory.VALIDATION,
                     "Run has no bound workspace directory") from exc


async def run_metrics(service, *, tenant_id: str, agent_id: str,
                      thread_id: str, run_id: str) -> dict:
    """Safe, exact-run operating metrics; never return provider payloads."""
    payload, native_id, _, _, context, access, _ = await selected_run(
        service, tenant_id=tenant_id, agent_id=agent_id,
        thread_id=thread_id, run_id=run_id,
    )
    run = await access.get_run(native_id, context)
    state = run.state.value
    if run.state not in TERMINAL_RUN_STATES and payload["state"] == "recovery_blocked":
        state = payload["state"]
    metrics = {"threadId": thread_id, "runId": run_id,
               "state": state, "acceptedAt": run.created_at.isoformat(),
               "completedAt": None, "activeMilliseconds": None, "usage": None}
    if run.state not in TERMINAL_RUN_STATES:
        return metrics
    result = await access.get_run_result(native_id, context)
    metrics["completedAt"] = result.completed_at.isoformat()
    metrics["usage"] = result.usage.model_dump(include={
        "reported", "input_tokens", "output_tokens", "cached_input_tokens",
    })
    # Lifecycle segments exclude queueing and suspended user-input waits.
    # Missing/oversized histories remain unknown rather than fabricated zeroes.
    cursor, active, elapsed, saw_start, saw_end, invalid = 0, None, 0.0, False, False, False
    for _ in range(200):
        events = await access.read_events(native_id, context, after_sequence=cursor, limit=500)
        if not events:
            if saw_start and saw_end and active is None and not invalid:
                metrics["activeMilliseconds"] = round(elapsed * 1000)
            break
        for event in events:
            cursor = event.run_sequence
            if event.type in {"run.started", "run.resumed"}:
                if active is None:
                    active = event.occurred_at
                saw_start = True
            elif event.type in {"run.suspended", "run.completed", "run.failed", "run.cancelled"}:
                if active is not None:
                    seconds = (event.occurred_at - active).total_seconds()
                    invalid = invalid or seconds < 0
                    elapsed += max(0.0, seconds)
                    active = None
                elif event.type == "run.suspended":
                    invalid = True
                if event.type != "run.suspended":
                    saw_end = True
    return metrics
