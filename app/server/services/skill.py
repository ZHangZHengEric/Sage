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
from sagents.skill.skill_manager import get_skill_manager, SkillManager

from .. import models
from ..core.exceptions import SageHTTPException


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


from pathlib import Path

def _get_skill_dimension(skill_path: str):

    path = Path(skill_path)
    parts = path.parts

    # agents/{user_id}/{agent_id}/skills/{skill_name}
    if "agents" in parts:
        idx = parts.index("agents")
        if len(parts) > idx + 3 and parts[idx + 3] == "skills":
            return {
                "dimension": "agent",
                "owner_user_id": parts[idx + 1],
                "agent_id": parts[idx + 2]
            }

    # users/{user_id}/skills/{skill_name}
    if "users" in parts:
        idx = parts.index("users")
        if len(parts) > idx + 2 and parts[idx + 2] == "skills":
            return {
                "dimension": "user",
                "owner_user_id": parts[idx + 1],
                "agent_id": None
            }

    # skills/{skill_name}
    if "skills" in parts:
        idx = parts.index("skills")
        if len(parts) == idx + 2:
            return {
                "dimension": "system",
                "owner_user_id": None,
                "agent_id": None
            }

    return {
        "dimension": "system",
        "owner_user_id": None,
        "agent_id": None
    }


def _collect_all_skills() -> List[Any]:
    """
    收集所有技能（系统、用户、Agent）

    Returns:
        所有技能的列表
    """
    from ..core.config import get_startup_config

    cfg = get_startup_config()
    skill_dir = cfg.skill_dir if cfg else "skills"
    user_dir = cfg.user_dir if cfg else "users"
    agents_dir = cfg.agents_dir if cfg else "agents"

    all_skills = []

    # 1. 系统技能
    if os.path.exists(skill_dir):
        try:
            tm = SkillManager(skill_dirs=[skill_dir], isolated=True, include_global_skills=False)
            all_skills.extend(list(tm.list_skill_info()))
        except Exception as e:
            logger.warning(f"加载系统技能失败: {e}")

    # 2. 用户技能
    if os.path.exists(user_dir):
        try:
            for user_folder in os.listdir(user_dir):
                user_skills_path = os.path.join(user_dir, user_folder, "skills")
                if os.path.isdir(user_skills_path):
                    try:
                        tm = SkillManager(skill_dirs=[user_skills_path], isolated=True, include_global_skills=False)
                        all_skills.extend(list(tm.list_skill_info()))
                    except Exception as e:
                        logger.warning(f"加载用户 {user_folder} 技能失败: {e}")
        except Exception as e:
            logger.warning(f"扫描用户技能目录失败: {e}")

    # 3. Agent 技能
    if os.path.exists(agents_dir):
        try:
            for user_folder in os.listdir(agents_dir):
                user_agents_path = os.path.join(agents_dir, user_folder)
                if os.path.isdir(user_agents_path):
                    for agent_folder in os.listdir(user_agents_path):
                        agent_skills_path = os.path.join(user_agents_path, agent_folder, "skills")
                        if os.path.isdir(agent_skills_path):
                            try:
                                tm = SkillManager(skill_dirs=[agent_skills_path], isolated=True, include_global_skills=False)
                                all_skills.extend(list(tm.list_skill_info()))
                            except Exception as e:
                                logger.warning(f"加载 Agent {user_folder}/{agent_folder} 技能失败: {e}")
        except Exception as e:
            logger.warning(f"扫描Agent技能目录失败: {e}")

    return all_skills


def _find_skill_by_name(skill_name: str) -> Optional[Any]:
    """
    从所有技能中根据名称查找技能

    Args:
        skill_name: 技能名称

    Returns:
        技能信息对象，未找到返回 None
    """
    all_skills = _collect_all_skills()
    for skill in all_skills:
        if skill.name == skill_name:
            return skill
    return None


def _check_skill_permission(
    dimension_info: Dict[str, Any],
    user_id: str,
    role: str,
    action: str = "access"
) -> None:
    """
    检查技能权限

    Args:
        dimension_info: 技能维度信息
        user_id: 当前用户ID
        role: 用户角色
        action: 操作类型 ("access", "delete", "modify")

    Raises:
        SageHTTPException: 权限不足时抛出
    """
    if role == "admin":
        return

    if dimension_info["dimension"] == "system":
        if action in ("delete", "modify"):
            raise SageHTTPException(
                status_code=500,
                detail=f"Permission denied: Cannot {action} system skill"
            )
    elif dimension_info["owner_user_id"] != user_id:
        raise SageHTTPException(detail="Permission denied")


async def list_skills(current_user_id: str, role: str = "user", filter_agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    获取可用技能列表

    Args:
        current_user_id: 当前用户ID
        role: 用户角色
        filter_agent_id: 可选，过滤特定Agent的技能
    """
    all_skills = _collect_all_skills()

    allowed_skills = None
    if filter_agent_id:
        agent_dao = models.AgentConfigDao()
        agent = await agent_dao.get_by_id(filter_agent_id)
        if agent and agent.config:
            allowed_skills = agent.config.get("availableSkills") or agent.config.get("available_skills")

    skills = []
    for skill in all_skills:
        name = skill.name

        if allowed_skills is not None and name not in allowed_skills:
            continue

        dimension_info = _get_skill_dimension(skill.path)

        if role != "admin":
            if dimension_info["dimension"] == "user":
                if dimension_info["owner_user_id"] != current_user_id:
                    continue
            elif dimension_info["dimension"] == "agent":
                if dimension_info["owner_user_id"] != current_user_id:
                    continue

        skills.append({
            "name": skill.name,
            "description": skill.description,
            "user_id": dimension_info["owner_user_id"] or "",
            "dimension": dimension_info["dimension"],
            "owner_user_id": dimension_info["owner_user_id"],
            "agent_id": dimension_info["agent_id"],
            "path": skill.path
        })
    return skills


async def delete_skill(skill_name: str, user_id: str, role: str = "user") -> None:
    """删除技能"""
    skill_info = _find_skill_by_name(skill_name)
    if not skill_info:
        raise SageHTTPException(detail=f"Skill '{skill_name}' not found")

    dimension_info = _get_skill_dimension(skill_info.path)
    _check_skill_permission(dimension_info, user_id, role, "delete")

    try:
        skill_path = skill_info.path
        if os.path.exists(skill_path):
            try:
                shutil.rmtree(skill_path)
            except (PermissionError, OSError) as e:
                logger.warning(f"Could not delete skill files for '{skill_name}': {e}")
                raise SageHTTPException(detail=f"删除技能文件失败: {e}")

    except Exception as e:
        logger.error(f"Delete skill failed: {e}")
        raise SageHTTPException(detail=f"删除失败: {str(e)}")


async def get_skill_content(skill_name: str, user_id: str, role: str = "user") -> str:
    """获取技能内容 (SKILL.md)"""
    skill_info = _find_skill_by_name(skill_name)
    if not skill_info:
        raise SageHTTPException(detail=f"Skill '{skill_name}' not found")

    dimension_info = _get_skill_dimension(skill_info.path)
    _check_skill_permission(dimension_info, user_id, role, "access")

    skill_path = os.path.join(skill_info.path, "SKILL.md")
    if not os.path.exists(skill_path):
        raise SageHTTPException(detail="SKILL.md not found")

    try:
        with open(skill_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Read skill content failed: {e}")
        raise SageHTTPException(detail=f"Failed to read skill content: {e}")


async def update_skill_content(skill_name: str, content: str, user_id: str, role: str = "user") -> str:
    """更新技能内容 (SKILL.md)"""
    skill_info = _find_skill_by_name(skill_name)
    if not skill_info:
        raise SageHTTPException(detail=f"Skill '{skill_name}' not found")

    dimension_info = _get_skill_dimension(skill_info.path)
    _check_skill_permission(dimension_info, user_id, role, "modify")

    skill_path = os.path.join(skill_info.path, "SKILL.md")

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
        raise SageHTTPException(detail=detail_msg)

    original_content = ""
    try:
        with open(skill_path, "r", encoding="utf-8") as f:
            original_content = f.read()
    except Exception as e:
        logger.error(f"Read original skill content failed: {e}")
        raise SageHTTPException(detail=f"Failed to read original skill content: {e}")

    try:
        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(content)
        return "技能更新成功"
    except Exception as e:
        logger.error(f"Update skill content failed: {e}")

        try:
            with open(skill_path, "w", encoding="utf-8") as f:
                f.write(original_content)
            logger.info(f"Rolled back skill '{skill_name}' to original state")
        except Exception as rollback_error:
            logger.error(f"Rollback failed for skill '{skill_name}': {rollback_error}")

        raise SageHTTPException(detail=f"Failed to update skill content: {e}")


def _extract_skill_from_zip(temp_extract_dir: str, original_filename: str) -> Tuple[Optional[str], Optional[str]]:
    """
    从解压目录中提取技能目录名称和源目录

    Returns:
        (skill_dir_name, source_dir)
    """
    if os.path.exists(os.path.join(temp_extract_dir, "SKILL.md")):
        skill_dir_name = os.path.splitext(original_filename)[0]
        return skill_dir_name, temp_extract_dir
    else:
        for item in os.listdir(temp_extract_dir):
            item_path = os.path.join(temp_extract_dir, item)
            if os.path.isdir(item_path) and os.path.exists(os.path.join(item_path, "SKILL.md")):
                return item, item_path
    return None, None


def _read_skill_name_from_md(skill_md_path: str) -> Optional[str]:
    """从 SKILL.md 中读取技能名称"""
    if not os.path.exists(skill_md_path):
        return None
    try:
        with open(skill_md_path, 'r', encoding='utf-8') as f:
            content = f.read()
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                metadata = yaml.safe_load(parts[1]) or {}
                return metadata.get("name")
    except Exception as e:
        logger.warning(f"Failed to read skill name from {skill_md_path}: {e}")
    return None


async def _process_zip_to_dir(
    zip_path: str,
    original_filename: str,
    target_dir: str
) -> Tuple[bool, str]:
    """
    通用的 ZIP 处理函数，解压到指定目录

    Args:
        zip_path: ZIP 文件路径
        original_filename: 原始文件名
        target_dir: 目标目录

    Returns:
        (success, message)
    """
    temp_extract_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_extract_dir)

        skill_dir_name, source_dir = _extract_skill_from_zip(temp_extract_dir, original_filename)
        if not skill_dir_name or not source_dir:
            return False, "未找到有效的技能结构 (缺少 SKILL.md)"

        target_path = os.path.join(target_dir, skill_dir_name)

        if os.path.exists(target_path):
            try:
                shutil.rmtree(target_path)
            except Exception as e:
                return False, f"无法覆盖已存在的技能目录: {e}"

        shutil.copytree(source_dir, target_path, dirs_exist_ok=True)
        _set_permissions_recursive(target_path, dir_mode=0o755, file_mode=0o644)

        skill_name = _read_skill_name_from_md(os.path.join(target_path, "SKILL.md"))
        if skill_name:
            return True, f"技能 '{skill_name}' 导入成功"
        else:
            return False, "技能验证失败，请检查 SKILL.md 格式"

    except zipfile.BadZipFile:
        return False, "无效的 ZIP 文件"
    except Exception as e:
        logger.error(f"Process zip failed: {e}")
        return False, f"处理技能文件失败: {str(e)}"
    finally:
        if os.path.exists(temp_extract_dir):
            shutil.rmtree(temp_extract_dir)


def _get_skill_target_path(skill_dir_name: str, user_id: str) -> str:
    """
    根据 user_id 获取技能的目标存储路径
    - 系统技能 (user_id 为空): skills/{skill_name}
    - 用户技能: users/{user_id}/skills/{skill_name}
    """
    from ..core.config import get_startup_config
    cfg = get_startup_config()
    skill_dir = cfg.skill_dir if cfg else "skills"
    user_dir = cfg.user_dir if cfg else "users"

    if user_id:
        target_dir = os.path.join(user_dir, user_id, "skills")
    else:
        target_dir = skill_dir

    os.makedirs(target_dir, exist_ok=True)
    return os.path.join(target_dir, skill_dir_name)


async def import_skill_by_file(
    file: UploadFile,
    user_id: str,
    role: str = "user",
    is_system: bool = False,
    is_agent: bool = False,
    agent_id: Optional[str] = None) -> str:
    """通过上传 ZIP 文件导入技能"""
    from ..core.config import get_startup_config
    cfg = get_startup_config()

    if is_system and role != "admin":
        raise SageHTTPException(detail="权限不足：只有管理员可以导入系统技能")

    if not file.filename.endswith('.zip'):
        raise SageHTTPException(detail="仅支持 ZIP 文件")

    tmp_file_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
            shutil.copyfileobj(file.file, tmp_file)
            tmp_file_path = tmp_file.name

        if is_agent and agent_id:
            agents_dir = cfg.agents_dir if cfg else "agents"
            target_dir = os.path.join(agents_dir, user_id, agent_id, "skills")
            os.makedirs(target_dir, exist_ok=True)

            success, message = await _process_zip_to_dir(
                tmp_file_path, file.filename, target_dir
            )
            if not success:
                raise SageHTTPException(detail=message)
            return message

        if is_system:
            success, message = await _process_zip_to_dir(
                tmp_file_path, file.filename, cfg.skill_dir
            )
        else:
            target_dir = os.path.join(cfg.user_dir, user_id, "skills")
            os.makedirs(target_dir, exist_ok=True)
            success, message = await _process_zip_to_dir(
                tmp_file_path, file.filename, target_dir
            )

        if not success:
            raise SageHTTPException(detail=message)

        return message

    except Exception as e:
        if isinstance(e, SageHTTPException):
            raise e
        logger.error(f"Upload skill failed: {e}")
        raise SageHTTPException(detail=f"导入失败: {str(e)}")
    finally:
        if tmp_file_path and os.path.exists(tmp_file_path):
            os.unlink(tmp_file_path)


async def import_skill_by_url(
    url: str,
    user_id: str,
    role: str = "user",
    is_system: bool = False,
    is_agent: bool = False,
    agent_id: Optional[str] = None) -> str:
    """通过 URL 导入技能"""
    from ..core.config import get_startup_config
    cfg = get_startup_config()

    if is_system and role != "admin":
        raise SageHTTPException(detail="权限不足：只有管理员可以导入系统技能")

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

        if is_agent and agent_id:
            agents_dir = cfg.agents_dir if cfg else "agents"
            target_dir = os.path.join(agents_dir, user_id, agent_id, "skills")
            os.makedirs(target_dir, exist_ok=True)

            success, message = await _process_zip_to_dir(
                tmp_file_path, filename, target_dir
            )
            if not success:
                raise SageHTTPException(detail=message)
            return message

        if is_system:
            success, message = await _process_zip_to_dir(
                tmp_file_path, filename, cfg.skill_dir
            )
        else:
            target_dir = os.path.join(cfg.user_dir, user_id, "skills")
            os.makedirs(target_dir, exist_ok=True)
            success, message = await _process_zip_to_dir(
                tmp_file_path, filename, target_dir
            )

        if not success:
            raise SageHTTPException(detail=message)

        return message

    except Exception as e:
        if isinstance(e, SageHTTPException):
            raise e
        logger.error(f"Import skill from URL failed: {e}")
        raise SageHTTPException(detail=f"导入失败: {str(e)}")
    finally:
        if tmp_file_path and os.path.exists(tmp_file_path):
            os.unlink(tmp_file_path)
