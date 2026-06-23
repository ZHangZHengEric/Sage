from io import BytesIO

import pytest
from fastapi import UploadFile

from common.core.exceptions import SageHTTPException
from common.services import skill_router_service, skill_service


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


def test_collect_skill_path_candidates_expands_skill_folders_and_zips(tmp_path):
    skill_a = tmp_path / "skill-a"
    skill_a.mkdir()
    (skill_a / "SKILL.md").write_text(
        "---\nname: skill-a\ndescription: demo\n---\n",
        encoding="utf-8",
    )
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "skill-b.zip").write_bytes(b"zip")
    asset_skill = tmp_path / "asset-skill"
    asset_skill.mkdir()
    (asset_skill / "SKILL.md").write_text(
        "---\nname: asset-skill\ndescription: demo\n---\n",
        encoding="utf-8",
    )
    (asset_skill / "asset.zip").write_bytes(b"asset")

    candidates = skill_service._collect_skill_path_candidates_sync(str(tmp_path))

    assert ("dir", str(skill_a), "skill-a") in candidates
    assert ("zip", str(nested / "skill-b.zip"), "skill-b.zip") in candidates
    assert ("dir", str(asset_skill), "asset-skill") in candidates
    assert ("zip", str(asset_skill / "asset.zip"), "asset.zip") not in candidates


@pytest.mark.asyncio
async def test_import_desktop_skills_by_paths_returns_per_path_results(monkeypatch):
    async def fake_collect(path):
        if path == "/bundle":
            return [
                ("dir", "/bundle/skill-a", "skill-a"),
                ("zip", "/bundle/bad.zip", "bad.zip"),
            ]
        return []

    async def fake_process_dir(*args):
        return True, "技能 'skill-a' 导入成功"

    async def fake_process_zip(*args):
        return False, "无效的 ZIP 文件"

    monkeypatch.setattr(skill_service, "_is_desktop_mode", lambda: True)
    monkeypatch.setattr(skill_service, "get_skill_manager", lambda: object())
    monkeypatch.setattr(skill_service, "_collect_skill_path_candidates", fake_collect)
    monkeypatch.setattr(
        skill_service, "_process_desktop_dir_and_register", fake_process_dir
    )
    monkeypatch.setattr(
        skill_service, "_process_desktop_zip_and_register", fake_process_zip
    )

    result = await skill_service.import_desktop_skills_by_paths(["/bundle"], "u_1")

    assert result["success_count"] == 1
    assert result["failed_count"] == 1
    assert result["results"] == [
        {
            "filename": "skill-a",
            "path": "/bundle/skill-a",
            "success": True,
            "message": "技能 'skill-a' 导入成功",
        },
        {
            "filename": "bad.zip",
            "path": "/bundle/bad.zip",
            "success": False,
            "message": "无效的 ZIP 文件",
        },
    ]


@pytest.mark.asyncio
async def test_import_desktop_skills_by_paths_imports_real_skill_directory(
    tmp_path, monkeypatch
):
    source = tmp_path / "source-skill"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nname: copied-skill\ndescription: demo\n---\n",
        encoding="utf-8",
    )
    (source / "guide.md").write_text("hello", encoding="utf-8")
    user_root = tmp_path / "user-skills"

    class FakeSkillManager:
        def register_new_skill(self, skill_dir_name):
            return skill_dir_name

    monkeypatch.setattr(skill_service, "_is_desktop_mode", lambda: True)
    monkeypatch.setattr(skill_service, "get_skill_manager", lambda: FakeSkillManager())
    monkeypatch.setattr(
        skill_service,
        "_desktop_user_skills_root",
        lambda user_id: str(user_root),
    )

    result = await skill_service.import_desktop_skills_by_paths([str(source)], "u_1")

    assert result["success_count"] == 1
    assert result["failed_count"] == 0
    target = user_root / "copied-skill"
    assert (target / "SKILL.md").is_file()
    assert (target / "guide.md").read_text(encoding="utf-8") == "hello"
