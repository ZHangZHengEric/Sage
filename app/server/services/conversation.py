"""
会话业务处理模块

封装会话相关的业务逻辑，供路由层调用。
"""

import json
import os
import mimetypes
import tempfile
import zipfile
import shutil
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from sagents.context.session_context import SessionStatus, get_session_context, get_session_messages, _get_workspace_root, get_sub_session_messages

from .. import models
from ..core.exceptions import SageHTTPException


async def interrupt_session(
    session_id: str, message: str = "用户请求中断"
) -> Dict[str, Any]:
    """中断指定会话，返回数据字典"""
    session_context = get_session_context(session_id)
    if not session_context:
        logger.bind(session_id=session_id).info("会话不存在或者已完成")
        return {"session_id": session_id}

    session_context.status = SessionStatus.INTERRUPTED
    logger.bind(session_id=session_id).info("会话中断成功")
    return {"session_id": session_id}


async def get_session_status(session_id: str) -> Dict[str, Any]:
    """获取指定会话的状态"""
    session_context = get_session_context(session_id)
    if not session_context:
        raise SageHTTPException(
            status_code=404,
            detail=f"会话 {session_id} 已完成或者不存在",
            error_detail=f"Session '{session_id}' completed or not found",
        )

    tasks_status = session_context.task_manager.to_dict()
    logger.bind(session_id=session_id).info(f"获取任务数量：{len(tasks_status.get('tasks', []))}")
    return {"session_id": session_id, "tasks_status": tasks_status}


async def get_file_workspace(session_id: str) -> Dict[str, Any]:
    """获取指定会话的文件工作空间内容"""
    workspace_root = _get_workspace_root()
    workspace_path = os.path.join(workspace_root, session_id, "agent_workspace")

    if not workspace_path or not os.path.exists(workspace_path):
        return {
            "session_id": session_id,
            "files": [],
            "message": "工作空间为空",
        }

    files: List[Dict[str, Any]] = []
    for root, dirs, filenames in os.walk(workspace_path):
        # 过滤掉隐藏文件和文件夹
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        filenames = [f for f in filenames if not f.startswith(".")]
        for filename in filenames:
            file_path = os.path.join(root, filename)
            relative_path = os.path.relpath(file_path, workspace_path)
            file_stat = os.stat(file_path)
            files.append(
                {
                    "name": filename,
                    "path": relative_path,
                    "size": file_stat.st_size,
                    "modified_time": file_stat.st_mtime,
                    "is_directory": False,
                }
            )

        for dirname in dirs:
            dir_path = os.path.join(root, dirname)
            relative_path = os.path.relpath(dir_path, workspace_path)
            files.append(
                {
                    "name": dirname,
                    "path": relative_path,
                    "size": 0,
                    "modified_time": os.stat(dir_path).st_mtime,
                    "is_directory": True,
                }
            )

    logger.bind(session_id=session_id).info(f"获取工作空间文件数量：{len(files)}")
    return {
        "session_id": session_id,
        "files": files,
        "message": "获取文件列表成功",
    }


def resolve_download_path(workspace_path: str, file_path: str) -> str:
    """校验并返回可下载的文件绝对路径"""
    if not workspace_path or not file_path:
        raise SageHTTPException(
            status_code=400,
            detail="缺少必要的路径参数",
            error_detail="workspace_path or file_path missing",
        )
    full_file_path = os.path.join(workspace_path, file_path)
    if not os.path.abspath(full_file_path).startswith(os.path.abspath(workspace_path)):
        raise SageHTTPException(
            status_code=403,
            detail="访问被拒绝：文件路径超出工作空间范围",
            error_detail="Access denied: file path outside workspace",
        )
    if not os.path.exists(full_file_path):
        raise SageHTTPException(
            status_code=404,
            detail=f"文件不存在: {file_path}",
            error_detail=f"File not found: {file_path}",
        )
    return full_file_path


async def get_conversations_paginated(
    page: int = 1,
    page_size: int = 10,
    user_id: Optional[str] = None,
    search: Optional[str] = None,
    agent_id: Optional[str] = None,
    sort_by: str = "date",
) -> Tuple[List[models.Conversation], int]:
    """分页获取会话列表并构造响应字典"""
    dao = models.ConversationDao()
    conversations, total_count = await dao.get_conversations_paginated(
        page=page,
        page_size=page_size,
        user_id=user_id,
        search=search,
        agent_id=agent_id,
        sort_by=sort_by or "date",
    )
    return conversations, total_count


async def get_conversation_messages(conversation_id: str) -> Dict[str, Any]:
    """获取指定对话的所有消息并返回响应字典"""
    dao = models.ConversationDao()
    conversation = await dao.get_by_session_id(conversation_id)
    if not conversation:
        raise SageHTTPException(
            status_code=404,
            detail=f"会话 {conversation_id} 不存在",
            error_detail=f"Conversation '{conversation_id}' not found",
        )

    messages = []
    for m in get_session_messages(conversation_id):
        result = m.to_dict()

        # 处理大内容的特殊情况
        content = result.get('content', '')

        # 特殊处理工具调用结果，避免JSON嵌套问题
        if result.get('role') == 'tool' and isinstance(content, str):
            try:
                # 尝试解析content中的JSON数据
                if content.strip().startswith('{'):
                    parsed_content = json.loads(content)

                    # 检查是否是嵌套的JSON结构
                    if isinstance(parsed_content, dict) and 'content' in parsed_content:
                        inner_content = parsed_content['content']
                        if isinstance(inner_content, str) and inner_content.strip().startswith('{'):
                            try:
                                # 解析内层JSON，这通常是实际的工具结果
                                tool_data = json.loads(inner_content)

                                # 清理工具结果中的大数据，避免JSON过大
                                if isinstance(tool_data, dict) and 'results' in tool_data:
                                    if isinstance(tool_data['results'], list):
                                        for item in tool_data['results']:
                                            if isinstance(item, dict):
                                                # 限制文本字段长度，但保留所有字段
                                                for field in ['snippet', 'description', 'content']:
                                                    if field in item and isinstance(item[field], str):
                                                        if len(item[field]) > 1000:
                                                            item[field] = item[field][:1000] + '...[TRUNCATED]'

                                # 直接使用解析后的数据
                                result['content'] = tool_data
                            except json.JSONDecodeError:
                                # 内层解析失败，使用外层数据
                                result['content'] = parsed_content
                        else:
                            # 内层不是JSON字符串，直接使用
                            result['content'] = parsed_content
                    else:
                        # 不是嵌套结构，直接使用
                        result['content'] = parsed_content

            except json.JSONDecodeError as e:
                logger.warning(f"解析工具结果JSON失败: {e}")
                # 保持原始字符串
                pass

        messages.append(result)

        # 处理 sys_delegate_task，将子任务的对话记录拼接在后面
        if result.get('role') == 'assistant' and result.get('tool_calls'):
            for tool_call in result['tool_calls']:
                if tool_call.get('function', {}).get('name') == 'sys_delegate_task':
                    try:
                        arguments = tool_call['function']['arguments']
                        if isinstance(arguments, str):
                            args = json.loads(arguments)
                        else:
                            args = arguments
                        
                        tasks = args.get('tasks', [])
                        if isinstance(tasks, list):
                            for task in tasks:
                                if isinstance(task, dict):
                                    sub_session_id = task.get('session_id')
                                    if sub_session_id:
                                        sub_msgs = get_sub_session_messages(conversation_id, sub_session_id)
                                        for sub_msg in sub_msgs:
                                            messages.append(sub_msg.to_dict())
                    except Exception as e:
                        logger.warning(f"处理子任务消息失败: {e}")
    return {
        "conversation_id": conversation_id,
        "messages": messages,
        "message_count": len(messages),
        "conversation_info": {
            "session_id": conversation.session_id,
            "user_id": conversation.user_id,
            "agent_id": conversation.agent_id,
            "agent_name": conversation.agent_name,
            "title": conversation.title,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
        },
    }


async def delete_conversation(conversation_id: str) -> str:
    """删除指定对话，返回 conversation_id"""
    dao = models.ConversationDao()
    conversation = await dao.get_by_session_id(conversation_id)
    if not conversation:
        raise SageHTTPException(
            status_code=404,
            detail=f"会话 {conversation_id} 不存在",
            error_detail=f"Conversation '{conversation_id}' not found",
        )

    success = await dao.delete_conversation(conversation_id)
    if not success:
        raise SageHTTPException(
            status_code=500,
            detail=f"删除会话 {conversation_id} 失败",
            error_detail=f"Failed to delete conversation '{conversation_id}'",
        )
    logger.bind(session_id=conversation_id).info("会话删除成功")
    return conversation_id


async def download_session_file(session_id: str, file_path: str) -> Tuple[str, str, str]:
    """
    下载会话文件

    :param session_id: 会话ID
    :param file_path: 相对文件路径
    :return: (file_path, filename, media_type)
    """
    workspace_root = _get_workspace_root()
    workspace_path = os.path.join(workspace_root, session_id, "agent_workspace")

    full_path = resolve_download_path(workspace_path, file_path)

    # 检查是否为文件或目录
    if os.path.isdir(full_path):
        # 如果是目录，创建zip文件并下载
        try:
            # 使用临时文件存储zip
            temp_dir = tempfile.gettempdir()
            zip_filename = f"{os.path.basename(full_path)}.zip"
            zip_path = os.path.join(temp_dir, zip_filename)

            # 创建zip文件
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(full_path):
                    for file in files:
                        file_abs_path = os.path.join(root, file)
                        # 计算在zip中的相对路径
                        rel_path = os.path.relpath(file_abs_path, full_path)
                        zipf.write(file_abs_path, rel_path)

            return zip_path, zip_filename, "application/zip"
        except Exception as e:
            raise SageHTTPException(
                status_code=500,
                detail=f"创建压缩文件失败: {str(e)}",
                error_detail=f"Failed to create zip file: {str(e)}",
            )

    if not os.path.isfile(full_path):
        raise SageHTTPException(
            status_code=400,
            detail=f"路径不是文件: {file_path}",
            error_detail=f"Path is not a file: {file_path}",
        )

    # 获取MIME类型
    mime_type, _ = mimetypes.guess_type(full_path)
    if mime_type is None:
        mime_type = "application/octet-stream"

    return full_path, os.path.basename(full_path), mime_type
