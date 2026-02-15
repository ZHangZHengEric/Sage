import os
import json
import re
from typing import List, Dict, Any, Optional

from ..tool_base import tool
from sagents.utils.logger import logger
from sagents.context.session_context import get_session_context
import datetime

class ToDoTool:
    """任务清单管理工具"""

    def _get_todo_path(self, session_id: Optional[str] = None, session_context: Optional[Any] = None) -> str:
        """获取任务清单文件路径"""
        # 优先使用传入的 session_context
        if session_context:
            try:
                ws = session_context.agent_workspace
                if isinstance(ws, str):
                    return os.path.join(ws, "todo_list.md")
                elif hasattr(ws, 'host_path'): # SandboxFileSystem
                    return os.path.join(ws.host_path, "todo_list.md")
            except Exception as e:
                logger.warning(f"通过 session_context 获取路径失败: {e}")

        # 尝试通过 session_id 获取上下文
        if session_id:
            try:
                session_context = get_session_context(session_id)
                if session_context:
                    ws = session_context.agent_workspace
                    if isinstance(ws, str):
                        return os.path.join(ws, "todo_list.md")
                    elif hasattr(ws, 'host_path'): # SandboxFileSystem
                        return os.path.join(ws.host_path, "todo_list.md")
            except Exception as e:
                logger.warning(f"通过 session_id 获取路径失败: {e}")
        
        # 退化为当前工作目录
        return os.path.join(os.getcwd(), "todo_list.md")

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
        pattern = re.compile(r'- \[(x| )\] (.*?) \(ID: (.*?)\)(?: \(Updated: (.*?)\))?$')

        for line in lines:
            line = line.strip()
            match = pattern.match(line)
            if match:
                is_completed = match.group(1) == 'x'
                content_text = match.group(2).strip()
                task_id = match.group(3).strip()
                updated_at = match.group(4)
                
                tasks.append({
                    'id': task_id,
                    'content': content_text,
                    'completed': is_completed,
                    'updated_at': updated_at if updated_at else None
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
        
        session_context = get_session_context(session_id)
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
            
            # 兼容旧的 status 字段，优先使用 completed 字段
            if 'status' in new_task:
                 new_task.pop('status')

            # Set updated_at
            new_task['updated_at'] = now_str

            if task_id in task_map:
                # 更新
                task_map[task_id].update(new_task)
                updated_count += 1
            else:
                # 新增
                if 'content' not in new_task or not new_task['content']:
                     logger.warning(f"ToDoTool: New task {task_id} missing content. Skipping.", session_id=session_id)
                     continue

                task_map[task_id] = new_task
                added_count += 1
        
        # 转换回列表
        final_tasks = list(task_map.values())
        
        if self._save_todo_file(file_path, final_tasks):
            logger.info(f"ToDoTool: Tasks saved. Added: {added_count}, Updated: {updated_count}", session_id=session_id)
            
            # 获取未完成任务用于显示
            pending = [t for t in final_tasks if not t.get('completed', False)]
            summary = f"成功更新任务清单。新增: {added_count}, 更新: {updated_count}。\n"
            summary += f"当前未完成任务数: {len(pending)}"
            return summary
        else:
            logger.error(f"ToDoTool: Failed to save tasks to {file_path}", session_id=session_id)
            return "保存任务清单失败。"

    def clean_old_tasks(self, session_id: Optional[str] = None, session_context: Optional[Any] = None):
        """
        清理过期的任务（超过5分钟未更新的任务）
        """
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
                    if (now - updated_at).total_seconds() <= 300: # 5 minutes
                        filtered_tasks.append(t)
                    else:
                        # 超过5分钟的任务，直接丢弃
                        has_changes = True
                except ValueError:
                    # 解析失败，保留或丢弃？这里保留
                    filtered_tasks.append(t)
            else:
                # 没有时间戳，视为过期，丢弃
                has_changes = True

        if has_changes:
                # 保存过滤后的任务列表回文件（永久删除旧任务）
                self._save_todo_file(file_path, filtered_tasks)
                logger.debug(f"已清理过期任务，剩余 {len(filtered_tasks)} 个任务",session_id=session_id)

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
            result += f"- {t.get('content')} (ID: {t.get('id')})\n"
            
        return result
