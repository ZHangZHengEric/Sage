from fastapi import APIRouter, File, UploadFile, Form
from ..core.render import Response
from ..services.oss import upload_file_to_oss

oss_router = APIRouter(prefix="/api/oss", tags=["OSS"])


@oss_router.post("/upload")
async def upload_file(file: UploadFile = File(...), path: str = Form(None)):
    url = await upload_file_to_oss(file, path)
    return await Response.succ(data={"url": url})
