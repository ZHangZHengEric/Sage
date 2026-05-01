from fastapi import APIRouter, File, UploadFile, Form
from pydantic import BaseModel, Field

from common.core.render import Response
from ..services.oss import (
    import_remote_url_to_oss,
    import_sandbox_upload_file_to_oss,
    upload_file_to_oss,
)

oss_router = APIRouter(prefix="/api/oss", tags=["OSS"])


class OssImportBody(BaseModel):
    url: str = Field(..., min_length=4, description="远端资源 URL")


class OssSandboxUploadBody(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=240, description="Agent 目录名")
    filename: str = Field(..., min_length=1, max_length=480, description="upload_files 下文件名（仅 basename）")


@oss_router.post("/upload")
async def upload_file(file: UploadFile = File(...), path: str = Form(None)):
    url = await upload_file_to_oss(file, path)
    return await Response.succ(data={"url": url})


@oss_router.post("/import_url")
async def import_url(body: OssImportBody):
    url, filename_hint = await import_remote_url_to_oss(body.url)
    return await Response.succ(data={"url": url, "filename": filename_hint})


@oss_router.post("/import_sandbox_upload")
async def import_sandbox_upload(body: OssSandboxUploadBody):
    """从本机 ~/.sage/agents/<agent_id>/upload_files/<filename> 读取已上传文件并写入 OSS。"""
    url, filename_hint = await import_sandbox_upload_file_to_oss(body.agent_id, body.filename)
    return await Response.succ(data={"url": url, "filename": filename_hint})
