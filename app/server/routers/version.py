from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Optional, List
from datetime import datetime

from app.server.models.system import VersionDao, Version

version_router = APIRouter(prefix="/api/system/version", tags=["Version"])

# Pydantic models
class ArtifactSchema(BaseModel):
    platform: str
    url: str
    signature: Optional[str] = None

class CreateVersionRequest(BaseModel):
    version: str
    release_notes: str
    artifacts: List[ArtifactSchema]

class VersionResponse(BaseModel):
    version: str
    notes: str
    pub_date: str
    platforms: Dict[str, Dict[str, str]]

class WebVersionResponse(BaseModel):
    version: str
    release_notes: str
    pub_date: datetime
    artifacts: List[ArtifactSchema]

@version_router.get("/check")
async def check_update():
    """
    Endpoint for Tauri v2 Updater.
    Returns the latest version information in the format Tauri expects.
    """
    dao = VersionDao()
    latest = await dao.get_latest_version()
    
    if not latest:
        # Return 204 or just an empty structure that implies no update?
        # Tauri expects a JSON response. If no version, returning 404 is acceptable.
        raise HTTPException(status_code=404, detail="No version found")
    
    platforms = {}
    for artifact in latest.artifacts:
        platforms[artifact.platform] = {
            "url": artifact.url,
            "signature": artifact.signature or ""
        }

    return {
        "version": latest.version,
        "notes": latest.release_notes,
        "pub_date": latest.pub_date.isoformat(),
        "platforms": platforms
    }

@version_router.get("/latest")
async def get_latest_version():
    """
    Endpoint for Web Download Page.
    """
    dao = VersionDao()
    latest = await dao.get_latest_version()
    
    if not latest:
        # Return empty response instead of 404 to avoid frontend error
        return None

    artifacts = [
        ArtifactSchema(
            platform=a.platform,
            url=a.url,
            signature=a.signature
        ) for a in latest.artifacts
    ]

    return {
        "version": latest.version,
        "release_notes": latest.release_notes,
        "pub_date": latest.pub_date,
        "artifacts": artifacts
    }

@version_router.post("")
async def create_version(request: CreateVersionRequest):
    """
    Create a new version (Admin only - practically).
    """
    dao = VersionDao()
    
    # Check if version exists
    existing = await dao.get_version_by_tag(request.version)
    if existing:
        raise HTTPException(status_code=400, detail="Version already exists")

    artifacts_dict = [a.model_dump() for a in request.artifacts]
    
    new_version = await dao.create_version(
        version_str=request.version,
        release_notes=request.release_notes,
        artifacts=artifacts_dict
    )
    
    # Re-fetch to get artifacts loaded if create_version doesn't return them populated (it does return the object but session closed)
    # Actually create_version in previous step returns object bound to session but session closes.
    # We should re-fetch.
    created = await dao.get_version_by_tag(request.version)
    
    artifacts = [
        ArtifactSchema(
            platform=a.platform,
            url=a.url,
            signature=a.signature
        ) for a in created.artifacts
    ]

    return {
        "version": created.version,
        "release_notes": created.release_notes,
        "pub_date": created.pub_date,
        "artifacts": artifacts
    }

@version_router.get("")
async def list_versions():
    """
    List all versions (Admin)
    """
    dao = VersionDao()
    
    # Check if table exists or handle DB errors gracefully
    # Assuming table exists.
    
    versions = await dao.list_versions()
    # If versions is empty, it returns []
    return [
        {
            "version": v.version,
            "release_notes": v.release_notes,
            "pub_date": v.pub_date,
            "artifacts": [
                ArtifactSchema(
                    platform=a.platform,
                    url=a.url,
                    signature=a.signature
                ) for a in v.artifacts
            ]
        } for v in versions
    ]

@version_router.delete("/{version_str}")
async def delete_version(version_str: str):
    """
    Delete a version
    """
    dao = VersionDao()
    version = await dao.get_version_by_tag(version_str)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    
    await dao.delete_by_id(Version, version.id)
    return {"success": True}
