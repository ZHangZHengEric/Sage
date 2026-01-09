from ..core.render import Response
from ..core.client.minio import upload_kdb_file
from fastapi import APIRouter, File, UploadFile

oss_router = APIRouter(prefix="/api/oss", tags=["OSS"])


@oss_router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    上传文件到 MinIO
    """
    content = await file.read()
    url = await upload_kdb_file(file.filename, content, file.content_type)
    return await Response.succ(data={"url": url})
