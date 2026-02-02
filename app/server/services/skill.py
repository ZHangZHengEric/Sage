"""
Skill 业务处理模块

封装 Skill 相关的业务逻辑，供路由层调用。
"""

import os
import shutil
import tempfile
import zipfile
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import UploadFile
from loguru import logger
from sagents.skill.skill_manager import get_skill_manager

from .. import models
from ..core.exceptions import SageHTTPException


async def list_skills(user_id: str, role: str = "user") -> List[Dict[str, Any]]:
    """获取可用技能列表"""
    tm = get_skill_manager()
    if not tm:
        return []

    all_skills = list(tm.list_skill_info())

    # Get all ownerships to avoid N+1 queries
    dao = models.SkillOwnershipDao()
    all_ownerships = await dao.get_all_ownerships()
    ownership_map = {obj.skill_name: obj.user_id for obj in all_ownerships}

    skills = []
    if role == "admin":
        for skill in all_skills:
            name = skill.get("name")
            skill["user_id"] = ownership_map.get(name, "")
            skills.append(skill)
    else:
        # Filter for user: System skills (no owner) + Own skills
        for skill in all_skills:
            name = skill.get("name")
            owner = ownership_map.get(name, "")
            skill["user_id"] = owner
            if not owner or owner == user_id:
                skills.append(skill)
    return skills


async def import_skill_by_file(file: UploadFile, user_id: str) -> str:
    """通过上传 ZIP 文件导入技能"""
    if not file.filename.endswith('.zip'):
        raise SageHTTPException(status_code=500, detail="仅支持 ZIP 文件")

    tm = get_skill_manager()
    if not tm:
        raise SageHTTPException(status_code=500, detail="技能管理器未初始化")

    tmp_file_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
            shutil.copyfileobj(file.file, tmp_file)
            tmp_file_path = tmp_file.name

        success, message = await _process_zip_and_register(
            tm, tmp_file_path, file.filename, user_id
        )

        if not success:
            raise SageHTTPException(status_code=500, detail=message)

        return message

    except Exception as e:
        if isinstance(e, SageHTTPException):
            raise e
        logger.error(f"Upload skill failed: {e}")
        raise SageHTTPException(status_code=500, detail=f"导入失败: {str(e)}")
    finally:
        if tmp_file_path and os.path.exists(tmp_file_path):
            os.unlink(tmp_file_path)


async def import_skill_by_url(url: str, user_id: str) -> str:
    """通过 URL 导入技能"""
    tm = get_skill_manager()
    if not tm:
        raise SageHTTPException(status_code=500, detail="技能管理器未初始化")

    tmp_file_path = ""
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()

        filename = url.split("/")[-1]
        if not filename.endswith(".zip"):
            filename = "downloaded_skill.zip"

        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
            for chunk in response.iter_content(chunk_size=8192):
                tmp_file.write(chunk)
            tmp_file_path = tmp_file.name

        success, message = await _process_zip_and_register(
            tm, tmp_file_path, filename, user_id
        )

        if not success:
            raise SageHTTPException(status_code=500, detail=message)

        return message

    except Exception as e:
        if isinstance(e, SageHTTPException):
            raise e
        logger.error(f"Import skill from URL failed: {e}")
        raise SageHTTPException(status_code=500, detail=f"导入失败: {str(e)}")
    finally:
        if tmp_file_path and os.path.exists(tmp_file_path):
            os.unlink(tmp_file_path)


async def delete_skill(skill_name: str, user_id: str, role: str = "user") -> None:
    """删除技能"""
    tm = get_skill_manager()
    if not tm:
        raise SageHTTPException(status_code=500, detail="技能管理器未初始化")

    skill_info = tm.get_skill_info(skill_name)
    if not skill_info:
        raise SageHTTPException(status_code=500, detail=f"Skill '{skill_name}' not found")

    dao = models.SkillOwnershipDao()
    owner = await dao.get_owner(skill_name)

    if role != "admin":
        if not owner:
            raise SageHTTPException(
                status_code=403, detail="Permission denied: Cannot delete system skill"
            )
        if owner != user_id:
            raise SageHTTPException(status_code=500, detail="Permission denied")

    try:
        skill_path = os.path.join(tm.skill_workspace, skill_name)
        if os.path.exists(skill_path):
            shutil.rmtree(skill_path)

        await dao.delete_ownership(skill_name)

    except Exception as e:
        logger.error(f"Delete skill failed: {e}")
        raise SageHTTPException(status_code=500, detail=f"删除失败: {str(e)}")


async def _process_zip_and_register(
    tm, zip_path: str, original_filename: str, user_id: str
) -> Tuple[bool, str]:
    """
    解压 ZIP 并注册技能
    """
    temp_extract_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_extract_dir)

        # 寻找包含 SKILL.md 的目录
        skill_dir_name = None
        source_dir = None

        # 1. 检查根目录是否有 SKILL.md
        if os.path.exists(os.path.join(temp_extract_dir, "SKILL.md")):
            # 如果在根目录，使用压缩包文件名作为技能目录名
            skill_dir_name = os.path.splitext(original_filename)[0]
            source_dir = temp_extract_dir
        else:
            # 2. 检查一级子目录
            for item in os.listdir(temp_extract_dir):
                item_path = os.path.join(temp_extract_dir, item)
                if os.path.isdir(item_path) and os.path.exists(
                    os.path.join(item_path, "SKILL.md")
                ):
                    skill_dir_name = item
                    source_dir = item_path
                    break

        if not skill_dir_name or not source_dir:
            return False, "未找到有效的技能结构 (缺少 SKILL.md)"

        # 目标路径
        target_path = os.path.join(tm.skill_workspace, skill_dir_name)

        # 如果目标已存在，先删除 (或者报错? 这里选择覆盖)
        if os.path.exists(target_path):
            try:
                shutil.rmtree(target_path)
            except Exception as e:
                return False, f"无法覆盖已存在的技能目录: {e}"

        # 移动到技能工作区
        shutil.copytree(source_dir, target_path, dirs_exist_ok=True)

        # 验证并注册
        if tm.register_new_skill(skill_dir_name):
            # Save ownership
            dao = models.SkillOwnershipDao()
            await dao.set_owner(skill_dir_name, user_id)
            return True, f"技能 '{skill_dir_name}' 导入成功"
        else:
            return False, "技能验证失败，请检查 SKILL.md 格式"

    except zipfile.BadZipFile:
        return False, "无效的 ZIP 文件"
    except Exception as e:
        logger.error(f"Process zip failed: {e}")
        return False, f"处理技能文件失败: {str(e)}"
    finally:
        # 清理临时解压目录
        if os.path.exists(temp_extract_dir):
            shutil.rmtree(temp_extract_dir)
