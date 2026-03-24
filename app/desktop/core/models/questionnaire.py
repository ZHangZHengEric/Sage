from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import JSON, String, DateTime, select
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BaseDao, get_local_now


class QuestionnaireSession(Base):
    """问卷会话 - 临时存储，获取结果后即删除"""
    __tablename__ = "questionnaire_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    questions: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, submitted, expired
    answers: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    wait_time: Mapped[int] = mapped_column(default=300)  # 等待时间(秒)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_local_now)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class QuestionnaireDao(BaseDao):
    """问卷数据访问对象"""

    async def create_session(self, session: QuestionnaireSession) -> QuestionnaireSession:
        """创建问卷会话"""
        await self.insert(session)
        return session

    async def get_session(self, session_id: str) -> Optional[QuestionnaireSession]:
        """获取问卷会话"""
        return await self.get_by_id(QuestionnaireSession, session_id)

    async def submit_answers(
        self,
        session_id: str,
        answers: Dict[str, Any]
    ) -> bool:
        """提交答案"""
        session = await self.get_session(session_id)
        if not session:
            return False
        if session.status != "pending":
            return False
        if datetime.now() > session.expires_at:
            return False

        session.answers = answers
        session.status = "submitted"
        session.submitted_at = get_local_now()
        await self.save(session)
        return True

    async def delete_session(self, session_id: str) -> bool:
        """删除问卷会话"""
        return await self.delete_by_id(QuestionnaireSession, session_id)

    async def cleanup_expired(self) -> int:
        """清理过期的问卷会话"""
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(QuestionnaireSession).where(
                QuestionnaireSession.expires_at < get_local_now(),
                QuestionnaireSession.status == "pending"
            )
            result = await session.execute(stmt)
            expired_sessions = result.scalars().all()

            count = 0
            for s in expired_sessions:
                s.status = "expired"
                await session.merge(s)
                count += 1

            return count
