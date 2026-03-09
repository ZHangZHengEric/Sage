from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, ConfigDict
from typing import Dict, Optional, List
from datetime import datetime

from app.server.models.system import VersionDao, Version
from app.server.core.render import Response
from app.server.schemas.base import BaseResponse

version_router = APIRouter(prefix="/api/system/version", tags=["Version"])

async def get_version_dao() -> VersionDao:
    return VersionDao()

# Pydantic models
class ArtifactSchema(BaseModel):
    platform: str
    installer_url: Optional[str] = None
    updater_url: Optional[str] = None
    updater_signature: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class CreateVersionRequest(BaseModel):
    version: str
    release_notes: str
    artifacts: List[ArtifactSchema]

class TauriPlatform(BaseModel):
    url: str
    signature: str

class TauriUpdateResponse(BaseModel):
    version: str
    notes: str
    pub_date: str
    platforms: Dict[str, TauriPlatform]

class WebVersionResponse(BaseModel):
    version: str
    release_notes: str
    pub_date: datetime
    artifacts: List[ArtifactSchema]
    model_config = ConfigDict(from_attributes=True)

@version_router.get("/check", response_model=TauriUpdateResponse)
async def check_update(dao: VersionDao = Depends(get_version_dao)):
    """
    Endpoint for Tauri v2 Updater.
    Returns the latest version information in the format Tauri expects.
    """
    latest = await dao.get_latest_version()
    
    if not latest:
        # Tauri expects a JSON response. If no version, returning 404 is acceptable.
        raise HTTPException(status_code=404, detail="No version found")
    
    platforms = {}
    for artifact in latest.artifacts:
        # Only include platforms that have an updater URL
        if artifact.updater_url:
            platforms[artifact.platform] = TauriPlatform(
                url=artifact.updater_url,
                signature=artifact.updater_signature or ""
            )

    return TauriUpdateResponse(
        version=latest.version,
        notes=latest.release_notes,
        pub_date=latest.pub_date.isoformat() + "Z",
        platforms=platforms
    )

@version_router.get("/latest", response_model=BaseResponse[Optional[WebVersionResponse]])
async def get_latest_version(dao: VersionDao = Depends(get_version_dao)):
    """
    Endpoint for Web Download Page.
    """
    latest = await dao.get_latest_version()
    return await Response.succ(data=latest)

@version_router.post("", response_model=BaseResponse[WebVersionResponse])
async def create_version(request: CreateVersionRequest, dao: VersionDao = Depends(get_version_dao)):
    """
    Create a new version (Admin only - practically).
    """
    # Check if version exists
    existing = await dao.get_version_by_tag(request.version)
    if existing:
        return await Response.error(code=400, message="Version already exists")

    artifacts_dict = [a.model_dump() for a in request.artifacts]
    
    created = await dao.create_version(
        version_str=request.version,
        release_notes=request.release_notes,
        artifacts=artifacts_dict
    )
    
    if not created:
        return await Response.error(code=500, message="Failed to create version")

    return await Response.succ(data=created, message="Version created successfully")

@version_router.get("", response_model=BaseResponse[List[WebVersionResponse]])
async def list_versions(dao: VersionDao = Depends(get_version_dao)):
    """
    List all versions (Admin)
    """
    versions = await dao.list_versions()
    return await Response.succ(data=versions)

@version_router.delete("/{version_str}", response_model=BaseResponse[dict])
async def delete_version(version_str: str, dao: VersionDao = Depends(get_version_dao)):
    """
    Delete a version
    """
    deleted = await dao.delete_by_tag(version_str)
    if not deleted:
        return await Response.error(code=404, message="Version not found")
    
    return await Response.succ(data={"success": True}, message="Version deleted successfully")
