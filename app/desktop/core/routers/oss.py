import os
import shutil
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException
from ..utils.file import split_file_name

oss_router = APIRouter(prefix="/api/oss", tags=["OSS"])

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
            
        final_filename = f"{origin}_{timestamp}{ext}"
        
        file_path = sage_files_dir / final_filename
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        return {"url": str(file_path.absolute())}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
