from io import BytesIO

import pytest
from fastapi import UploadFile

from common.core.exceptions import SageHTTPException
from common.services import skill_router_service


@pytest.mark.asyncio
async def test_build_upload_skills_response_keeps_partial_success(monkeypatch):
    async def fake_import_skill_by_file(file, *args, **kwargs):
        if file.filename == "bad.txt":
            raise SageHTTPException(status_code=400, detail="仅支持 ZIP 文件")
        return f"技能 '{file.filename}' 导入成功"

    monkeypatch.setattr(
        skill_router_service.skill_service,
        "import_skill_by_file",
        fake_import_skill_by_file,
    )

    files = [
        UploadFile(file=BytesIO(b"zip"), filename="good.zip"),
        UploadFile(file=BytesIO(b"text"), filename="bad.txt"),
    ]

    response = await skill_router_service.build_upload_skills_response(
        files=files,
        user_id="u_1",
    )

    assert response["data"]["success_count"] == 1
    assert response["data"]["failed_count"] == 1
    assert response["data"]["results"] == [
        {
            "filename": "good.zip",
            "success": True,
            "message": "技能 'good.zip' 导入成功",
        },
        {
            "filename": "bad.txt",
            "success": False,
            "message": "仅支持 ZIP 文件",
        },
    ]
