"""Rebuild resource dependencies without executing ancestor Agents or tools."""

from __future__ import annotations

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.session.access import AuthorizedSessionAccess
from .binding import ExecutionBindingRequest


async def acquire_execution_binding(provider, request, runtime):
    """Pin accepted ancestor leases for the lifetime of this binding.

    Read only authorized durable commands. Walking stops at a private workspace,
    whose origin is independent of its parent. No Run is resumed or created.
    """
    access = AuthorizedSessionAccess(runtime.session_store)
    chain = [request]
    seen = {request.run_id}
    current = request
    while (
        current.parent_run_id
        and str(getattr(current.workspace_policy, "value", current.workspace_policy))
        != "private_child"
    ):
        parent_id = current.parent_run_id
        if parent_id in seen:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="execution.configuration_incompatible",
                    category=ErrorCategory.VALIDATION,
                    message="cyclic durable execution ancestry",
                    safe_to_resume=False,
                )
            )
        seen.add(parent_id)
        parent = await access.get_start_command(parent_id, request.context)
        snapshot = parent.config.execution_snapshot
        current = ExecutionBindingRequest(
            run_id=parent_id,
            parent_run_id=parent.parent_run_id,
            agent_id=parent.agent_id,
            context=request.context,
            configuration=snapshot,
            workspace_policy=snapshot.workspace_policy if snapshot else "shared_parent",
        )
        chain.append(current)
    acquired = []
    try:
        for item in reversed(chain):
            binding = await provider.acquire(item)
            acquired.append(binding)
            binding.validate_for(item)
            if item is not request:
                await runtime.record_execution_binding(binding, request.context)
        result = acquired[-1]
        dependencies = acquired[:-1]
        result.diagnostics = {
            **result.diagnostics,
            "resource_dependencies": [
                {
                    "run_id": value.run_id,
                    "configuration_id": value.configuration_id,
                    "sandbox": value.sandbox.ref.model_dump(mode="json"),
                }
                for value in dependencies
            ],
        }
        result._dependencies = tuple(reversed(dependencies))
        return result
    except BaseException as exc:
        for binding in reversed(acquired):
            try:
                await binding.close()
            except BaseException as close_exc:
                exc.add_note(f"dependency binding rollback failed: {close_exc}")
        raise
