from fastapi import UploadFile

from ..core.client.s3 import upload_kdb_file


async def upload_file_to_oss(file: UploadFile) -> str:
    content = await file.read()
    return await upload_kdb_file(file.filename, content, file.content_type)
