from fastapi import APIRouter, File, UploadFile

from ..core.render import Response
from ..services.oss import upload_file_to_oss

oss_router = APIRouter(prefix="/api/oss", tags=["OSS"])


@oss_router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    url = await upload_file_to_oss(file)
    return await Response.succ(data={"url": url})
