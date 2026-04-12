import os
import shutil
import tempfile
import zipfile
import hashlib
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


def _calculate_skill_hash(skill_path: str) -> str:
    """
    计算技能文件夹的哈希值，用于检测技能是否发生变化。

    计算所有文件的哈希值（排除隐藏文件和缓存文件），
    返回一个包含所有文件哈希的复合哈希值。
    """
    try:
        if not os.path.exists(skill_path):
            return ""

        # 收集所有文件及其哈希值
        file_hashes = {}
        for root, dirs, files in os.walk(skill_path):
            # 排除隐藏文件和缓存文件
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'node_modules']]

            for file in sorted(files):
                if file.startswith('.'):
                    continue

                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, skill_path)

                try:
                    with open(file_path, "rb") as f:
                        file_hash = hashlib.md5(f.read()).hexdigest()
                    file_hashes[rel_path] = file_hash
                except Exception as e:
                    logger.warning(f"计算文件哈希失败 {file_path}: {e}")

        # 按文件路径排序后生成复合哈希
        sorted_items = sorted(file_hashes.items())
        composite = "|".join([f"{path}:{hash}" for path, hash in sorted_items])
        return hashlib.md5(composite.encode("utf-8")).hexdigest()
    except Exception as e:
        logger.warning(f"计算技能哈希失败 {skill_path}: {e}")
        return ""


def _is_skill_need_update(source_skill_path: str, agent_skill_path: str) -> bool:
    """
    判断Agent工作空间的技能是否需要更新。

    对比广场技能的所有文件与Agent本地技能的对应文件：
    - 如果广场的文件在Agent本地不存在 → 需要更新
    - 如果广场的文件内容与Agent本地不同 → 需要更新
    - 如果Agent本地有多余的文件 → 不需要更新（忽略）

    Args:
        source_skill_path: 广场技能路径
        agent_skill_path: Agent本地技能路径

    Returns:
        bool: 是否需要更新
    """
    try:
        logger.info(f"对比技能: 广场={source_skill_path}, Agent={agent_skill_path}")

        # 获取广场技能的所有文件
        source_files = {}
        for root, dirs, files in os.walk(source_skill_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'node_modules']]

            for file in sorted(files):
                if file.startswith('.'):
                    continue

                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, source_skill_path)

                try:
                    with open(file_path, "rb") as f:
                        source_files[rel_path] = hashlib.md5(f.read()).hexdigest()
                except Exception as e:
                    logger.warning(f"读取广场技能文件失败 {file_path}: {e}")

        logger.info(f"广场技能文件: {list(source_files.keys())}")

        # 对比Agent本地技能的对应文件
        for rel_path, source_hash in source_files.items():
            agent_file_path = os.path.join(agent_skill_path, rel_path)

            # 如果Agent本地不存在该文件 → 需要更新
            if not os.path.exists(agent_file_path):
                logger.info(f"技能需要更新: Agent缺少文件 {rel_path}")
                return True

            # 如果Agent本地文件内容不同 → 需要更新
            try:
                with open(agent_file_path, "rb") as f:
                    agent_hash = hashlib.md5(f.read()).hexdigest()
                if agent_hash != source_hash:
                    logger.info(f"技能需要更新: 文件 {rel_path} 内容不同")
                    return True
            except Exception as e:
                logger.warning(f"读取Agent技能文件失败 {agent_file_path}: {e}")
                return True

        # 所有广场文件都存在且内容相同 → 不需要更新
        logger.info(f"技能不需要更新")
        return False
    except Exception as e:
        logger.warning(f"判断技能是否需要更新失败: {e}")
        return False


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
    """
    获取Agent可用的技能列表，包含是否需要更新状态。

    只检测技能广场（系统/用户技能）与Agent工作空间中技能的差异。
    如果Agent工作空间中的技能与广场不一致，则标记为需要更新。

    返回的技能列表中每个技能会包含以下字段：
    - name: 技能名称
    - description: 技能描述
    - source_dimension: 技能来源维度 (system, user)
    - need_update: 是否需要更新 (bool)
    - source_path: 源技能路径（用于更新）
    """
    cfg = _get_cfg()
    skill_dir = cfg.skill_dir
    user_dir = cfg.user_dir
    agents_dir = cfg.agents_dir

    agent_dao = AgentConfigDao()
    agent = await agent_dao.get_by_id(agent_id)
    agent_user_id = agent.user_id if agent and agent.user_id else current_user_id

    # 收集所有源技能（系统 + 用户）
    source_skills: Dict[str, Dict[str, Any]] = {}

    logger.info(f"技能广场路径: skill_dir={skill_dir}, user_dir={user_dir}")

    # 1. 加载系统技能
    if os.path.exists(skill_dir):
        try:
            tm = SkillManager(skill_dirs=[skill_dir], isolated=True)
            system_skills = list(tm.list_skill_info())
            logger.info(f"系统技能数量: {len(system_skills)}")
            for skill in system_skills:
                source_skills[skill.name] = {
                    "name": skill.name,
                    "description": skill.description,
                    "source_dimension": "system",
                    "path": skill.path,
                    "hash": _calculate_skill_hash(skill.path),
                }
        except Exception as e:
            logger.warning(f"加载系统技能失败: {e}")

    # 2. 加载用户技能（优先级高于系统技能，覆盖系统技能）
    if os.path.exists(user_dir) and agent_user_id:
        user_skills_path = os.path.join(user_dir, agent_user_id, "skills")
        logger.info(f"用户技能路径: {user_skills_path}, 存在={os.path.isdir(user_skills_path)}")
        if os.path.isdir(user_skills_path):
            try:
                tm = SkillManager(skill_dirs=[user_skills_path], isolated=True)
                user_skills = list(tm.list_skill_info())
                logger.info(f"用户技能数量: {len(user_skills)}")
                for skill in user_skills:
                    source_skills[skill.name] = {
                        "name": skill.name,
                        "description": skill.description,
                        "source_dimension": "user",
                        "path": skill.path,
                        "hash": _calculate_skill_hash(skill.path),
                    }
            except Exception as e:
                logger.warning(f"加载用户技能失败: {e}")
    else:
        logger.info(f"用户技能目录不存在或参数不全: user_dir存在={os.path.exists(user_dir) if user_dir else False}, agent_user_id={agent_user_id}")

    # 3. 加载Agent工作空间中的技能
    agent_skills: Dict[str, Dict[str, Any]] = {}
    logger.info(f"检查Agent工作空间: agents_dir={agents_dir}, agent_user_id={agent_user_id}, agent_id={agent_id}, app_mode={cfg.app_mode}")

    # 根据模式确定Agent技能路径
    if cfg.app_mode == "desktop":
        # Desktop模式: ~/.sage/agents/{agent_id}/skills
        agent_skills_path = os.path.join(agents_dir, agent_id, "skills")
    else:
        # Server模式: agents_dir/{user_id}/{agent_id}/skills
        if not agent_user_id:
            logger.info(f"Server模式需要agent_user_id")
        else:
            agent_skills_path = os.path.join(agents_dir, agent_user_id, agent_id, "skills")

    if agent_id and os.path.isdir(agent_skills_path):
        logger.info(f"Agent技能路径: {agent_skills_path}, 存在={os.path.isdir(agent_skills_path)}")
        try:
            tm = SkillManager(skill_dirs=[agent_skills_path], isolated=True)
            agent_skill_list = list(tm.list_skill_info())
            logger.info(f"Agent工作空间技能数量: {len(agent_skill_list)}")
            for skill in agent_skill_list:
                agent_skills[skill.name] = {
                    "name": skill.name,
                    "description": skill.description,
                    "path": skill.path,
                    "hash": _calculate_skill_hash(skill.path),
                }
        except Exception as e:
            logger.warning(f"加载Agent技能失败: {e}")
    else:
        logger.info(f"Agent工作空间不存在: {agent_skills_path if 'agent_skills_path' in locals() else '路径未确定'}")

    # 4. 合并技能列表，检测是否需要更新
    # 只返回广场中存在的技能，不显示孤立技能
    skills_list: List[Dict[str, Any]] = []

    logger.info(f"get_agent_available_skills: 广场技能={list(source_skills.keys())}, Agent技能={list(agent_skills.keys())}")

    for skill_name, source_skill in source_skills.items():
        skill_info = {
            "name": skill_name,
            "description": source_skill["description"],
            "source_dimension": source_skill["source_dimension"],
            "source_path": source_skill["path"],
        }

        # 检查Agent工作空间中是否存在该技能
        if skill_name in agent_skills:
            agent_skill = agent_skills[skill_name]
            logger.info(f"检查技能 '{skill_name}': 广场={source_skill['path']}, Agent={agent_skill['path']}")
            # 使用文件级对比判断是否需要更新
            # 广场文件不存在于Agent本地，或内容不同 → 需要更新
            # Agent本地有多余文件 → 忽略（不算需要更新）
            need_update = _is_skill_need_update(source_skill["path"], agent_skill["path"])
            skill_info["need_update"] = need_update
            skill_info["agent_path"] = agent_skill["path"]
            logger.info(f"技能 '{skill_name}' need_update={need_update}")
        else:
            # Agent工作空间中没有该技能，不需要显示更新状态
            # 对话时会自动同步
            skill_info["need_update"] = False
            logger.info(f"技能 '{skill_name}' 不在Agent工作空间中")

        skills_list.append(skill_info)

    skills_list.sort(key=lambda x: x["name"])
    return skills_list


async def sync_skill_to_agent(
    skill_name: str,
    agent_id: str,
    user_id: str = "",
    role: str = "user",
) -> Dict[str, Any]:
    """
    将技能同步到Agent工作空间。

    从技能广场（系统或用户技能）复制技能到Agent工作空间。
    如果Agent工作空间已存在该技能，则会覆盖更新。

    Args:
        skill_name: 技能名称
        agent_id: Agent ID
        user_id: 用户ID
        role: 用户角色

    Returns:
        Dict: 包含同步结果的信息
    """
    cfg = _get_cfg()
    skill_dir = cfg.skill_dir
    user_dir = cfg.user_dir
    agents_dir = cfg.agents_dir

    # 获取Agent信息
    agent_dao = AgentConfigDao()
    agent = await agent_dao.get_by_id(agent_id)
    if not agent:
        raise SageHTTPException(detail=f"Agent '{agent_id}' 不存在")

    agent_user_id = agent.user_id if agent.user_id else user_id

    # 检查权限
    if role != "admin" and agent_user_id != user_id:
        raise SageHTTPException(detail="无权同步技能到该Agent")

    # 1. 查找源技能（优先从用户技能，然后是系统技能）
    source_skill_path = None
    source_dimension = None

    # 先查找用户技能
    if os.path.exists(user_dir) and agent_user_id:
        user_skill_path = os.path.join(user_dir, agent_user_id, "skills", skill_name)
        if os.path.isdir(user_skill_path):
            source_skill_path = user_skill_path
            source_dimension = "user"

    # 再查找系统技能
    if source_skill_path is None and os.path.exists(skill_dir):
        system_skill_path = os.path.join(skill_dir, skill_name)
        if os.path.isdir(system_skill_path):
            source_skill_path = system_skill_path
            source_dimension = "system"

    if source_skill_path is None:
        raise SageHTTPException(detail=f"技能 '{skill_name}' 在技能广场中不存在")

    # 2. 确保Agent工作空间技能目录存在
    # 根据模式确定Agent技能路径
    if cfg.app_mode == "desktop":
        # Desktop模式: ~/.sage/agents/{agent_id}/skills
        agent_skills_dir = os.path.join(agents_dir, agent_id, "skills")
    else:
        # Server模式: agents_dir/{user_id}/{agent_id}/skills
        agent_skills_dir = os.path.join(agents_dir, agent_user_id, agent_id, "skills")
    os.makedirs(agent_skills_dir, exist_ok=True)

    # 3. 复制技能到Agent工作空间
    target_skill_path = os.path.join(agent_skills_dir, skill_name)

    try:
        # 如果已存在，先删除
        if os.path.exists(target_skill_path):
            shutil.rmtree(target_skill_path)

        # 复制技能文件夹
        shutil.copytree(source_skill_path, target_skill_path)
        _set_permissions_recursive(target_skill_path)

        logger.info(f"技能 '{skill_name}' 已同步到Agent '{agent_id}' 工作空间")

        return {
            "skill_name": skill_name,
            "agent_id": agent_id,
            "source_dimension": source_dimension,
            "source_path": source_skill_path,
            "target_path": target_skill_path,
            "sync_status": "synced",
        }
    except Exception as e:
        logger.error(f"同步技能失败: {e}")
        raise SageHTTPException(detail=f"同步技能失败: {str(e)}")


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
