"""
SQLAlchemy 基础设施

"""

from sqlalchemy.orm import declarative_base
import asyncio


Base = declarative_base()


class BaseDao:
    def __init__(self):
        try:
            loop = asyncio.get_running_loop()
            from core.client.db import get_global_db

            self._db_task = loop.create_task(get_global_db())
        except RuntimeError:
            self._db_task = None
        self.db = None

    async def _get_db(self):
        if self.db is not None:
            return self.db
        if self._db_task is not None:
            self.db = await self._db_task
            return self.db
        from core.client.db import get_global_db

        self.db = await get_global_db()
        return self.db
