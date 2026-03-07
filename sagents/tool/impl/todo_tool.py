import os
import json
import re
from typing import List, Dict, Any, Optional

from ..tool_base import tool
from sagents.utils.logger import logger
from sagents.context.session_context import SessionContext
import datetime

class ToDoTool:
    """任务清单管理工具"""

    def _get_todo_path(self, session_id: Optional[str] = None, session_context: Optional[SessionContext] = None) -> str:
        """获取任务清单文件路径"""
        # 确定文件名
        if session_id:
            filename = f"TODO_LIST_{session_id}.md"
        else:
            filename = "TODO_LIST_default.md"
        
        # 优先使用传入的 session_context
        if session_context:
            try:
                ws = session_context.agent_workspace_sandbox.file_system
                if isinstance(ws, str):
                    return os.path.join(ws, filename)
                elif hasattr(ws, 'host_path'): # SandboxFileSystem
                    return os.path.join(ws.host_path, filename)
            except Exception as e:
                logger.warning(f"通过 session_context 获取路径失败: {e}")

        # 尝试通过 session_id 获取上下文
        if session_id:
            try:
                from sagents.session_runtime import get_global_session_manager
                session_manager = get_global_session_manager()
                session = session_manager.get(session_id)
                if session and session.session_context:
                    session_context = session.session_context
                    ws = session_context.agent_workspace_sandbox.file_system
                    if isinstance(ws, str):
                        return os.path.join(ws, filename)
                    elif hasattr(ws, 'host_path'): # SandboxFileSystem
                        return os.path.join(ws.host_path, filename)
            except Exception as e:
                logger.warning(f"通过 session_id 获取路径失败: {e}")
        
        # 退化为当前工作目录
        return os.path.join(os.getcwd(), filename)

    def _clean_other_session_todo_files(self, session_id: Optional[str] = None, session_context: Optional[Any] = None, time_threshold: int = 300):
        """
        清理 workspace 下其他 session 的过期 todo 文件
        支持沙箱文件系统
        """
        try:
            # 获取 workspace 和文件系统对象
            fs = None
            workspace_dir = None

            if session_context:
                ws = session_context.agent_workspace_sandbox.file_system
                if hasattr(ws, 'host_path'):  # SandboxFileSystem
                    fs = ws
                    workspace_dir = ws.host_path
                elif isinstance(ws, str):
                    workspace_dir = ws
            elif session_id:
                try:
                    from sagents.session_runtime import get_global_session_manager
                    session_manager = get_global_session_manager()
                    session = session_manager.get(session_id)
                    if session and session.session_context:
                        sc = session.session_context
                        ws = sc.agent_workspace_sandbox.file_system
                        if hasattr(ws, 'host_path'):  # SandboxFileSystem
                            fs = ws
                            workspace_dir = ws.host_path
                        elif isinstance(ws, str):
                            workspace_dir = ws
                except Exception:
                    pass

            if not workspace_dir or not os.path.exists(workspace_dir):
                return

            now = datetime.datetime.now()
            pattern = re.compile(r'TODO_LIST_(.+?)\.md$')

            for filename in os.listdir(workspace_dir):
                match = pattern.match(filename)
                if match:
                    other_session_id = match.group(1)
                    # 跳过当前 session
                    if other_session_id == session_id:
                        continue

                    try:
                        if fs:  # 使用沙箱文件系统
                            # 检查文件是否存在
                            if fs.exists(filename):
                                # 获取文件状态
                                stat = fs.stat(filename)
                                if stat:
                                    file_mtime = datetime.datetime.fromtimestamp(stat.st_mtime)
                                    if (now - file_mtime).total_seconds() > time_threshold:
                                        # 文件过期，删除
                                        fs.remove(filename)
                                        logger.info(f"已删除过期 todo 文件 (沙箱): {filename} (session: {other_session_id})")
                        else:  # 使用普通文件系统
                            other_file_path = os.path.join(workspace_dir, filename)
                            if os.path.exists(other_file_path):
                                stat = os.stat(other_file_path)
                                file_mtime = datetime.datetime.fromtimestamp(stat.st_mtime)
                                if (now - file_mtime).total_seconds() > time_threshold:
                                    os.remove(other_file_path)
                                    logger.info(f"已删除过期 todo 文件: {filename} (session: {other_session_id})")
                    except Exception as e:
                        logger.warning(f"清理 todo 文件失败 {filename}: {e}")
        except Exception as e:
            logger.error(f"清理其他 session todo 文件失败: {e}")

    @staticmethod
    def parse_todo_list(content: str) -> List[Dict[str, Any]]:
        """
        静态方法：解析任务清单内容字符串
        
        Args:
            content: 任务清单文件内容
            
        Returns:
            List[Dict[str, Any]]: 解析后的任务列表
        """
        tasks = []
        lines = content.splitlines()
        
        # Regex for "- [ ] content (ID: id) (Updated: timestamp)"
        pattern = re.compile(r'- \[(x| )\] (.*?) \(ID: (.*?)\)(?: \(Updated: (.*?)\))?(?: \(Conclusion: (.*?)\))?$')

        for line in lines:
            line = line.strip()
            match = pattern.match(line)
            if match:
                is_completed = match.group(1) == 'x'
                content_text = match.group(2).strip()
                task_id = match.group(3).strip()
                updated_at = match.group(4)
                conclusion = match.group(5)

                tasks.append({
                    'id': task_id,
                    'content': content_text,
                    'completed': is_completed,
                    'updated_at': updated_at if updated_at else None,
                    'conclusion': conclusion if conclusion else None
                })
        return tasks

    def _read_todo_file(self, file_path: str) -> List[Dict[str, Any]]:
        """读取并解析任务清单文件"""
        if not os.path.exists(file_path):
            return []
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return self.parse_todo_list(content)
        except Exception as e:
            logger.error(f"读取任务清单失败: {e}")
            return []

    def _save_todo_file(self, file_path: str, tasks: List[Dict[str, Any]]) -> bool:
        """保存任务清单到文件"""
        try:
            # 生成 Markdown 内容
            md_content = "# ToDo List\n\n"
            
            pending_tasks = [t for t in tasks if not t.get('completed', False)]
            completed_tasks = [t for t in tasks if t.get('completed', False)]
            
            if not tasks:
                md_content += "(No tasks yet)\n"
            else:
                md_content += "## Pending\n"
                for t in pending_tasks:
                    line = f"- [ ] {t.get('content', '')} (ID: {t.get('id')})"
                    if t.get('updated_at'):
                        line += f" (Updated: {t.get('updated_at')})"
                    md_content += line + "\n"

                md_content += "\n## Completed\n"
                for t in completed_tasks:
                    line = f"- [x] {t.get('content', '')} (ID: {t.get('id')})"
                    if t.get('updated_at'):
                        line += f" (Updated: {t.get('updated_at')})"
                    if t.get('conclusion'):
                        line += f" (Conclusion: {t.get('conclusion')})"
                    md_content += line + "\n"
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(md_content)
                
            return True
        except Exception as e:
            logger.error(f"保存任务清单失败: {e}")
            return False



    @tool(
        description_i18n={
            "zh": "创建或更新任务清单，新增任务需包含 id, content；更新任务只需 id 和变更字段(content/completed)。未变更的任务无需传入。",
            "en": "Create or update todo list",
        },
        param_description_i18n={
            "tasks": {
                "zh": "任务列表。新增任务需包含 id, content；更新任务只需 id 和变更字段(content/completed)。未变更的任务无需传入。",
                "en": "List of tasks. New tasks need id, content; updates need id and changed fields (content/completed). Unchanged tasks can be omitted."
            },
            "session_id": {
                "zh": "会话ID，用于定位工作区",
                "en": "Session ID, used to locate workspace"
            }
        },
        param_schema={
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Unique identifier for the task"
                        },
                        "content": {
                            "type": "string",
                            "description": "Content/Description of the task. Required for new tasks."
                        },
                        "completed": {
                            "type": "boolean",
                            "description": "Whether the task is completed. Default is false (pending)."
                        },
                        "conclusion": {
                            "type": "string",
                            "description": "Execution conclusion or comment about the task. Added when task is completed, used for summary and guidance."
                        }
                    },
                    "required": ["id"]
                }
            },
            "session_id": {
                "type": "string",
                "description": "Session ID, used to locate workspace"
            }
        }
    )
    def todo_write(self, tasks: List[Dict[str, Any]], session_id: Optional[str] = None) -> str:
        """
        创建或更新任务清单。
        如果任务ID已存在，则更新该任务；如果不存在，则添加新任务。
        
        Args:
            tasks: 任务列表，例如 [{'id': '1', 'content': '任务内容', 'completed': False}]
            session_id: 会话ID
        """
        if not session_id:
            raise ValueError("ToDoTool: session_id is required")
        
        logger.debug(f"ToDoTool: todo_write called. session_id={session_id}")

        from sagents.session_runtime import get_global_session_manager
        session_manager = get_global_session_manager()
        session = session_manager.get(session_id)
        if not session or not session.session_context:
            raise ValueError(f"ToDoTool: Invalid session_id={session_id}")
        
        session_context = session.session_context
        file_path = self._get_todo_path(session_id, session_context)
        current_tasks = self._read_todo_file(file_path)
        
        # 建立索引以便更新
        task_map = {str(t.get('id')): t for t in current_tasks}
        
        updated_count = 0
        added_count = 0
        
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        for new_task in tasks:
            task_id = str(new_task.get('id'))
            if not task_id:
                continue
            
            # 兼容旧的 status 字段，转换为 completed 字段
            if 'status' in new_task:
                status = new_task.pop('status')
                # 如果 status 是 "completed"，设置 completed 为 True
                if status == 'completed' and 'completed' not in new_task:
                    new_task['completed'] = True

            # Set updated_at
            new_task['updated_at'] = now_str

            if task_id in task_map:
                # 更新
                task_map[task_id].update(new_task)
                updated_count += 1
            else:
                # 新增
                # 如果没有 content 但有 conclusion，使用 conclusion 作为 content
                if ('content' not in new_task or not new_task['content']) and 'conclusion' in new_task:
                    new_task['content'] = new_task['conclusion']
                
                if 'content' not in new_task or not new_task['content']:
                     logger.warning(f"ToDoTool: New task {task_id} missing content. Skipping.", session_id=session_id)
                     continue

                task_map[task_id] = new_task
                added_count += 1
        
        # 转换回列表，并添加 index 字段
        final_tasks = list(task_map.values())

        # 按原始任务列表的顺序分配 index（如果传入的任务有顺序，保留该顺序）
        # 首先给现有任务分配 index（基于它们在 task_map 中的顺序）
        for idx, task in enumerate(final_tasks, start=1):
            task['index'] = idx

        # 检查是否所有任务都已完成
        pending_tasks = [t for t in final_tasks if not t.get('completed', False)]

        # 构建任务列表（用于返回）- 按 index 排序确保顺序一致
        sorted_tasks = sorted(final_tasks, key=lambda t: t.get('index', 0))
        task_list = [
            {
                "index": t.get('index', 0),
                "id": str(t.get('id', '')),
                "name": t.get('content', ''),
                "status": "completed" if t.get('completed', False) else "pending"
            }
            for t in sorted_tasks
        ]

        logger.debug(f"ToDoTool: Checking deletion condition - pending_tasks: {len(pending_tasks)}, final_tasks: {len(final_tasks)}, file_path: {file_path}", session_id=session_id)
        
        if not pending_tasks and final_tasks:
            # 所有任务都已完成，删除 todo 文件
            try:
                logger.debug(f"ToDoTool: Attempting to delete file: {file_path}, exists: {os.path.exists(file_path)}", session_id=session_id)
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"ToDoTool: All tasks completed. Deleted todo file: {file_path}", session_id=session_id)
                    # 返回完整的任务列表（虽然文件已删除）
                    result = {
                        "summary": f"所有任务已完成！任务清单已清理。\n新增: {added_count}, 更新: {updated_count}",
                        "tasks": task_list
                    }
                    return json.dumps(result, ensure_ascii=False, indent=2)
                else:
                    logger.warning(f"ToDoTool: File does not exist, cannot delete: {file_path}", session_id=session_id)
            except Exception as e:
                logger.error(f"ToDoTool: Failed to delete todo file: {e}", session_id=session_id)

        if self._save_todo_file(file_path, final_tasks):
            logger.info(f"ToDoTool: Tasks saved. Added: {added_count}, Updated: {updated_count}", session_id=session_id)

            # 构建 JSON 返回结果（task_list 已在上面的代码中构建）
            result = {
                "summary": f"成功更新任务清单。新增: {added_count}, 更新: {updated_count}。当前未完成任务数: {len(pending_tasks)}",
                "tasks": task_list
            }
            return json.dumps(result, ensure_ascii=False, indent=2)
        else:
            logger.error(f"ToDoTool: Failed to save tasks to {file_path}", session_id=session_id)
            return json.dumps({"summary": "保存任务清单失败。", "tasks": []}, ensure_ascii=False)

    def clean_old_tasks(self, session_id: Optional[str] = None, session_context: Optional[Any] = None, time_threshold: int = 300):
        """
        清理过期的任务（超过5分钟未更新的任务）
        如果清理后任务为空，删除 todo 文件
        同时清理 workspace 下其他 session 的过期 todo 文件
        """
        # 1. 清理当前 session 的 todo 文件
        file_path = self._get_todo_path(session_id, session_context)
        tasks = self._read_todo_file(file_path)

        now = datetime.datetime.now()
        filtered_tasks = []
        has_changes = False

        for t in tasks:
            updated_at_str = t.get('updated_at')
            if updated_at_str:
                try:
                    updated_at = datetime.datetime.strptime(updated_at_str, '%Y-%m-%d %H:%M:%S')
                    if (now - updated_at).total_seconds() <= time_threshold: # 5 minutes
                        filtered_tasks.append(t)
                    else:
                        # 超过5分钟的任务，直接丢弃
                        has_changes = True
                except ValueError:
                    # 解析失败，保留
                    filtered_tasks.append(t)
            else:
                # 没有时间戳，视为过期，丢弃
                has_changes = True

        if has_changes:
            if not filtered_tasks:
                # 清理后为空，删除文件
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        logger.info(f"已清理所有过期任务，删除空 todo 文件: {file_path}", session_id=session_id)
                except Exception as e:
                    logger.error(f"删除空 todo 文件失败: {e}", session_id=session_id)
            else:
                # 保存过滤后的任务列表回文件
                self._save_todo_file(file_path, filtered_tasks)
                logger.debug(f"已清理过期任务，剩余 {len(filtered_tasks)} 个任务", session_id=session_id)

        # 2. 清理 workspace 下其他 session 的过期 todo 文件
        self._clean_other_session_todo_files(session_id, session_context, time_threshold)

    @tool(
        description_i18n={
            "zh": "读取当前未完成的任务清单",
            "en": "Read current pending todo list",
            "zh_Hant": "讀取當前未完成的任務清單"
        },
        param_description_i18n={
            "session_id": {
                "zh": "会话ID，用于定位工作区",
                "en": "Session ID, used to locate workspace",
                "zh_Hant": "會話ID，用於定位工作區"
            }
        }
    )
    def todo_read(self, session_id: Optional[str] = None, session_context: Optional[Any] = None) -> str:
        """
        读取并显示当前未完成的任务。
        """
        file_path = self._get_todo_path(session_id, session_context)
        tasks = self._read_todo_file(file_path)
        
        pending = [t for t in tasks if not t.get('completed', False)]

        
        if not pending:
            return "当前没有未完成的任务。"
            
        result = "当前未完成任务清单:\n"
        for t in pending:
            result += f"- {t.get('content')} (ID: {t.get('id')})"
            if t.get('conclusion'):
                result += f" [结论: {t.get('conclusion')}]"
            result += "\n"

        return result
