from loguru import logger
from sqlalchemy import or_, update

from common.core.client.db import get_global_db
from common.models.agent import Agent, AgentAuthorization
from common.models.conversation import Conversation
from common.models.im_channel import IMChannelConfig
from common.models.kdb import Kdb
from common.models.llm_provider import LLMProvider
from common.models.mcp_server import MCPServer
from common.models.task import RecurringTask, Task
from .user_context import DEFAULT_DESKTOP_USER_ID


async def migrate_desktop_default_user_id() -> None:
    db = await get_global_db()
    async with db.get_session() as session:  # type: ignore[attr-defined]
        migrated = {}

        result = await session.execute(
            update(Agent)
            .where(or_(Agent.user_id == "", Agent.user_id.is_(None)))
            .values(user_id=DEFAULT_DESKTOP_USER_ID)
        )
        migrated["agent_configs"] = int(result.rowcount or 0)

        result = await session.execute(
            update(Conversation)
            .where(or_(Conversation.user_id == "", Conversation.user_id.is_(None)))
            .values(user_id=DEFAULT_DESKTOP_USER_ID)
        )
        migrated["conversations"] = int(result.rowcount or 0)

        result = await session.execute(
            update(LLMProvider)
            .where(or_(LLMProvider.user_id == "", LLMProvider.user_id.is_(None)))
            .values(user_id=DEFAULT_DESKTOP_USER_ID)
        )
        migrated["llm_providers"] = int(result.rowcount or 0)

        result = await session.execute(
            update(MCPServer)
            .where(or_(MCPServer.user_id == "", MCPServer.user_id.is_(None)))
            .values(user_id=DEFAULT_DESKTOP_USER_ID)
        )
        migrated["mcp_servers"] = int(result.rowcount or 0)

        result = await session.execute(
            update(Kdb)
            .where(or_(Kdb.user_id == "", Kdb.user_id.is_(None)))
            .values(user_id=DEFAULT_DESKTOP_USER_ID)
        )
        migrated["kdb"] = int(result.rowcount or 0)

        result = await session.execute(
            update(AgentAuthorization)
            .where(or_(AgentAuthorization.user_id == "", AgentAuthorization.user_id.is_(None)))
            .values(user_id=DEFAULT_DESKTOP_USER_ID)
        )
        migrated["agent_authorizations"] = int(result.rowcount or 0)

        result = await session.execute(
            update(IMChannelConfig)
            .where(
                or_(
                    IMChannelConfig.sage_user_id == "",
                    IMChannelConfig.sage_user_id.is_(None),
                    IMChannelConfig.sage_user_id == "desktop_default_user",
                )
            )
            .values(sage_user_id=DEFAULT_DESKTOP_USER_ID)
        )
        migrated["im_user_configs"] = int(result.rowcount or 0)

        result = await session.execute(
            update(RecurringTask)
            .where(or_(RecurringTask.user_id == "", RecurringTask.user_id.is_(None)))
            .values(user_id=DEFAULT_DESKTOP_USER_ID)
        )
        migrated["recurring_tasks"] = int(result.rowcount or 0)

        result = await session.execute(
            update(Task)
            .where(or_(Task.user_id == "", Task.user_id.is_(None)))
            .values(user_id=DEFAULT_DESKTOP_USER_ID)
        )
        migrated["tasks"] = int(result.rowcount or 0)

        logger.info(
            "Desktop user_id migration completed: "
            + ", ".join(f"{table}={count}" for table, count in migrated.items())
        )
