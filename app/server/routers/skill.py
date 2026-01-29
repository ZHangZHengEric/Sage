"""
工具执行接口路由模块
"""

import os
import shutil
import zipfile
import tempfile
import requests
from typing import Any, Dict, Optional
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, Form, HTTPException
from pydantic import BaseModel
from sagents.skill.skill_manager import get_skill_manager
from sagents.utils.logger import logger

from ..core.render import Response

# 创建路由器
skill_router = APIRouter(prefix="/api/skills")


class UrlImportRequest(BaseModel):
    url: str


@skill_router.get("")
async def get_skills():
    """
    获取可用技能列表
    """
    skills = []
    tm = get_skill_manager()
    if tm:
        skills = list(tm.list_skill_info())

    return await Response.succ(message="获取技能列表成功", data={"skills": skills})


@skill_router.post("/upload")
async def upload_skill(file: UploadFile = File(...)):
    """
    通过上传 ZIP 文件导入技能
    """
    if not file.filename.endswith('.zip'):
        return await Response.error(message="仅支持 ZIP 文件")

    tm = get_skill_manager()
    if not tm:
        return await Response.error(message="技能管理器未初始化")

    try:
        # 创建临时文件保存上传的 zip
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
            shutil.copyfileobj(file.file, tmp_file)
            tmp_file_path = tmp_file.name

        success, message = _process_zip_and_register(tm, tmp_file_path, file.filename)
        
        # 清理临时文件
        os.unlink(tmp_file_path)

        if success:
            return await Response.succ(message=message)
        else:
            return await Response.error(message=message)

    except Exception as e:
        logger.error(f"Upload skill failed: {e}")
        return await Response.error(message=f"导入失败: {str(e)}")


@skill_router.post("/import-url")
async def import_skill_from_url(request: UrlImportRequest):
    """
    通过 URL 导入技能 (ZIP)
    """
    tm = get_skill_manager()
    if not tm:
        return await Response.error(message="技能管理器未初始化")

    url = request.url
    try:
        # 下载文件
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()

        # 获取文件名
        filename = url.split("/")[-1]
        if not filename.endswith(".zip"):
            filename = "downloaded_skill.zip"

        # 保存到临时文件
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
            for chunk in response.iter_content(chunk_size=8192):
                tmp_file.write(chunk)
            tmp_file_path = tmp_file.name

        success, message = _process_zip_and_register(tm, tmp_file_path, filename)
        
        # 清理临时文件
        os.unlink(tmp_file_path)

        if success:
            return await Response.succ(message=message)
        else:
            return await Response.error(message=message)

    except Exception as e:
        logger.error(f"Import skill from URL failed: {e}")
        return await Response.error(message=f"导入失败: {str(e)}")


def _process_zip_and_register(tm, zip_path: str, original_filename: str) -> (bool, str):
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
                if os.path.isdir(item_path) and os.path.exists(os.path.join(item_path, "SKILL.md")):
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
        # 注意：如果是根目录模式，temp_extract_dir 包含其他文件，我们只想要 SKILL.md 和相关文件
        # 这里简单起见，直接移动整个 source_dir
        shutil.copytree(source_dir, target_path, dirs_exist_ok=True)
        
        # 验证并注册
        if tm.register_new_skill(skill_dir_name):
            return True, f"技能 '{skill_dir_name}' 导入成功"
        else:
            # register_new_skill 会自动删除无效目录，但我们再次确认
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
