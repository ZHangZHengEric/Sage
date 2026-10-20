"""Stable synchronous Agent lookup backed by asynchronous revision leases."""
from __future__ import annotations

import asyncio

from sagents.v2.contracts.run_state import EventCursor
from sagents.v2.sagent import SAgent, SAgentRunStream


class ApplicationAgentRuntime:
    """Revision-bound admission and process-owned RuntimePort controls."""

    _SHARED_METHODS = frozenset({
        "subscribe_events", "subscribe_session_tree", "get_run", "get_run_result",
        "propose_session_commit", "publish_session_commit", "reject_session_commit",
        "start_execution", "pause_run", "commit_suspension", "resume_run",
        "reply_interaction", "mark_resumed", "steer_run", "cancel_run", "complete_run", "fail_run",
    })

    def __init__(self, catalog, agent):
        self._catalog = catalog
        self._revision = agent

    @property
    def session_store(self):
        return self._catalog.process_runtime.session_store

    @property
    def job_runtime(self):
        return self._catalog.process_runtime.job_runtime

    @property
    def derived_state_store(self):
        return self._catalog.process_runtime.derived_state_store

    def __getattr__(self, name):
        if name in self._SHARED_METHODS:
            return getattr(self._catalog.process_runtime, name)
        raise AttributeError(name)

    async def start_run(self, command, context):
        async with self._catalog.pin(self._revision) as agent:
            return await self._catalog.implementation(agent).runtime.start_run(command, context)

    async def stream(self, command, context):
        async with self._catalog.pin(self._revision) as agent:
            return await self._catalog.implementation(agent).runtime.stream(command, context)


class ApplicationAgent(SAgent):
    """Keep an exported facade usable when its idle composition is released.

    Only the process control runtime and immutable plan are exposed directly.
    Execution, subscriptions and publication acquire their exact revision.
    """

    def __init__(self, catalog, agent):
        self._catalog = catalog
        self._revision = agent
        self._closed = False
        self._closing = False
        self._runtime = ApplicationAgentRuntime(catalog, agent)

    @property
    def runtime(self):
        return self._runtime

    @property
    def resolved_plan(self):
        return self._revision.resolved_plan

    async def _invoke(self, method, *args, **kwargs):
        self._ensure_open()
        async with self._catalog.pin(self._revision) as agent:
            return await getattr(self._catalog.implementation(agent), method)(*args, **kwargs)

    async def start_run(self, command, context):
        return await self._invoke("start_run", command, context)

    async def run_stream(self, command, context):
        return await self._invoke("run_stream", command, context)

    async def drive_admitted_run(self, run_id, context, *, resume=False):
        return await self._invoke("drive_admitted_run", run_id, context, resume=resume)

    async def schedule_accepted_run(self, handle, context, *, resume=False):
        return await self._invoke("schedule_accepted_run", handle, context, resume=resume)

    async def continue_run(self, run_id, context):
        return await self._invoke("continue_run", run_id, context)

    async def propose_session_commit(self, command, context):
        return await self._invoke("propose_session_commit", command, context)

    async def publish_session_commit(self, command, context):
        return await self._invoke("publish_session_commit", command, context)

    async def reject_session_commit(self, command, context):
        return await self._invoke("reject_session_commit", command, context)

    async def fail_driver_crash(self, run_id, exc, context):
        return await self._invoke("fail_driver_crash", run_id, exc, context)

    async def recover_interrupted_run(self, run_id, context):
        return await self._invoke("recover_interrupted_run", run_id, context)

    def ensure_execution(self, run_id, context, *, resume):
        self._ensure_open()

        async def execute():
            async with self._catalog.pin(self._revision) as agent:
                return await self._catalog.implementation(agent).ensure_execution(run_id, context, resume=resume)

        return asyncio.create_task(execute(), name=f"sagent-export:{run_id}")

    def subscribe_events(self, cursor, context):
        self._ensure_open()

        async def events():
            async with self._catalog.pin(self._revision) as agent:
                source = self._catalog.implementation(agent).subscribe_events(cursor, context)
                try:
                    async for event in source:
                        yield event
                finally:
                    await source.aclose()

        return events()

    def drive_accepted_run(self, handle, context, *, resume=False):
        return SAgentRunStream(handle=handle,
            events=self.subscribe_events(EventCursor(run_id=handle.run_id, run_sequence=0), context),
            execution=self.ensure_execution(handle.run_id, context, resume=resume))

    def attach_dispatcher(self, dispatcher):
        if dispatcher is not self._catalog.process_dispatcher:
            raise RuntimeError("SAgent already has an execution dispatcher")

    async def close(self):
        if self._closed:
            return
        await self._invoke("close")
        self._closed = True
