"""Startup reconciliation for persisted managed operations."""

from __future__ import annotations


from sagents.v2.agent.management.service import owner_key
from app.v2.server.observability.logging import get_logger

LOGGER = get_logger(__name__)


async def recover_pending_packages(management, users, contexts):
    """Re-open unarchived operations in bounded pages; never replay a StartRun."""
    for user in await users.list_users():
        context = contexts.for_user(user.user_id)
        owner = owner_key(context)
        after = ""
        while True:
            # Filter archived and incomplete admissions in the same SQL query.
            # A terminal status can remove a row from this result while scanning,
            # so advancing by operation key must not depend on its old offset.
            rows = await management.store.unarchived_invocations(
                owner, after=after, limit=100
            )
            for row in rows:
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
            after = rows[-1]["operation"]
