import os
import io
from pathlib import Path
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, UploadFile, File, HTTPException, Form, Request
from fastapi.responses import FileResponse
from common.utils.file import split_file_name
from PIL import Image
from loguru import logger
from common.utils.safe_remote_fetch import SafeRemoteFetchError, fetch_http_url_bytes_bounded

oss_router = APIRouter(prefix="/api/oss", tags=["OSS"])


class OssImportBody(BaseModel):
    url: str = Field(..., min_length=4)
    agent_id: Optional[str] = None


class OssSandboxUploadBody(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=240)
    filename: str = Field(..., min_length=1, max_length=480)

def _resolve_upload_root(agent_id: Optional[str]) -> Path:
    """根据 agent_id 解析上传文件根目录。"""
    user_home = Path.home()
    if agent_id:
        return user_home / ".sage" / "agents" / agent_id / "upload_files"
    return user_home / ".sage" / "files"


def _build_public_url(request: Request, agent_id: Optional[str], filename: str) -> str:
    """构建可被前端 <img src> / agent 后端拉取的 HTTP URL（保留旧字段，仅作降级展示用）。"""
    base = str(request.base_url).rstrip("/")
    if agent_id:
        return f"{base}/api/oss/file/{agent_id}/{filename}"
    return f"{base}/api/oss/file/_default/{filename}"

def compress_image_to_target_size(image: Image.Image, target_size_bytes: int = 1 * 1024 * 1024, max_dimension: int = 2048) -> bytes:
    """Compress image to target size (default 1MB) while maintaining aspect ratio."""
    # Resize if image is too large
    width, height = image.size
    if width > max_dimension or height > max_dimension:
        ratio = min(max_dimension / width, max_dimension / height)
        new_width = int(width * ratio)
        new_height = int(height * ratio)
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    # Try different quality levels to achieve target size
    quality = 95
    min_quality = 30
    
    while quality >= min_quality:
        buffer = io.BytesIO()
        # Convert to RGB if necessary (for PNG with transparency)
        if image.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            if image.mode in ('RGBA', 'LA'):
                background.paste(image, mask=image.split()[-1] if image.mode in ('RGBA', 'LA') else None)
                image = background
            else:
                image = image.convert('RGB')
        
        image.save(buffer, format='JPEG', quality=quality, optimize=True)
        size = buffer.tell()
        
        if size <= target_size_bytes:
            return buffer.getvalue()
        
        # Reduce quality and try again
        quality -= 5
    
    # If still too large, reduce dimensions further
    ratio = 0.8
    while True:
        new_width = int(width * ratio)
        new_height = int(height * ratio)
        resized = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        buffer = io.BytesIO()
        resized.save(buffer, format='JPEG', quality=min_quality, optimize=True)
        size = buffer.tell()
        
        if size <= target_size_bytes:
            return buffer.getvalue()
        
        ratio *= 0.8
        if ratio < 0.1:  # Prevent infinite loop
            break
    
    return buffer.getvalue()


def is_image_file(filename: str) -> bool:
    """Check if file is an image based on extension."""
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif'}
    ext = os.path.splitext(filename.lower())[1]
    return ext in image_extensions


def _persist_upload_bytes(
    *,
    request: Request,
    agent_id: Optional[str],
    filename_str: str,
    content: bytes,
) -> dict:
    sage_files_dir = _resolve_upload_root(agent_id)
    sage_files_dir.mkdir(parents=True, exist_ok=True)

    fn = filename_str or "unknown_file"
    origin, ext = split_file_name(fn)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    if ext and not ext.startswith("."):
        ext = "." + ext

    if is_image_file(fn):
        try:
            logger.info(f"Original file size (import/upload): {len(content)} bytes, start compress")
            image = Image.open(io.BytesIO(content))
            compressed_data = compress_image_to_target_size(image, target_size_bytes=1 * 1024 * 1024)
            ext = ".jpg"
            final_filename = f"{origin}_{timestamp}{ext}"
            file_path = sage_files_dir / final_filename
            with open(file_path, "wb") as buffer:
                buffer.write(compressed_data)
        except Exception:
            final_filename = f"{origin}_{timestamp}{ext}"
            file_path = sage_files_dir / final_filename
            with open(file_path, "wb") as buffer:
                buffer.write(content)
    else:
        final_filename = f"{origin}_{timestamp}{ext}"
        file_path = sage_files_dir / final_filename
        with open(file_path, "wb") as buffer:
            buffer.write(content)

    local_path = str(file_path.resolve())
    public_url = _build_public_url(request, agent_id, final_filename)
    payload = {
        "url": local_path,
        "local_path": local_path,
        "http_url": public_url,
        "filename": final_filename,
    }
    if agent_id:
        payload["agent_id"] = agent_id
    return payload


@oss_router.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    agent_id: Optional[str] = Form(None),
):
    """
    上传文件

    Args:
        file: 上传的文件
        agent_id: 可选的 Agent ID，如果提供，文件将保存到该 Agent 沙箱的 upload_files 文件夹
    """
    try:
        if agent_id:
            logger.info(f"Uploading file to agent sandbox: {agent_id}")
        else:
            logger.info("Uploading file to default location")

        filename_str = file.filename or "unknown_file"
        content = await file.read()

        # 桌面端 sidecar：返回本地路径 + HTTP 预览 URL。
        return _persist_upload_bytes(
            request=request,
            agent_id=agent_id,
            filename_str=filename_str,
            content=content,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@oss_router.post("/import_url")
async def import_url(request: Request, body: OssImportBody):
    try:
        data, _, suggested_name = await fetch_http_url_bytes_bounded(body.url.strip())
        return _persist_upload_bytes(
            request=request,
            agent_id=body.agent_id,
            filename_str=suggested_name or "import.bin",
            content=data,
        )
    except SafeRemoteFetchError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@oss_router.post("/import_sandbox_upload")
async def import_sandbox_upload(request: Request, body: OssSandboxUploadBody):
    """复用 ~/.sage/agents/<agent_id>/upload_files 下既有文件，供粘贴 markdown 绑定附件。"""
    aid = body.agent_id.strip()
    fn = body.filename.strip()
    if not aid:
        raise HTTPException(status_code=400, detail="invalid agent_id")
    if ".." in aid or "/" in aid or "\\" in aid:
        raise HTTPException(status_code=400, detail="invalid agent_id")
    if ".." in fn or "/" in fn or "\\" in fn:
        raise HTTPException(status_code=400, detail="invalid filename")

    base = _resolve_upload_root(aid).resolve()
    file_path = (base / fn).resolve()
    try:
        file_path.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="path traversal not allowed")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    local_path = str(file_path)
    public_url = _build_public_url(request, aid, fn)
    return {
        "url": local_path,
        "local_path": local_path,
        "http_url": public_url,
        "filename": fn,
        "agent_id": aid,
    }


@oss_router.get("/file/{agent_id}/{filename}")
async def serve_uploaded_file(agent_id: str, filename: str):
    """提供已上传文件的下载/预览。

    桌面端把上传的文件以 HTTP 方式静态暴露给前端，使 desktop 与 server 渲染逻辑
    完全一致（前端不再需要 Tauri convertFileSrc / readFile 这条本地路径分支）。
    """
    if "/" in filename or "\\" in filename or filename in ("..", "."):
        raise HTTPException(status_code=400, detail="invalid filename")

    if agent_id == "_default":
        base_dir = _resolve_upload_root(None)
    else:
        if "/" in agent_id or "\\" in agent_id or agent_id in ("..", "."):
            raise HTTPException(status_code=400, detail="invalid agent_id")
        base_dir = _resolve_upload_root(agent_id)

    file_path = (base_dir / filename).resolve()
    try:
        file_path.relative_to(base_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="path traversal not allowed")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    return FileResponse(str(file_path), filename=filename)
