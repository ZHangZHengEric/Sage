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
import yaml
from fastapi import UploadFile
from loguru import logger
from sagents.skill.skill_manager import get_skill_manager

from .. import models
from ..core.exceptions import SageHTTPException


def _get_skill_info_safe(tm, skill_name: str):
    """Safely get skill info from manager"""
    for skill in tm.list_skill_info():
        if skill.name == skill_name:
            return skill
    return None


import stat

def _set_permissions_recursive(path, dir_mode=0o755, file_mode=0o644):
    """
    Recursively set permissions for a directory and its contents.
    Ensures that the directory and files are writable/readable by the owner.
    """
    try:
        if os.path.isdir(path):
            os.chmod(path, dir_mode)
            
        for root, dirs, files in os.walk(path):
            for d in dirs:
                os.chmod(os.path.join(root, d), dir_mode)
            for f in files:
                os.chmod(os.path.join(root, f), file_mode)
    except Exception as e:
        logger.warning(f"Failed to set permissions for {path}: {e}")


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
            name = skill.name
            skills.append({"name": skill.name, "description": skill.description, "user_id": ownership_map.get(name, "")})
    else:
        # Filter for user: System skills (no owner) + Own skills
        for skill in all_skills:
            name = skill.name

            owner = ownership_map.get(name, "")
            if not owner or owner == user_id:
                skills.append({"name": skill.name, "description": skill.description, "user_id": ownership_map.get(name, "")})
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

    skill_info = _get_skill_info_safe(tm, skill_name)
    if not skill_info:
        raise SageHTTPException(status_code=500, detail=f"Skill '{skill_name}' not found")

    dao = models.SkillOwnershipDao()
    owner = await dao.get_owner(skill_name)

    if role != "admin":
        if not owner:
            raise SageHTTPException(
                status_code=500, detail="Permission denied: Cannot delete system skill"
            )
        if owner != user_id:
            raise SageHTTPException(status_code=500, detail="Permission denied")

    try:
        # 1. Remove from SkillManager (Cache)
        tm.remove_skill(skill_name)
        
        # 2. Delete files
        skill_path = os.path.join(tm.skill_workspace, skill_name)
        if os.path.exists(skill_path):
            try:
                shutil.rmtree(skill_path)
            except (PermissionError, OSError) as e:
                logger.warning(f"Could not delete skill files for '{skill_name}' (possibly mounted): {e}")
                # Continue to delete ownership so it's removed from the app view

        # 3. Delete ownership (DB)
        await dao.delete_ownership(skill_name)

    except Exception as e:
        logger.error(f"Delete skill failed: {e}")
        raise SageHTTPException(status_code=500, detail=f"删除失败: {str(e)}")


async def get_skill_content(skill_name: str, user_id: str, role: str = "user") -> str:
    """获取技能内容 (SKILL.md)"""
    tm = get_skill_manager()
    if not tm:
        raise SageHTTPException(status_code=500, detail="技能管理器未初始化")

    # Check existence
    skill_info = _get_skill_info_safe(tm, skill_name)
    if not skill_info:
        raise SageHTTPException(status_code=500, detail=f"Skill '{skill_name}' not found")

    # Check permission
    dao = models.SkillOwnershipDao()
    owner = await dao.get_owner(skill_name)

    if role != "admin":
        # User can read system skills (owner=None) and own skills
        if owner and owner != user_id:
            raise SageHTTPException(status_code=500, detail="Permission denied")

    skill_path = os.path.join(tm.skill_workspace, skill_name, "SKILL.md")
    if not os.path.exists(skill_path):
        raise SageHTTPException(status_code=500, detail="SKILL.md not found")

    try:
        with open(skill_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Read skill content failed: {e}")
        raise SageHTTPException(status_code=500, detail=f"Failed to read skill content: {e}")


async def update_skill_content(skill_name: str, content: str, user_id: str, role: str = "user") -> str:
    """更新技能内容 (SKILL.md)"""
    tm = get_skill_manager()
    if not tm:
        raise SageHTTPException(status_code=500, detail="技能管理器未初始化")

    skill_info = _get_skill_info_safe(tm, skill_name)
    if not skill_info:
        raise SageHTTPException(status_code=500, detail=f"Skill '{skill_name}' not found")

    dao = models.SkillOwnershipDao()
    owner = await dao.get_owner(skill_name)

    if role != "admin":
        if not owner: # System skill
            raise SageHTTPException(status_code=500, detail="Cannot modify system skill")
        if owner != user_id:
            raise SageHTTPException(status_code=500, detail="Permission denied")

    skill_path = os.path.join(tm.skill_workspace, skill_name, "SKILL.md")

    # 0. Validate content format before saving
    try:
        metadata = {}
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                yaml_content = parts[1]
                metadata = yaml.safe_load(yaml_content) or {}
        
        name = metadata.get("name")
        description = metadata.get("description")
        
        if not name or not description:
             raise ValueError("Missing name or description in YAML frontmatter")

        if name != skill_name:
             raise ValueError(f"Skill name cannot be changed. Expected '{skill_name}', got '{name}'")

    except Exception as e:
        logger.warning(f"Skill validation failed before save: {e}")
        detail_msg = str(e) if "Skill name cannot be changed" in str(e) else "技能格式验证失败，请检查 SKILL.md 格式 (需包含 name 和 description)。"
        raise SageHTTPException(status_code=500, detail=detail_msg)

    # 1. Read original content for backup
    original_content = ""
    try:
        with open(skill_path, "r", encoding="utf-8") as f:
            original_content = f.read()
    except Exception as e:
        logger.error(f"Read original skill content failed: {e}")
        # If we can't read the original file, we probably shouldn't proceed with overwrite
        raise SageHTTPException(status_code=500, detail=f"Failed to read original skill content: {e}")

    try:
        # 2. Write new content
        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(content)

        # 3. Reload and validate skill
        if tm.register_new_skill(skill_name):
            return "技能更新成功"
        else:
            # Validation failed, trigger rollback
            raise ValueError("Skill validation failed")

    except Exception as e:
        logger.error(f"Update skill content failed: {e}")

        # 4. Rollback
        try:
            with open(skill_path, "w", encoding="utf-8") as f:
                f.write(original_content)
            # Re-register original to ensure consistency
            tm.register_new_skill(skill_name)
            logger.info(f"Rolled back skill '{skill_name}' to original state")
        except Exception as rollback_error:
            logger.error(f"Rollback failed for skill '{skill_name}': {rollback_error}")

        if isinstance(e, ValueError) and str(e) == "Skill validation failed":
            raise SageHTTPException(status_code=400, detail="技能格式验证失败，已还原修改。请检查 SKILL.md 格式。")

        raise SageHTTPException(status_code=500, detail=f"Failed to update skill content: {e}")


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

        # 确保文件权限正确，允许覆盖和删除
        _set_permissions_recursive(target_path, dir_mode=0o755, file_mode=0o644)

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
