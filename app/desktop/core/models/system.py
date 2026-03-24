from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BaseDao

class SystemInfo(Base):
    __tablename__ = "system_info"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=True)

    def __init__(self, key: str, value: str):
        self.key = key
        self.value = value

class SystemInfoDao(BaseDao):
    async def get_by_key(self, key: str) -> str | None:
        info = await BaseDao.get_by_id(self, SystemInfo, key)
        return info.value if info else None

    async def set_value(self, key: str, value: str) -> bool:
        info = await BaseDao.get_by_id(self, SystemInfo, key)
        if info:
            info.value = value
            return await BaseDao.save(self, info)
        else:
            info = SystemInfo(key=key, value=value)
            await BaseDao.insert(self, info)
            return True
