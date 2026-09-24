"""Startup reconciliation for persisted managed operations."""

from __future__ import annotations


from sagents.v2.agent.management.service import owner_key
from app.server_v2.core.observability.logging import get_logger

LOGGER = get_logger(__name__)


async def recover_pending_packages(management, users, contexts):
    """Re-open unarchived operations in bounded pages; never replay a StartRun."""
    for user in await users.list_users():
        context = contexts.for_user(user.user_id)
        offset = 0
        while True:
            rows = await management.list_runs(context, limit=100, offset=offset)
            for row in rows:
                if not row.get("handle"):
                    continue  # Caller must retry incomplete admission with original input.
                if (
                    await management.store.terminal_status(
                        owner_key(context), row["operation"]
                    )
                    is not None
                ):
                    continue
                try:
                    await management.status(row["operation"], context)
                except Exception as exc:
                    LOGGER.exception(
                        "package.recovery.failed",
                        "managed operation recovery failed",
                        exc,
                        operation_id=row["operation"],
                    )
            if len(rows) < 100:
                break
            offset += len(rows)
