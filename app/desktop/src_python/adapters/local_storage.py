import os
import shutil
import uuid
from typing import Optional
from loguru import logger
from fastapi.responses import FileResponse
from fastapi import APIRouter

STORAGE_ROOT = os.path.join(os.getcwd(), "storage")
os.makedirs(STORAGE_ROOT, exist_ok=True)

# Define a router to serve files
file_router = APIRouter()

@file_router.get("/files/{filename}")
async def get_file(filename: str):
    file_path = os.path.join(STORAGE_ROOT, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return {"error": "File not found"}, 404

async def upload_kdb_file(base_name: str, data: bytes, content_type: str) -> str:
    """
    Simulate S3 upload by saving to local disk and returning a localhost URL.
    """
    # Create unique filename
    ext = os.path.splitext(base_name)[1]
    filename = f"{uuid.uuid4()}{ext}"
    file_path = os.path.join(STORAGE_ROOT, filename)
    
    with open(file_path, "wb") as f:
        f.write(data)
    
    # We need the port the server is running on. 
    # Since this is a sidecar, we might not know the exact port easily unless we pass it or use a fixed relative path.
    # However, if we return a relative path, the frontend might prepend the base URL.
    # The current S3 implementation returns a full URL.
    
    # Assuming the API base URL is available in the frontend, we can return a relative path like "/files/{filename}"
    # and let the frontend handle it, OR we construct a full URL if we know the host/port.
    
    # For simplicity, let's return a relative path starting with /files/
    # The frontend or API client should handle this if it expects a full URL.
    # If the original code expects a full URL (http...), we might need to adjust.
    # But usually clients can handle relative URLs if they are using an API client with base_url.
    
    # Wait, the S3 implementation returns `public_base + "/" + object_name`.
    # `public_base` is usually `http://minio:9000/bucket`.
    # Here we can return `/files/{filename}`.
    
    logger.info(f"Saved local file: {file_path}")
    return f"/files/{filename}"

# Mock init_s3_client to do nothing or return a dummy
async def init_s3_client(cfg=None):
    logger.info("Local S3 Client Initialized (No-op)")
    return "LocalFileClient"

async def close_s3_client():
    pass
