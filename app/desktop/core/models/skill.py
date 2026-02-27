from datetime import datetime
from typing import Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BaseDao


class SkillOwnership(Base):
    __tablename__ = "skill_ownerships"

    skill_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)

    def __init__(self, skill_name: str, user_id: str):
        self.skill_name = skill_name
        self.user_id = user_id
        self.created_at = datetime.now()


class SkillOwnershipDao(BaseDao):
    async def get_owner(self, skill_name: str) -> Optional[str]:
        obj = await BaseDao.get_by_id(self, SkillOwnership, skill_name)
        return obj.user_id if obj else None

    async def set_owner(self, skill_name: str, user_id: str) -> None:
        obj = await BaseDao.get_by_id(self, SkillOwnership, skill_name)
        if obj:
            obj.user_id = user_id
            await BaseDao.save(self, obj)
        else:
            obj = SkillOwnership(skill_name=skill_name, user_id=user_id)
            await BaseDao.insert(self, obj)

    async def get_user_skills(self, user_id: str) -> list[str]:
        objs = await BaseDao.get_list(self, SkillOwnership, where=[SkillOwnership.user_id == user_id])
        return [obj.skill_name for obj in objs]

    async def delete_ownership(self, skill_name: str) -> None:
        await BaseDao.delete_by_id(self, SkillOwnership, skill_name)

    async def get_all_ownerships(self) -> list[SkillOwnership]:
        return await BaseDao.get_all(self, SkillOwnership)
