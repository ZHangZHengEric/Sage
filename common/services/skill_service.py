import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml
from fastapi import UploadFile
from loguru import logger
from sagents.skill.skill_manager import SkillManager, get_skill_manager

from common.core import config
from common.core.exceptions import SageHTTPException
from common.models.agent import AgentConfigDao


def _get_cfg() -> config.StartupConfig:
    cfg = config.get_startup_config()
    if not cfg:
        raise RuntimeError("Startup config not initialized")
    return cfg


def _is_desktop_mode() -> bool:
    return _get_cfg().app_mode == "desktop"


def _set_permissions_recursive(path: str, dir_mode: int = 0o755, file_mode: int = 0o644) -> None:
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


def _validate_skill_content(skill_name: str, content: str) -> None:
    try:
        metadata = {}
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                metadata = yaml.safe_load(parts[1]) or {}

        name = metadata.get("name")
        description = metadata.get("description")
        if not name or not description:
            raise ValueError("Missing name or description in YAML frontmatter")
        if name != skill_name:
            raise ValueError(
                f"Skill name cannot be changed. Expected '{skill_name}', got '{name}'"
            )
    except Exception as e:
        logger.warning(f"Skill validation failed before save: {e}")
        detail_msg = (
            str(e)
            if "Skill name cannot be changed" in str(e)
            else "技能格式验证失败，请检查 SKILL.md 格式 (需包含 name 和 description)。"
        )
        raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail=detail_msg)


def _extract_skill_from_zip(
    temp_extract_dir: str,
    original_filename: str,
) -> Tuple[Optional[str], Optional[str]]:
    if os.path.exists(os.path.join(temp_extract_dir, "SKILL.md")):
        return os.path.splitext(original_filename)[0], temp_extract_dir

    for item in os.listdir(temp_extract_dir):
        item_path = os.path.join(temp_extract_dir, item)
        if os.path.isdir(item_path) and os.path.exists(os.path.join(item_path, "SKILL.md")):
            return item, item_path
    return None, None


def _read_skill_name_from_md(skill_md_path: str) -> Optional[str]:
    if not os.path.exists(skill_md_path):
        return None
    try:
        with open(skill_md_path, "r", encoding="utf-8") as f:
            content = f.read()
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                metadata = yaml.safe_load(parts[1]) or {}
                return metadata.get("name")
    except Exception as e:
        logger.warning(f"Failed to read skill name from {skill_md_path}: {e}")
    return None


def _get_skill_info_safe(tm: Any, skill_name: str) -> Optional[Any]:
    for skill in tm.list_skill_info():
        if skill.name == skill_name:
            return skill
    return None


def _get_skill_dimension(skill_path: str) -> Dict[str, Any]:
    path = Path(skill_path)
    parts = path.parts

    if "agents" in parts:
        idx = parts.index("agents")
        if len(parts) > idx + 3 and parts[idx + 3] == "skills":
            return {
                "dimension": "agent",
                "owner_user_id": parts[idx + 1],
                "agent_id": parts[idx + 2],
            }

    if "users" in parts:
        idx = parts.index("users")
        if len(parts) > idx + 2 and parts[idx + 2] == "skills":
            return {
                "dimension": "user",
                "owner_user_id": parts[idx + 1],
                "agent_id": None,
            }

    if "skills" in parts:
        idx = parts.index("skills")
        if len(parts) == idx + 2:
            return {
                "dimension": "system",
                "owner_user_id": None,
                "agent_id": None,
            }

    return {"dimension": "system", "owner_user_id": None, "agent_id": None}


def _check_skill_permission(
    dimension_info: Dict[str, Any],
    user_id: str,
    role: str,
    action: str = "access",
) -> None:
    if role == "admin":
        return

    if dimension_info["dimension"] == "system":
        if action in ("delete", "modify"):
            raise SageHTTPException(
                detail=f"Permission denied: Cannot {action} system skill"
            )
    elif dimension_info["owner_user_id"] != user_id:
        raise SageHTTPException(detail="Permission denied")


def _sync_desktop_agent_skills() -> None:
    try:
        sage_home = Path.home() / ".sage"
        agents_dir = sage_home / "agents"
        sage_skills_dir = sage_home / "skills"
        if not agents_dir.exists():
            return

        sage_skills_dir.mkdir(parents=True, exist_ok=True)
        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            agent_skills_dir = agent_dir / "skills"
            if not agent_skills_dir.exists():
                continue
            for skill_path in agent_skills_dir.iterdir():
                if not skill_path.is_dir():
                    continue
                if not any(
                    f.name.lower() == "skill.md" for f in skill_path.iterdir() if f.is_file()
                ):
                    continue
                target_path = sage_skills_dir / skill_path.name
                if target_path.exists():
                    continue
                try:
                    shutil.copytree(skill_path, target_path)
                    logger.info(f"Synced agent skill: {skill_path.name} from {agent_dir.name}")
                except Exception as e:
                    logger.error(f"Failed to sync skill '{skill_path.name}': {e}")
    except Exception as e:
        logger.error(f"Error syncing agent skills: {e}")


def _collect_server_skills() -> List[Any]:
    cfg = _get_cfg()
    skill_dir = cfg.skill_dir
    user_dir = cfg.user_dir
    agents_dir = cfg.agents_dir
    all_skills: List[Any] = []

    if os.path.exists(skill_dir):
        try:
            all_skills.extend(list(SkillManager(skill_dirs=[skill_dir], isolated=True).list_skill_info()))
        except Exception as e:
            logger.warning(f"加载系统技能失败: {e}")

    if os.path.exists(user_dir):
        try:
            for user_folder in os.listdir(user_dir):
                user_skills_path = os.path.join(user_dir, user_folder, "skills")
                if os.path.isdir(user_skills_path):
                    try:
                        tm = SkillManager(skill_dirs=[user_skills_path], isolated=True)
                        all_skills.extend(list(tm.list_skill_info()))
                    except Exception as e:
                        logger.warning(f"加载用户 {user_folder} 技能失败: {e}")
        except Exception as e:
            logger.warning(f"扫描用户技能目录失败: {e}")

    if os.path.exists(agents_dir):
        try:
            for user_folder in os.listdir(agents_dir):
                user_agents_path = os.path.join(agents_dir, user_folder)
                if os.path.isdir(user_agents_path):
                    for agent_folder in os.listdir(user_agents_path):
                        agent_skills_path = os.path.join(
                            user_agents_path,
                            agent_folder,
                            "skills",
                        )
                        if os.path.isdir(agent_skills_path):
                            try:
                                tm = SkillManager(skill_dirs=[agent_skills_path], isolated=True)
                                all_skills.extend(list(tm.list_skill_info()))
                            except Exception as e:
                                logger.warning(
                                    f"加载 Agent {user_folder}/{agent_folder} 技能失败: {e}"
                                )
        except Exception as e:
            logger.warning(f"扫描Agent技能目录失败: {e}")

    return all_skills


def _find_server_skill_by_name(skill_name: str) -> Optional[Any]:
    for skill in _collect_server_skills():
        if skill.name == skill_name:
            return skill
    return None


async def list_skills(
    current_user_id: str = "",
    role: str = "user",
    filter_agent_id: Optional[str] = None,
    dimension: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if _is_desktop_mode():
        tm = get_skill_manager()
        if not tm:
            return []
        # Disabled temporarily: do not auto-sync agent workspace skills into ~/.sage/skills during desktop skill listing.
        # _sync_desktop_agent_skills()
        tm.reload()
        return [
            {"name": skill.name, "description": skill.description}
            for skill in list(tm.list_skill_info())
        ]

    all_skills = _collect_server_skills()
    allowed_skills = None
    if filter_agent_id:
        agent_dao = AgentConfigDao()
        agent = await agent_dao.get_by_id(filter_agent_id)
        if agent and agent.config:
            allowed_skills = agent.config.get("availableSkills") or agent.config.get("available_skills")

    agent_dao = AgentConfigDao()
    all_agents = await agent_dao.get_list()
    agent_name_map = {agent.agent_id: agent.name for agent in all_agents}

    skills: List[Dict[str, Any]] = []
    for skill in all_skills:
        name = skill.name
        if allowed_skills is not None and name not in allowed_skills:
            continue

        dimension_info = _get_skill_dimension(skill.path)
        skill_dimension = dimension_info["dimension"]
        if dimension and dimension != "all" and skill_dimension != dimension:
            continue

        if role != "admin" and skill_dimension in {"user", "agent"}:
            if dimension_info["owner_user_id"] != current_user_id:
                continue

        agent_id = dimension_info["agent_id"]
        skills.append(
            {
                "name": skill.name,
                "description": skill.description,
                "user_id": dimension_info["owner_user_id"] or "",
                "dimension": skill_dimension,
                "owner_user_id": dimension_info["owner_user_id"],
                "agent_id": agent_id,
                "agent_name": agent_name_map.get(agent_id, agent_id) if agent_id else None,
                "path": skill.path,
            }
        )
    return skills


async def list_skills_for_agent(agent_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    allowed_names = agent_config.get("availableSkills") or agent_config.get("available_skills") or []
    allowed_set = {str(name).strip() for name in allowed_names if str(name).strip()}
    if not allowed_set:
        return []

    all_skills = await list_skills()
    return [skill for skill in all_skills if skill.get("name") in allowed_set]


async def get_agent_available_skills(
    agent_id: str,
    current_user_id: str,
    role: str = "user",
) -> List[Dict[str, Any]]:
    if _is_desktop_mode():
        return []

    cfg = _get_cfg()
    skill_dir = cfg.skill_dir
    user_dir = cfg.user_dir
    agents_dir = cfg.agents_dir

    agent_dao = AgentConfigDao()
    agent = await agent_dao.get_by_id(agent_id)
    agent_user_id = agent.user_id if agent and agent.user_id else current_user_id

    skills_map: Dict[str, Dict[str, Any]] = {}

    if os.path.exists(skill_dir):
        try:
            tm = SkillManager(skill_dirs=[skill_dir], isolated=True)
            for skill in tm.list_skill_info():
                skills_map[skill.name] = {
                    "name": skill.name,
                    "description": skill.description,
                    "source_dimension": "system",
                }
        except Exception as e:
            logger.warning(f"加载系统技能失败: {e}")

    if os.path.exists(user_dir) and agent_user_id:
        user_skills_path = os.path.join(user_dir, agent_user_id, "skills")
        if os.path.isdir(user_skills_path):
            try:
                tm = SkillManager(skill_dirs=[user_skills_path], isolated=True)
                for skill in tm.list_skill_info():
                    skills_map[skill.name] = {
                        "name": skill.name,
                        "description": skill.description,
                        "source_dimension": "user",
                    }
            except Exception as e:
                logger.warning(f"加载用户技能失败: {e}")

    if os.path.exists(agents_dir) and agent_user_id and agent_id:
        agent_skills_path = os.path.join(agents_dir, agent_user_id, agent_id, "skills")
        if os.path.isdir(agent_skills_path):
            try:
                tm = SkillManager(skill_dirs=[agent_skills_path], isolated=True)
                for skill in tm.list_skill_info():
                    skills_map[skill.name] = {
                        "name": skill.name,
                        "description": skill.description,
                        "source_dimension": "agent",
                    }
            except Exception as e:
                logger.warning(f"加载Agent技能失败: {e}")

    skills_list = list(skills_map.values())
    skills_list.sort(key=lambda x: x["name"])
    return skills_list


async def delete_skill(
    skill_name: str,
    user_id: str = "",
    role: str = "user",
    agent_id: Optional[str] = None,
) -> None:
    if _is_desktop_mode():
        tm = get_skill_manager()
        if not tm:
            raise SageHTTPException(status_code=500, detail="技能管理器未初始化")
        skill_info = _get_skill_info_safe(tm, skill_name)
        if not skill_info:
            raise SageHTTPException(status_code=500, detail=f"Skill '{skill_name}' not found")
        try:
            tm.remove_skill(skill_name)
            skill_path = skill_info.path
            if os.path.exists(skill_path):
                try:
                    shutil.rmtree(skill_path)
                except (PermissionError, OSError) as e:
                    logger.warning(f"Could not delete skill files for '{skill_name}' (possibly mounted): {e}")
        except Exception as e:
            logger.error(f"Delete skill failed: {e}")
            raise SageHTTPException(status_code=500, detail=f"删除失败: {str(e)}")
        return

    cfg = _get_cfg()
    if agent_id:
        agent_skills_path = os.path.join(cfg.agents_dir, user_id, agent_id, "skills", skill_name)
        if not os.path.exists(agent_skills_path):
            raise SageHTTPException(detail=f"Skill '{skill_name}' not found in agent workspace")
        try:
            shutil.rmtree(agent_skills_path)
            return
        except (PermissionError, OSError) as e:
            raise SageHTTPException(detail=f"删除技能文件失败: {e}")

    if user_id:
        user_skills_path = os.path.join(cfg.user_dir, user_id, "skills", skill_name)
        if os.path.exists(user_skills_path):
            try:
                shutil.rmtree(user_skills_path)
                return
            except (PermissionError, OSError) as e:
                raise SageHTTPException(detail=f"删除技能文件失败: {e}")

    system_skills_path = os.path.join(cfg.skill_dir, skill_name)
    if os.path.exists(system_skills_path):
        if role != "admin":
            raise SageHTTPException(detail="无权删除系统技能", error_detail="forbidden")
        try:
            shutil.rmtree(system_skills_path)
            skill_manager = get_skill_manager()
            if skill_manager:
                skill_manager.reload()
            return
        except (PermissionError, OSError) as e:
            raise SageHTTPException(detail=f"删除技能文件失败: {e}")


async def get_skill_content(skill_name: str, user_id: str = "", role: str = "user") -> str:
    if _is_desktop_mode():
        tm = get_skill_manager()
        if not tm:
            raise SageHTTPException(status_code=500, detail="技能管理器未初始化")
        skill_info = _get_skill_info_safe(tm, skill_name)
        if not skill_info:
            raise SageHTTPException(status_code=500, detail=f"Skill '{skill_name}' not found")
    else:
        skill_info = _find_server_skill_by_name(skill_name)
        if not skill_info:
            raise SageHTTPException(detail=f"Skill '{skill_name}' not found")
        dimension_info = _get_skill_dimension(skill_info.path)
        _check_skill_permission(dimension_info, user_id, role, "access")

    skill_path = os.path.join(skill_info.path, "SKILL.md")
    if not os.path.exists(skill_path):
        raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail="SKILL.md not found")

    try:
        with open(skill_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail=f"Failed to read skill content: {e}")


async def update_skill_content(
    skill_name: str,
    content: str,
    user_id: str = "",
    role: str = "user",
) -> str:
    if _is_desktop_mode():
        tm = get_skill_manager()
        if not tm:
            raise SageHTTPException(status_code=500, detail="技能管理器未初始化")
        skill_info = _get_skill_info_safe(tm, skill_name)
        if not skill_info:
            raise SageHTTPException(status_code=500, detail=f"Skill '{skill_name}' not found")
    else:
        skill_info = _find_server_skill_by_name(skill_name)
        if not skill_info:
            raise SageHTTPException(detail=f"Skill '{skill_name}' not found")
        dimension_info = _get_skill_dimension(skill_info.path)
        _check_skill_permission(dimension_info, user_id, role, "modify")

    skill_path = os.path.join(skill_info.path, "SKILL.md")
    _validate_skill_content(skill_name, content)

    try:
        with open(skill_path, "r", encoding="utf-8") as f:
            original_content = f.read()
    except Exception as e:
        raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail=f"Failed to read original skill content: {e}")

    try:
        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(content)
        if _is_desktop_mode():
            if tm.reload_skill(skill_info.path):
                return "技能更新成功"
            raise ValueError("Skill validation failed")
        return "技能更新成功"
    except Exception as e:
        logger.error(f"Update skill content failed: {e}")
        try:
            with open(skill_path, "w", encoding="utf-8") as f:
                f.write(original_content)
            if _is_desktop_mode():
                tm.reload_skill(skill_info.path)
        except Exception as rollback_error:
            logger.error(f"Rollback failed for skill '{skill_name}': {rollback_error}")

        if isinstance(e, ValueError) and str(e) == "Skill validation failed":
            raise SageHTTPException(status_code=500, detail="技能格式验证失败，已还原修改。请检查 SKILL.md 格式。")
        raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail=f"Failed to update skill content: {e}")


async def _process_server_zip_to_dir(
    zip_path: str,
    original_filename: str,
    target_dir: str,
) -> Tuple[bool, str]:
    temp_extract_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
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
        _set_permissions_recursive(target_path)
        skill_name = _read_skill_name_from_md(os.path.join(target_path, "SKILL.md"))
        if skill_name:
            return True, f"技能 '{skill_name}' 导入成功"
        return False, "技能验证失败，请检查 SKILL.md 格式"
    except zipfile.BadZipFile:
        return False, "无效的 ZIP 文件"
    except Exception as e:
        logger.error(f"Process zip failed: {e}")
        return False, f"处理技能文件失败: {str(e)}"
    finally:
        if os.path.exists(temp_extract_dir):
            shutil.rmtree(temp_extract_dir)


async def _process_desktop_zip_and_register(tm: Any, zip_path: str, original_filename: str) -> Tuple[bool, str]:
    temp_extract_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(temp_extract_dir)

        skill_dir_name, source_dir = _extract_skill_from_zip(temp_extract_dir, original_filename)
        if not skill_dir_name or not source_dir:
            return False, "未找到有效的技能结构 (缺少 SKILL.md)"

        sage_skills_dir = Path.home() / ".sage" / "skills"
        sage_skills_dir.mkdir(parents=True, exist_ok=True)
        target_path = os.path.join(str(sage_skills_dir), skill_dir_name)
        if os.path.exists(target_path):
            try:
                shutil.rmtree(target_path)
            except Exception as e:
                return False, f"无法覆盖已存在的技能目录: {e}"

        shutil.copytree(source_dir, target_path, dirs_exist_ok=True)
        _set_permissions_recursive(target_path)
        registered_name = tm.register_new_skill(skill_dir_name)
        if registered_name:
            return True, f"技能 '{registered_name}' 导入成功"
        return False, "技能验证失败，请检查 SKILL.md 格式"
    except zipfile.BadZipFile:
        return False, "无效的 ZIP 文件"
    except Exception as e:
        logger.error(f"Process zip failed: {e}")
        return False, f"处理技能文件失败: {str(e)}"
    finally:
        if os.path.exists(temp_extract_dir):
            shutil.rmtree(temp_extract_dir)


async def import_skill_by_file(
    file: UploadFile,
    user_id: str = "",
    role: str = "user",
    is_system: bool = False,
    is_agent: bool = False,
    agent_id: Optional[str] = None,
) -> str:
    if not file.filename.endswith(".zip"):
        raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail="仅支持 ZIP 文件")

    if not _is_desktop_mode() and is_system and role != "admin":
        raise SageHTTPException(detail="权限不足：只有管理员可以导入系统技能")

    tmp_file_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
            shutil.copyfileobj(file.file, tmp_file)
            tmp_file_path = tmp_file.name

        if _is_desktop_mode():
            tm = get_skill_manager()
            if not tm:
                raise SageHTTPException(status_code=500, detail="技能管理器未初始化")
            success, message = await _process_desktop_zip_and_register(tm, tmp_file_path, file.filename)
        else:
            cfg = _get_cfg()
            if is_agent and agent_id:
                target_dir = os.path.join(cfg.agents_dir, user_id, agent_id, "skills")
                os.makedirs(target_dir, exist_ok=True)
            elif is_system:
                target_dir = cfg.skill_dir
            else:
                target_dir = os.path.join(cfg.user_dir, user_id, "skills")
                os.makedirs(target_dir, exist_ok=True)
            success, message = await _process_server_zip_to_dir(tmp_file_path, file.filename, target_dir)

        if not success:
            raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail=message)
        return message
    except Exception as e:
        if isinstance(e, SageHTTPException):
            raise
        raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail=f"导入失败: {str(e)}")
    finally:
        if tmp_file_path and os.path.exists(tmp_file_path):
            os.unlink(tmp_file_path)


async def import_skill_by_url(
    url: str,
    user_id: str = "",
    role: str = "user",
    is_system: bool = False,
    is_agent: bool = False,
    agent_id: Optional[str] = None,
) -> str:
    if not _is_desktop_mode() and is_system and role != "admin":
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

        if _is_desktop_mode():
            tm = get_skill_manager()
            if not tm:
                raise SageHTTPException(status_code=500, detail="技能管理器未初始化")
            success, message = await _process_desktop_zip_and_register(tm, tmp_file_path, filename)
        else:
            cfg = _get_cfg()
            if is_agent and agent_id:
                target_dir = os.path.join(cfg.agents_dir, user_id, agent_id, "skills")
                os.makedirs(target_dir, exist_ok=True)
            elif is_system:
                target_dir = cfg.skill_dir
            else:
                target_dir = os.path.join(cfg.user_dir, user_id, "skills")
                os.makedirs(target_dir, exist_ok=True)
            success, message = await _process_server_zip_to_dir(tmp_file_path, filename, target_dir)

        if not success:
            raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail=message)
        return message
    except Exception as e:
        if isinstance(e, SageHTTPException):
            raise
        raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail=f"导入失败: {str(e)}")
    finally:
        if tmp_file_path and os.path.exists(tmp_file_path):
            os.unlink(tmp_file_path)
