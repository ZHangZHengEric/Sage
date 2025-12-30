"""
文件服务器路由模块
提供静态文件访问和下载功能，支持workspace和logs-dir目录
"""

import json
import mimetypes
import os
from pathlib import Path

from core import config
from core.exceptions import SageHTTPException
from core.render import Response
from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, HTMLResponse

from sagents.utils.logger import logger

# 创建路由器
file_server_router = APIRouter()

# 文件预览模板
PREVIEW_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>文件预览 - {filename}</title>
    <meta charset="utf-8">
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f8f9fa; }}
        .header {{ background: #fff; padding: 15px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .content {{ background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .file-info {{ margin-bottom: 15px; padding: 10px; background: #e9ecef; border-radius: 5px; }}
        .actions {{ margin-bottom: 15px; }}
        .btn {{ display: inline-block; padding: 8px 16px; margin-right: 10px; background: #007bff; color: white; text-decoration: none; border-radius: 4px; }}
        .btn:hover {{ background: #0056b3; }}
        .btn-secondary {{ background: #6c757d; }}
        .btn-secondary:hover {{ background: #545b62; }}
        pre {{ background: #f8f9fa; padding: 15px; border-radius: 5px; overflow-x: auto; white-space: pre-wrap; word-wrap: break-word; max-height: 600px; overflow-y: auto; }}
        .json-viewer {{ font-family: 'Courier New', monospace; }}
        .log-viewer {{ font-family: 'Courier New', monospace; line-height: 1.4; }}
        .line-numbers {{ color: #666; margin-right: 10px; user-select: none; }}
        .error {{ color: #dc3545; background: #f8d7da; padding: 10px; border-radius: 5px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>文件预览</h1>
        <div class="file-info">
            <strong>文件名:</strong> {filename}<br>
            <strong>文件大小:</strong> {file_size}<br>
            <strong>文件类型:</strong> {file_type}
        </div>
        <div class="actions">
            <a href="{download_url}" class="btn">下载文件</a>
            <a href="{back_url}" class="btn btn-secondary">返回目录</a>
        </div>
    </div>
    
    <div class="content">
        {content}
    </div>
</body>
</html>
"""

# 简单的HTML模板，用于目录浏览
DIRECTORY_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>文件浏览器 - {path}</title>
    <meta charset="utf-8">
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .header {{ background: #f5f5f5; padding: 10px; border-radius: 5px; margin-bottom: 20px; }}
        .breadcrumb {{ margin-bottom: 10px; }}
        .breadcrumb a {{ text-decoration: none; color: #007bff; }}
        .breadcrumb a:hover {{ text-decoration: underline; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #f8f9fa; }}
        .file-icon {{ width: 16px; margin-right: 8px; }}
        .directory {{ color: #007bff; }}
        .file {{ color: #333; }}
        .size {{ text-align: right; }}
        .date {{ color: #666; }}
        a {{ text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>文件浏览器</h1>
        <div class="breadcrumb">
            <strong>当前路径:</strong> {breadcrumb}
        </div>
    </div>
    
    <table>
        <thead>
            <tr>
                <th>名称</th>
                <th>大小</th>
                <th>修改时间</th>
                <th>操作</th>
            </tr>
        </thead>
        <tbody>
            {parent_link}
            {file_list}
        </tbody>
    </table>
</body>
</html>
"""


def get_workspace_path():
    """获取工作空间路径"""

    return config.get_startup_config().workspace


def get_logs_path():
    """获取日志目录路径"""

    return config.get_startup_config().logs_dir


def format_file_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes == 0:
        return "0 B"
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.1f} {size_names[i]}"


def is_safe_path(base_path: str, requested_path: str) -> bool:
    """检查请求的路径是否在基础路径范围内"""
    try:
        base_path = os.path.abspath(base_path)
        requested_path = os.path.abspath(requested_path)
        return requested_path.startswith(base_path)
    except Exception:
        return False


def is_previewable_file(file_path: str) -> bool:
    """检查文件是否支持预览"""
    if not os.path.isfile(file_path):
        return False

    # 获取文件扩展名
    _, ext = os.path.splitext(file_path.lower())

    # 支持预览的文件类型
    previewable_extensions = {
        ".log",
        ".json",
        ".txt",
        ".md",
        ".py",
        ".js",
        ".html",
        ".css",
        ".xml",
        ".yaml",
        ".yml",
    }

    return ext in previewable_extensions


def get_file_content_for_preview(
    file_path: str, max_size: int = 1024 * 1024
) -> tuple[str, str]:
    """获取文件内容用于预览

    Args:
        file_path: 文件路径
        max_size: 最大文件大小（字节），默认1MB

    Returns:
        tuple: (content, file_type)
    """
    try:
        # 检查文件大小
        file_size = os.path.getsize(file_path)
        if file_size > max_size:
            return (
                f"文件太大无法预览 (大小: {format_file_size(file_size)}, 限制: {format_file_size(max_size)})",
                "error",
            )

        # 获取文件扩展名
        _, ext = os.path.splitext(file_path.lower())

        # 读取文件内容
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # 根据文件类型处理内容
        if ext == ".json":
            try:
                # 尝试格式化JSON
                parsed_json = json.loads(content)
                formatted_content = json.dumps(
                    parsed_json, indent=2, ensure_ascii=False
                )
                return f'<pre class="json-viewer">{formatted_content}</pre>', "json"
            except json.JSONDecodeError as e:
                return (
                    f'<div class="error">JSON格式错误: {str(e)}</div><pre class="json-viewer">{content}</pre>',
                    "json",
                )

        elif ext == ".log":
            # 对于日志文件，添加行号
            lines = content.split("\n")
            if len(lines) > 1000:  # 限制显示行数
                lines = lines[-1000:]  # 只显示最后1000行
                content_with_lines = "... (只显示最后1000行) ...\n\n"
            else:
                content_with_lines = ""

            for i, line in enumerate(lines, 1):
                content_with_lines += (
                    f'<span class="line-numbers">{i:4d}:</span> {line}\n'
                )

            return f'<pre class="log-viewer">{content_with_lines}</pre>', "log"

        else:
            # 其他文本文件
            return f"<pre>{content}</pre>", "text"

    except UnicodeDecodeError:
        return '<div class="error">文件编码不支持，无法预览文本内容</div>', "error"
    except Exception as e:
        return f'<div class="error">读取文件时出错: {str(e)}</div>', "error"


def get_directory_listing(
    directory_path: str, base_url: str, relative_path: str = ""
) -> str:
    """生成目录列表的HTML"""
    try:
        items = []

        # 添加返回上级目录的链接（如果不是根目录）
        parent_link = ""
        if relative_path:
            parent_path = (
                "/".join(relative_path.split("/")[:-1]) if "/" in relative_path else ""
            )
            parent_url = f"{base_url}?path={parent_path}" if parent_path else base_url
            parent_link = f'<tr><td colspan="4"><a href="{parent_url}">📁 .. (返回上级目录)</a></td></tr>'

        # 获取目录内容
        for item_name in sorted(os.listdir(directory_path)):
            if item_name.startswith("."):  # 跳过隐藏文件
                continue

            item_path = os.path.join(directory_path, item_name)
            item_relative_path = (
                f"{relative_path}/{item_name}" if relative_path else item_name
            )

            try:
                stat = os.stat(item_path)
                os.path.getmtime(item_path)
                mod_time_str = Path(item_path).stat().st_mtime
                import datetime

                mod_time_formatted = datetime.datetime.fromtimestamp(
                    mod_time_str
                ).strftime("%Y-%m-%d %H:%M:%S")

                if os.path.isdir(item_path):
                    # 目录
                    browse_url = f"{base_url}?path={item_relative_path}"
                    items.append(
                        f"""
                        <tr>
                            <td><a href="{browse_url}" class="directory">📁 {item_name}</a></td>
                            <td class="size">-</td>
                            <td class="date">{mod_time_formatted}</td>
                            <td><a href="{browse_url}">浏览</a></td>
                        </tr>
                    """
                    )
                else:
                    # 文件
                    download_url = f"{base_url}/download?path={item_relative_path}"
                    file_size = format_file_size(stat.st_size)

                    # 检查是否支持预览
                    actions = []
                    if is_previewable_file(item_path):
                        preview_url = f"{base_url}/preview?path={item_relative_path}"
                        actions.append(f'<a href="{preview_url}">预览</a>')
                    actions.append(f'<a href="{download_url}">下载</a>')

                    items.append(
                        f"""
                        <tr>
                            <td><span class="file">📄 {item_name}</span></td>
                            <td class="size">{file_size}</td>
                            <td class="date">{mod_time_formatted}</td>
                            <td>{" | ".join(actions)}</td>
                        </tr>
                    """
                    )
            except Exception as e:
                logger.warning(f"无法获取文件信息: {item_path}, 错误: {e}")
                continue

        # 生成面包屑导航
        breadcrumb_parts = []
        if relative_path:
            path_parts = relative_path.split("/")
            current_path = ""
            for part in path_parts:
                current_path = f"{current_path}/{part}" if current_path else part
                part_url = f"{base_url}?path={current_path}"
                breadcrumb_parts.append(f'<a href="{part_url}">{part}</a>')

        breadcrumb = " / ".join([f'<a href="{base_url}">根目录</a>'] + breadcrumb_parts)

        return DIRECTORY_TEMPLATE.format(
            path=relative_path or "根目录",
            breadcrumb=breadcrumb,
            parent_link=parent_link,
            file_list="".join(items),
        )
    except Exception as e:
        logger.error(f"生成目录列表失败: {e}")
        raise SageHTTPException(
            status_code=500, detail="生成目录列表失败", error_detail=str(e)
        )


@file_server_router.get("/api/files/workspace")
async def browse_workspace(
    request: Request, path: str = Query("", description="相对路径")
):
    """浏览workspace目录"""
    workspace_path = get_workspace_path()
    if not workspace_path or not os.path.exists(workspace_path):
        raise SageHTTPException(
            status_code=404,
            detail="工作空间目录不存在",
            error_detail=f"Workspace directory not found: {workspace_path}",
        )

    # 构建完整路径
    if path:
        full_path = os.path.join(workspace_path, path.lstrip("/"))
    else:
        full_path = workspace_path

    # 安全检查
    if not is_safe_path(workspace_path, full_path):
        raise SageHTTPException(
            status_code=403,
            detail="访问被拒绝：路径超出工作空间范围",
            error_detail="Access denied: path outside workspace",
        )

    # 检查路径是否存在
    if not os.path.exists(full_path):
        raise SageHTTPException(
            status_code=404,
            detail=f"路径不存在: {path}",
            error_detail=f"Path not found: {path}",
        )

    # 如果是文件，直接返回文件内容
    if os.path.isfile(full_path):
        return FileResponse(path=full_path, filename=os.path.basename(full_path))

    # 如果是目录，返回目录列表
    base_url = "/api/files/workspace"
    html_content = get_directory_listing(full_path, base_url, path)
    return HTMLResponse(content=html_content)


@file_server_router.get("/api/files/workspace/download")
async def download_workspace_file(path: str = Query(..., description="文件相对路径")):
    """下载workspace目录中的文件"""
    workspace_path = get_workspace_path()
    if not workspace_path or not os.path.exists(workspace_path):
        raise SageHTTPException(
            status_code=404,
            detail="工作空间目录不存在",
            error_detail=f"Workspace directory not found: {workspace_path}",
        )

    # 构建完整路径
    full_path = os.path.join(workspace_path, path.lstrip("/"))

    # 安全检查
    if not is_safe_path(workspace_path, full_path):
        raise SageHTTPException(
            status_code=403,
            detail="访问被拒绝：路径超出工作空间范围",
            error_detail="Access denied: path outside workspace",
        )

    # 检查文件是否存在
    if not os.path.exists(full_path):
        raise SageHTTPException(
            status_code=404,
            detail=f"文件不存在: {path}",
            error_detail=f"File not found: {path}",
        )

    # 检查是否为文件
    if not os.path.isfile(full_path):
        raise SageHTTPException(
            status_code=400,
            detail=f"路径不是文件: {path}",
            error_detail=f"Path is not a file: {path}",
        )

    # 获取MIME类型
    mime_type, _ = mimetypes.guess_type(full_path)
    if mime_type is None:
        mime_type = "application/octet-stream"

    return FileResponse(
        path=full_path, filename=os.path.basename(path), media_type=mime_type
    )


@file_server_router.get("/api/files/logs")
async def browse_logs(request: Request, path: str = Query("", description="相对路径")):
    """浏览logs目录"""
    logs_path = get_logs_path()
    if not logs_path or not os.path.exists(logs_path):
        raise SageHTTPException(
            status_code=404,
            detail="日志目录不存在",
            error_detail=f"Logs directory not found: {logs_path}",
        )

    # 构建完整路径
    if path:
        full_path = os.path.join(logs_path, path.lstrip("/"))
    else:
        full_path = logs_path

    # 安全检查
    if not is_safe_path(logs_path, full_path):
        raise SageHTTPException(
            status_code=403,
            detail="访问被拒绝：路径超出日志目录范围",
            error_detail="Access denied: path outside logs directory",
        )

    # 检查路径是否存在
    if not os.path.exists(full_path):
        raise SageHTTPException(
            status_code=404,
            detail=f"路径不存在: {path}",
            error_detail=f"Path not found: {path}",
        )

    # 如果是文件，直接返回文件内容
    if os.path.isfile(full_path):
        return FileResponse(path=full_path, filename=os.path.basename(full_path))

    # 如果是目录，返回目录列表
    base_url = "/api/files/logs"
    html_content = get_directory_listing(full_path, base_url, path)
    return HTMLResponse(content=html_content)


@file_server_router.get("/api/files/logs/download")
async def download_logs_file(path: str = Query(..., description="文件相对路径")):
    """下载logs目录中的文件"""
    logs_path = get_logs_path()
    if not logs_path or not os.path.exists(logs_path):
        raise SageHTTPException(
            status_code=404,
            detail="日志目录不存在",
            error_detail=f"Logs directory not found: {logs_path}",
        )

    # 构建完整路径
    full_path = os.path.join(logs_path, path.lstrip("/"))

    # 安全检查
    if not is_safe_path(logs_path, full_path):
        raise SageHTTPException(
            status_code=403,
            detail="访问被拒绝：路径超出日志目录范围",
            error_detail="Access denied: path outside logs directory",
        )

    # 检查文件是否存在
    if not os.path.exists(full_path):
        raise SageHTTPException(
            status_code=404,
            detail=f"文件不存在: {path}",
            error_detail=f"File not found: {path}",
        )

    # 检查是否为文件
    if not os.path.isfile(full_path):
        raise SageHTTPException(
            status_code=400,
            detail=f"路径不是文件: {path}",
            error_detail=f"Path is not a file: {path}",
        )

    # 获取MIME类型
    mime_type, _ = mimetypes.guess_type(full_path)
    if mime_type is None:
        mime_type = "application/octet-stream"

    return FileResponse(
        path=full_path, filename=os.path.basename(path), media_type=mime_type
    )


@file_server_router.get("/api/files/info")
async def get_file_server_info():
    """获取文件服务器信息"""
    workspace_path = get_workspace_path()
    logs_path = get_logs_path()

    return Response.succ(
        message="文件服务器信息",
        data={
            "workspace": {
                "path": workspace_path,
                "exists": os.path.exists(workspace_path) if workspace_path else False,
                "browse_url": "/api/files/workspace",
                "download_url": "/api/files/workspace/download",
            },
            "logs": {
                "path": logs_path,
                "exists": os.path.exists(logs_path) if logs_path else False,
                "browse_url": "/api/files/logs",
                "download_url": "/api/files/logs/download",
            },
            "endpoints": [
                "GET /api/files/workspace - 浏览工作空间目录",
                "GET /api/files/workspace/download - 下载工作空间文件",
                "GET /api/files/workspace/preview - 预览工作空间文件",
                "GET /api/files/logs - 浏览日志目录",
                "GET /api/files/logs/download - 下载日志文件",
                "GET /api/files/logs/preview - 预览日志文件",
                "GET /api/files/info - 获取文件服务器信息",
            ],
        },
    )


@file_server_router.get("/api/files/workspace/preview")
async def preview_workspace_file(path: str = Query(..., description="文件相对路径")):
    """预览workspace目录中的文件"""
    workspace_path = get_workspace_path()
    if not workspace_path or not os.path.exists(workspace_path):
        raise SageHTTPException(
            status_code=404,
            detail="工作空间目录不存在",
            error_detail=f"Workspace directory not found: {workspace_path}",
        )

    # 构建完整路径
    full_path = os.path.join(workspace_path, path.lstrip("/"))

    # 安全检查
    if not is_safe_path(workspace_path, full_path):
        raise SageHTTPException(
            status_code=403,
            detail="访问被拒绝：路径超出工作空间范围",
            error_detail="Access denied: path outside workspace",
        )

    # 检查文件是否存在
    if not os.path.exists(full_path):
        raise SageHTTPException(
            status_code=404,
            detail=f"文件不存在: {path}",
            error_detail=f"File not found: {path}",
        )

    # 检查是否为文件
    if not os.path.isfile(full_path):
        raise SageHTTPException(
            status_code=400,
            detail=f"路径不是文件: {path}",
            error_detail=f"Path is not a file: {path}",
        )

    # 检查是否支持预览
    if not is_previewable_file(full_path):
        raise SageHTTPException(
            status_code=400,
            detail=f"文件类型不支持预览: {path}",
            error_detail=f"File type not supported for preview: {path}",
        )

    # 获取文件内容
    content, file_type = get_file_content_for_preview(full_path)

    # 生成预览页面
    filename = os.path.basename(path)
    file_size = format_file_size(os.path.getsize(full_path))
    download_url = f"/api/files/workspace/download?path={path}"

    # 生成返回目录的URL
    parent_path = "/".join(path.split("/")[:-1]) if "/" in path else ""
    back_url = (
        f"/api/files/workspace?path={parent_path}"
        if parent_path
        else "/api/files/workspace"
    )

    html_content = PREVIEW_TEMPLATE.format(
        filename=filename,
        file_size=file_size,
        file_type=file_type,
        download_url=download_url,
        back_url=back_url,
        content=content,
    )

    return HTMLResponse(content=html_content)


@file_server_router.get("/api/files/logs/preview")
async def preview_logs_file(path: str = Query(..., description="文件相对路径")):
    """预览logs目录中的文件"""
    logs_path = get_logs_path()
    if not logs_path or not os.path.exists(logs_path):
        raise SageHTTPException(
            status_code=404,
            detail="日志目录不存在",
            error_detail=f"Logs directory not found: {logs_path}",
        )

    # 构建完整路径
    full_path = os.path.join(logs_path, path.lstrip("/"))

    # 安全检查
    if not is_safe_path(logs_path, full_path):
        raise SageHTTPException(
            status_code=403,
            detail="访问被拒绝：路径超出日志目录范围",
            error_detail="Access denied: path outside logs directory",
        )

    # 检查文件是否存在
    if not os.path.exists(full_path):
        raise SageHTTPException(
            status_code=404,
            detail=f"文件不存在: {path}",
            error_detail=f"File not found: {path}",
        )

    # 检查是否为文件
    if not os.path.isfile(full_path):
        raise SageHTTPException(
            status_code=400,
            detail=f"路径不是文件: {path}",
            error_detail=f"Path is not a file: {path}",
        )

    # 检查是否支持预览
    if not is_previewable_file(full_path):
        raise SageHTTPException(
            status_code=400,
            detail=f"文件类型不支持预览: {path}",
            error_detail=f"File type not supported for preview: {path}",
        )

    # 获取文件内容
    content, file_type = get_file_content_for_preview(full_path)

    # 生成预览页面
    filename = os.path.basename(path)
    file_size = format_file_size(os.path.getsize(full_path))
    download_url = f"/api/files/logs/download?path={path}"

    # 生成返回目录的URL
    parent_path = "/".join(path.split("/")[:-1]) if "/" in path else ""
    back_url = (
        f"/api/files/logs?path={parent_path}" if parent_path else "/api/files/logs"
    )

    html_content = PREVIEW_TEMPLATE.format(
        filename=filename,
        file_size=file_size,
        file_type=file_type,
        download_url=download_url,
        back_url=back_url,
        content=content,
    )

    return HTMLResponse(content=html_content)
