from fastapi import UploadFile

from common.core.client.s3 import upload_kdb_file


async def upload_file_to_oss(file: UploadFile, path: str = None) -> str:
    content = await file.read()
    if path:
        from common.core.client.s3 import upload_file_with_path
        return await upload_file_with_path(content, path, file.content_type)
    
    return await upload_kdb_file(file.filename, content, file.content_type)
