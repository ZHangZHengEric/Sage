import os
import shutil
import io
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException
from ..utils.file import split_file_name
from PIL import Image
from loguru import logger

oss_router = APIRouter(prefix="/api/oss", tags=["OSS"])

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
async def upload_file(file: UploadFile = File(...)):
    try:
        user_home = Path.home()
        sage_files_dir = user_home / ".sage" / "files"
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
        
        return {"url": str(file_path.absolute())}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
