import asyncio
import mimetypes
from pathlib import Path

from fastapi import UploadFile

from common.core.client.s3 import upload_kdb_file
from common.core.exceptions import SageHTTPException
from common.utils.safe_remote_fetch import SafeRemoteFetchError, fetch_http_url_bytes_bounded


async def upload_file_to_oss(file: UploadFile, path: str = None) -> str:
    content = await file.read()
    if path:
        from common.core.client.s3 import upload_file_with_path
        return await upload_file_with_path(content, path, file.content_type)

    return await upload_kdb_file(file.filename, content, file.content_type)


async def import_remote_url_to_oss(url: str) -> tuple[str, str]:
    try:
        body, content_type, suggested_name = await fetch_http_url_bytes_bounded(url.strip())
        if not body:
            raise SageHTTPException(detail="远端资源为空")
        public_url = await upload_kdb_file(suggested_name, body, content_type)
        return public_url, suggested_name
    except SafeRemoteFetchError as e:
        raise SageHTTPException(detail=str(e)) from e


def resolve_sage_agent_upload_files_path(agent_id: str, filename: str) -> Path:
    """校验并解析 ~/.sage/agents/<agent_id>/upload_files/<filename>。"""
    aid = (agent_id or "").strip()
    fn = (filename or "").strip()
    if not aid or not fn:
        raise SageHTTPException(detail="非法参数")
    if ".." in aid or "/" in aid or "\\" in aid:
        raise SageHTTPException(detail="非法 agent_id")
    if ".." in fn or "/" in fn or "\\" in fn:
        raise SageHTTPException(detail="非法文件名")
    base = (Path.home() / ".sage" / "agents" / aid / "upload_files").resolve()
    path = (base / fn).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        raise SageHTTPException(detail="path traversal not allowed")
    if not path.is_file():
        raise SageHTTPException(detail="文件不存在或不可读")
    return path


async def import_sandbox_upload_file_to_oss(agent_id: str, filename: str) -> tuple[str, str]:
    path = resolve_sage_agent_upload_files_path(agent_id, filename)
    content = await asyncio.to_thread(path.read_bytes)
    if not content:
        raise SageHTTPException(detail="文件为空")
    ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    public_url = await upload_kdb_file(fn := path.name, content, ctype)
    return public_url, fn
