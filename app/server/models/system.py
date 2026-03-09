from sqlalchemy import Boolean, String, Text, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship, selectinload
from datetime import datetime

from .base import Base, BaseDao

class SystemInfo(Base):
    __tablename__ = "system_info"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=True)

    def __init__(self, key: str, value: str):
        self.key = key
        self.value = value

class Version(Base):
    __tablename__ = "version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    release_notes: Mapped[str] = mapped_column(Text, nullable=True)
    pub_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    artifacts: Mapped[list["VersionArtifact"]] = relationship(back_populates="version", cascade="all, delete-orphan")

class VersionArtifact(Base):
    __tablename__ = "version_artifact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("version.id"))
    platform: Mapped[str] = mapped_column(String(32)) # e.g., darwin-aarch64, darwin-x86_64, windows-x86_64, linux-x86_64
    url: Mapped[str] = mapped_column(String(512))
    signature: Mapped[str] = mapped_column(Text, nullable=True)
    
    version: Mapped["Version"] = relationship(back_populates="artifacts")

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

class VersionDao(BaseDao):
    async def get_latest_version(self) -> Version | None:
        db = await self._get_db()
        async with db.get_session() as session:
            result = await session.execute(
                self.select(Version).options(selectinload(Version.artifacts)).order_by(Version.id.desc()).limit(1)
            )
            return result.scalars().first()

    async def get_version_by_tag(self, tag: str) -> Version | None:
        db = await self._get_db()
        async with db.get_session() as session:
            result = await session.execute(
                self.select(Version).options(selectinload(Version.artifacts)).where(Version.version == tag)
            )
            return result.scalars().first()
            
    async def list_versions(self) -> list[Version]:
        db = await self._get_db()
        async with db.get_session() as session:
            result = await session.execute(
                self.select(Version).options(selectinload(Version.artifacts)).order_by(Version.id.desc())
            )
            return result.scalars().all()

    async def create_version(self, version_str: str, release_notes: str, artifacts: list[dict]) -> Version:
        """Create a new version with artifacts"""
        db = await self._get_db()
        async with db.get_session() as session:
            v = Version(version=version_str, release_notes=release_notes)
            session.add(v)
            await session.flush() # Ensure ID is generated
            
            for art in artifacts:
                a = VersionArtifact(
                    version_id=v.id,
                    platform=art['platform'],
                    url=art['url'],
                    signature=art.get('signature')
                )
                session.add(a)
            # Session commit happens automatically on exit if configured, or we trust the framework
            return v
