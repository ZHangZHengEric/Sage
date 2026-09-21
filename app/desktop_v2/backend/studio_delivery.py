"""Durable, per-member Studio mention delivery; publishing never awaits replies."""

from __future__ import annotations

import asyncio
import json

from app.desktop_v2.backend.schemas import DesktopRunRequest, RunMessage
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.run_state import TERMINAL_RUN_STATES


class StudioDeliveryMixin:
    def _start_studio_delivery_worker(self):
        if getattr(self, "_studio_delivery_worker", None) is not None:
            return
        self._studio_delivery_tasks = {}
        self._studio_delivery_worker = asyncio.create_task(self._studio_delivery_loop())

    async def _stop_studio_delivery_worker(self):
        worker = getattr(self, "_studio_delivery_worker", None)
        if worker is not None:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        tasks = list(getattr(self, "_studio_delivery_tasks", {}).values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._studio_delivery_worker = None

    async def _studio_delivery_loop(self):
        while True:
            try:
                await self.dispatch_studio_deliveries()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.exception(
                    "studio.delivery_poll_failed", "Studio delivery will retry", exc
                )
            await asyncio.sleep(1)

    async def dispatch_studio_deliveries(self):
        tasks = self._studio_delivery_tasks
        for key, task in list(tasks.items()):
            if task.done():
                tasks.pop(key)
                # Exceptions are handled by the delivery itself.
                task.result()
        rows = await asyncio.to_thread(self.studio_store.pending_deliveries)
        visited = set()
        for row in rows:
            key = row["session_id"]
            if key in visited or key in tasks:
                continue
            visited.add(key)
            if len(tasks) >= 8:
                break
            # Reconcile a prior start before considering any new execution.
            existing = await self.find_studio_run(
                row["studio_id"], row["member_id"], row["message_id"], row["owner"]
            )
            if existing is not None:
                await asyncio.to_thread(
                    self.studio_store.delivery_started,
                    row["message_id"],
                    row["member_id"],
                    existing["run_id"],
                )
                continue
            try:
                runs = await self.session_access.list_session_runs(
                    key, self._context(row["owner"])
                )
            except SageV2Error as exc:
                if exc.info.code != "session.not_found":
                    raise
                runs = ()
            if any(run.state not in TERMINAL_RUN_STATES for run in runs):
                continue  # Busy, including approval/suspension: retain FIFO queue.
            tasks[key] = asyncio.create_task(self._deliver_studio_message(row))

    async def _deliver_studio_message(self, row):
        try:
            request = DesktopRunRequest(
                studio_id=row["studio_id"],
                studio_member_id=row["member_id"],
                studio_message_id=row["message_id"],
                agent_id=row["agent_id"],
                session_id=row["session_id"],
                messages=[RunMessage(role="user", text=row["text"])],
                idempotency_key=f"studio-delivery:{row['message_id']}:{row['member_id']}",
            )
            # The ordinary v2 scheduler owns execution, approvals and resource limits.
            async for encoded in self.run_events(request, row["owner"]):
                event = json.loads(encoded)
                if event.get("kind") == "stream.opened":
                    await asyncio.to_thread(
                        self.studio_store.delivery_started,
                        row["message_id"],
                        row["member_id"],
                        event["handle"]["run_id"],
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await asyncio.to_thread(
                self.studio_store.delivery_failed,
                row["message_id"],
                row["member_id"],
                exc,
            )
            # Retry by reconciling canonical Runs first, never blindly resubmit.
            self.logger.exception(
                "studio.delivery_failed", "Studio delivery awaits reconciliation", exc
            )
