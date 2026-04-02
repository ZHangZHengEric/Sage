from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, ConfigDict
from typing import Dict, Optional, List, Any
from datetime import datetime, timedelta
import httpx
import asyncio
import logging

from common.core.render import Response
from common.models.system import VersionDao, Version
from common.schemas.base import BaseResponse

logger = logging.getLogger(__name__)

version_router = APIRouter(prefix="/api/system/version", tags=["Version"])

# GitHub Release Cache
_github_cache = {
    "data": None,
    "last_updated": None
}
CACHE_TTL = timedelta(minutes=15)
GITHUB_REPO = "ZHangZHengEric/Sage"

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

async def fetch_github_release_info() -> Optional[Dict[str, Any]]:
    """
    Fetch release info from GitHub.
    Returns parsed data suitable for creating a version in DB.
    """
    global _github_cache
    now = datetime.now()

    if _github_cache["data"] and _github_cache["last_updated"]:
        if now - _github_cache["last_updated"] < CACHE_TTL:
            return _github_cache["data"]

    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10.0, follow_redirects=True)
            resp.raise_for_status()
            release_data = resp.json()
            
            tag_name = release_data.get("tag_name", "")
            # Clean version string: remove 'desktop-v' and leading 'v'
            version = tag_name.replace("desktop-v", "").lstrip("v")
            notes = release_data.get("body", "")
            pub_date = release_data.get("published_at", "")
            
            assets = release_data.get("assets", [])
            
            # Helper to fetch signature content
            async def get_sig_content(asset_url):
                try:
                    r = await client.get(asset_url, timeout=10.0, follow_redirects=True)
                    r.raise_for_status()
                    return r.text
                except Exception as e:
                    logger.error(f"Failed to fetch signature from {asset_url}: {e}")
                    return ""

            # Intermediate storage to group assets by platform
            # key: platform, value: { installer: url, updater: url, sig_url: url }
            platform_assets = {}

            def get_platform(name):
                name_lower = name.lower()
                # Mac detection
                if any(k in name_lower for k in ["darwin", "macos", "apple", ".dmg", ".app.tar.gz"]):
                    if any(k in name_lower for k in ["aarch64", "arm64"]):
                        return "darwin-aarch64"
                    if any(k in name_lower for k in ["x86_64", "x64", "intel"]):
                         return "darwin-x86_64"
                
                # Windows detection
                if any(
                    k in name_lower
                    for k in ["windows", "win", ".exe", ".msi", ".nsis.zip", "-setup.zip", ".msi.zip"]
                ):
                    if any(k in name_lower for k in ["x64", "x86_64"]):
                        return "windows-x86_64"
                
                # Linux detection
                if any(k in name_lower for k in ["linux", "appimage", ".deb"]):
                    if any(k in name_lower for k in ["x86_64", "amd64"]):
                        return "linux-x86_64"
                    if any(k in name_lower for k in ["aarch64", "arm64"]):
                        return "linux-aarch64"
                return None

            for asset in assets:
                name = asset["name"]
                name_lower = name.lower()
                url = asset["browser_download_url"]
                
                if name.endswith(".sig"):
                    continue

                platform = get_platform(name)
                # If platform not detected but it is a .tar.gz and has 'aarch64' or 'x86_64', try to infer
                if not platform and name.endswith(".tar.gz"):
                    if "aarch64" in name.lower() or "arm64" in name.lower():
                         # Likely Mac ARM or Linux ARM
                         # Assuming Mac if not specified
                         platform = "darwin-aarch64"
                    elif "x86_64" in name.lower():
                         # Ambiguous: could be Mac Intel, Linux, or Windows (unlikely for tar.gz updater)
                         # Let's check if we can differentiate
                         # If no other clues, maybe skip or default?
                         # The provided asset `Sage-1.0.0-aarch64.tar.gz` was missed.
                         pass

                if not platform:
                    continue
                
                if platform not in platform_assets:
                    platform_assets[platform] = {"installer": None, "updater": None, "sig_url": None}

                # Determine type
                # Updater packages
                # Windows
                # NSIS: Sage-x.x.x-x86_64-setup.zip
                is_updater = False
                if name_lower.endswith("-setup.zip") or name_lower.endswith(".nsis.zip") or name_lower.endswith(".msi.zip"):
                    is_updater = True
                elif name_lower.endswith(".appimage.tar.gz"):
                    is_updater = True
                elif platform.startswith("darwin") and name_lower.endswith(".tar.gz") and not name_lower.endswith(".app.tar.gz"):
                     # It seems for mac it is just .tar.gz in the provided example
                     is_updater = True
                elif platform.startswith("darwin") and name_lower.endswith(".app.tar.gz"):
                     is_updater = True

                if is_updater:
                    platform_assets[platform]["updater"] = url
                    # Check if signature exists in assets
                    sig_name = name + ".sig"
                    for a in assets:
                        if a["name"] == sig_name:
                            platform_assets[platform]["sig_url"] = a["browser_download_url"]
                            break
                # Installer packages
                elif (
                    name_lower.endswith(".dmg")
                    or name_lower.endswith(".exe")
                    or name_lower.endswith(".msi")
                    or name_lower.endswith(".appimage")
                    or name_lower.endswith(".deb")
                ):
                    platform_assets[platform]["installer"] = url

            # Build artifacts list
            artifacts = []
            sig_tasks = []
            temp_artifacts = []
            
            # Debug log
            logger.info(f"Found platform assets: {platform_assets}")

            for platform, files in platform_assets.items():
                if files["updater"] and files["sig_url"]:
                    sig_tasks.append(get_sig_content(files["sig_url"]))
                    
                    # For Windows NSIS, installer is .exe, updater is .zip
                    # For Windows MSI, installer is .msi, updater is .msi.zip
                    # For macOS, installer is .dmg, updater is .tar.gz
                    # For Linux, installer is .AppImage, updater is .AppImage.tar.gz

                    # If installer_url is missing, fallback logic:
                    # - Windows: prefer updater url (zip) ? No, updater zip cannot be installed directly usually.
                    #   But if we missed the .exe asset, we might not have a choice or should leave it None.
                    #   However, in previous logic: `files["installer"] or files["updater"]`
                    #   If we have NSIS updater (.zip), we likely have NSIS installer (.exe).
                    
                    installer_url = files["installer"]
                    # If no installer found but we have updater, check if we can/should use updater as installer?
                    # Generally NO for NSIS (zip is not installer).
                    # For AppImage, maybe?
                    # Let's keep existing logic but be aware.
                    
                    temp_artifacts.append({
                        "platform": platform,
                        "installer_url": installer_url, 
                        "updater_url": files["updater"],
                        "updater_signature": None # Will be filled later
                    })
                elif files["installer"]:
                     # Only installer, no updater
                     artifacts.append({
                        "platform": platform,
                        "installer_url": files["installer"],
                        "updater_url": None,
                        "updater_signature": None
                     })

            # Fetch signatures
            if sig_tasks:
                signatures = await asyncio.gather(*sig_tasks)
                for i, sig in enumerate(signatures):
                    temp_artifacts[i]["updater_signature"] = sig
                    artifacts.append(temp_artifacts[i])

            result = {
                "version": version,
                "notes": notes,
                "pub_date": pub_date,
                "artifacts": artifacts
            }
            
            _github_cache["data"] = result
            _github_cache["last_updated"] = now
            return result

    except Exception as e:
        logger.error(f"Error fetching GitHub release: {e}")
        return None

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

@version_router.post("/import_github", response_model=BaseResponse[WebVersionResponse])
async def import_github_version(dao: VersionDao = Depends(get_version_dao)):
    """
    Import latest version from GitHub Release.
    """
    data = await fetch_github_release_info()
    if not data:
        return await Response.error(code=500, message="Failed to fetch from GitHub")
    # Check if version exists
    existing = await dao.get_version_by_tag(data["version"])
    if existing:
        # If exists, delete it first (overwrite)
        await dao.delete_by_tag(data["version"])
    
    # Create version
    created = await dao.create_version(
        version_str=data["version"],
        release_notes=data["notes"],
        artifacts=data["artifacts"]
    )
    
    if not created:
        return await Response.error(code=500, message="Failed to create version")
        
    return await Response.succ(data=created, message=f"Version {data['version']} imported successfully")

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
