"""Exact-run access for external Agent Runs.

This service resolves persisted Agent, tenant, thread and run bindings.
"""

from __future__ import annotations

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.run_state import RunState, TERMINAL_RUN_STATES


def _error(code: str, category: ErrorCategory, message: str) -> SageV2Error:
    return SageV2Error(RuntimeErrorInfo(
        code="server.external_runs." + code, category=category, message=message,
    ))


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
    if (command.agent_id != agent_id
            or command.config.metadata.get("server_v2.workspace_user_id") != tenant_id):
        raise _error("forbidden", ErrorCategory.AUTHORIZATION,
                     "Run does not belong to the requested Agent and tenant")
    return payload, native_run_id, owner, internal_thread, context, access, command


async def run_details(service, *, tenant_id: str, agent_id: str,
                      thread_id: str, run_id: str) -> dict:
    payload, native_run_id, _, _, context, access, _ = await selected_run(
        service, tenant_id=tenant_id, agent_id=agent_id,
        thread_id=thread_id, run_id=run_id,
    )
    details = {**payload, "items": [], "interaction": None}
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
    _, native_run_id, _, internal_thread, context, access, command = await selected_run(
        service, tenant_id=tenant_id, agent_id=agent_id,
        thread_id=thread_id, run_id=run_id,
    )
    runs = await access.list_session_runs(internal_thread, context)
    latest = max(runs, key=lambda run: (
        run.accepted_session_revision, run.created_at, run.run_id,
    ))
    if latest.run_id != native_run_id:
        raise _error("stale_workspace", ErrorCategory.CONFLICT,
                     "Workspace has a newer Run")
    from app.v2.server.storage.external_workspaces import workspace_parts
    path = command.config.metadata.get("server_v2.external.workspace_path")
    try:
        return "/".join(workspace_parts(path))
    except ValueError as exc:
        raise _error("workspace_missing", ErrorCategory.VALIDATION,
                     "Run has no bound workspace directory") from exc
