import os
import shutil
import io
from pathlib import Path
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, Form, Request
from fastapi.responses import FileResponse
from common.utils.file import split_file_name
from PIL import Image
from loguru import logger

oss_router = APIRouter(prefix="/api/oss", tags=["OSS"])


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
        sage_files_dir = _resolve_upload_root(agent_id)
        if agent_id:
            logger.info(f"Uploading file to agent sandbox: {agent_id}, path: {sage_files_dir}")
        else:
            logger.info(f"Uploading file to default location: {sage_files_dir}")

        # 确保目录存在
        sage_files_dir.mkdir(parents=True, exist_ok=True)

        filename_str = file.filename or "unknown_file"
        origin, ext = split_file_name(filename_str)

        # Use a timestamp to avoid name collision
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        # Ensure ext starts with dot if not empty
        if ext and not ext.startswith("."):
            ext = "." + ext

        # Check if it's an image file and needs compression
        if is_image_file(filename_str):
            try:
                # Read file content
                content = await file.read()
                logger.info(f"Original file size: {len(content)} bytes, start compress")
                # Open image
                image = Image.open(io.BytesIO(content))

                # Compress image to 1MB
                compressed_data = compress_image_to_target_size(image, target_size_bytes=1 * 1024 * 1024)

                # Update extension to .jpg for compressed images
                ext = ".jpg"
                final_filename = f"{origin}_{timestamp}{ext}"
                file_path = sage_files_dir / final_filename

                # Save compressed image
                with open(file_path, "wb") as buffer:
                    buffer.write(compressed_data)

            except Exception as img_error:
                # If image processing fails, fall back to original file
                final_filename = f"{origin}_{timestamp}{ext}"
                file_path = sage_files_dir / final_filename
                file.file.seek(0)
                with open(file_path, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)
        else:
            # Non-image file, save as-is
            final_filename = f"{origin}_{timestamp}{ext}"
            file_path = sage_files_dir / final_filename
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

        # 桌面端 sidecar 与 agent 跑在同一台机器上，直接把"本地绝对路径"作为 url 返回：
        # - markdown 引用 / image_url part 都用本地路径，agent 不再需要走 HTTP 抓回来或反解 localhost URL；
        # - 前端 MarkdownRenderer 已有 `convertFileSrc / data-local-image` 分支，能直接渲染本地路径；
        # - http_url 字段仍然保留（指向 sidecar 的 GET /api/oss/file/...），便于以后调试 / 在浏览器中打开。
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
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


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
