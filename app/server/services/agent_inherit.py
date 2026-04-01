import shutil
from pathlib import Path

from loguru import logger


def get_agent_inherit_dir(agent_id: str) -> Path:
    """返回 agent 默认继承目录 ./inherit/<agent_id>"""
    return (Path(".") / "inherit" / agent_id).resolve()


def ensure_agent_inherit_dir(agent_id: str) -> Path:
    """在创建 agent 时初始化对应的继承目录"""
    inherit_dir = get_agent_inherit_dir(agent_id)
    inherit_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Agent inherit 目录已就绪: {inherit_dir}")
    return inherit_dir


def copy_agent_inherit_to_workspace(agent_id: str, agent_workspace: str) -> None:
    """将 ./inherit/<agent_id> 下的内容复制到 agent workspace 根目录。"""
    inherit_dir = get_agent_inherit_dir(agent_id)
    if not inherit_dir.is_dir():
        logger.debug(f"Agent inherit 目录不存在，跳过初始化复制: {inherit_dir}")
        return

    workspace_path = Path(agent_workspace)
    _copy_directory_contents(inherit_dir, workspace_path)
    logger.info(f"已从 inherit 初始化 agent workspace: {inherit_dir} -> {workspace_path}")


def _copy_directory_contents(source_dir: Path, target_dir: Path) -> None:
    """复制目录内容，但不额外包一层源目录名"""
    for item in source_dir.iterdir():
        target_path = target_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target_path, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target_path)
