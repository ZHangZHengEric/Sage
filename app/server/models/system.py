from sqlalchemy import Boolean, String, Text, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship, selectinload
from datetime import datetime

from .base import Base, BaseDao
from ..utils.id import generate_short_id

class SystemInfo(Base):
    __tablename__ = "system_info"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=True)

    def __init__(self, key: str, value: str):
        self.key = key
        self.value = value

class Version(Base):
    __tablename__ = "version"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: generate_short_id())
    version: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    release_notes: Mapped[str] = mapped_column(Text, nullable=True)
    pub_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    artifacts: Mapped[list["VersionArtifact"]] = relationship(back_populates="version", cascade="all, delete-orphan")

class VersionArtifact(Base):
    __tablename__ = "version_artifact"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: generate_short_id())
    version_id: Mapped[str] = mapped_column(ForeignKey("version.id"))
    platform: Mapped[str] = mapped_column(String(32)) # e.g., darwin-aarch64, darwin-x86_64, windows-x86_64, linux-x86_64, linux-aarch64
    
    installer_url: Mapped[str] = mapped_column(String(512), nullable=True)
    updater_url: Mapped[str] = mapped_column(String(512), nullable=True)
    updater_signature: Mapped[str] = mapped_column(Text, nullable=True)
    
    version: Mapped["Version"] = relationship(back_populates="artifacts")

class SystemInfoDao(BaseDao):
    async def get_by_key(self, key: str) -> str | None:
        info = await self.get_by_id(SystemInfo, key)
        return info.value if info else None

    async def set_value(self, key: str, value: str) -> bool:
        info = await self.get_by_id(SystemInfo, key)
        if info:
            info.value = value
            return await self.save(info)
        else:
            info = SystemInfo(key=key, value=value)
            await self.insert(info)
            return True

class VersionDao(BaseDao):
    async def get_latest_version(self) -> Version | None:
        return await self.get_first(
            Version,
            order_by=Version.pub_date.desc(),
            options=[selectinload(Version.artifacts)]
        )

    async def get_version_by_tag(self, tag: str) -> Version | None:
        return await self.get_first(
            Version,
            where=[Version.version == tag],
            options=[selectinload(Version.artifacts)]
        )
            
    async def list_versions(self) -> list[Version]:
        return await self.get_all(
            Version,
            order_by=Version.pub_date.desc(),
            options=[selectinload(Version.artifacts)]
        )

    async def create_version(self, version_str: str, release_notes: str, artifacts: list[dict]) -> Version | None:
        """Create a new version with artifacts"""
        v = Version(version=version_str, release_notes=release_notes, pub_date=datetime.utcnow())
        
        db = await self._get_db()
        async with db.get_session() as session:
            session.add(v)
            await session.flush() # Ensure ID is generated (via default function)
            
            for art in artifacts:
                updater_url = art.get('updater_url')
                if updater_url:
                    updater_url = "https://ghfast.top/" + updater_url
                
                a = VersionArtifact(
                    version_id=v.id,
                    platform=art['platform'],
                    installer_url=art.get('installer_url'),
                    updater_url=updater_url,
                    updater_signature=art.get('updater_signature')
                )
                session.add(a)
            # Session commit happens automatically on exit if configured, or we trust the framework
        
        # Re-fetch to return fully loaded object with artifacts
        return await self.get_version_by_tag(version_str)

    async def delete_by_tag(self, tag: str) -> bool:
        """Delete a version by tag"""
        version = await self.get_version_by_tag(tag)
        if version:
            return await self.delete_by_id(Version, version.id)
        return False
