import os
import json
import re
from typing import List, Dict, Any, Optional

from ..tool_base import tool
from sagents.utils.logger import logger
import datetime

class ToDoTool:
    """任务清单管理工具"""

    def _get_session_context(self, session_id: Optional[str] = None):
        """通过 session_id 获取 session_context"""
        if not session_id:
            return None
        try:
            from sagents.utils.agent_session_helper import get_live_session_context
            ctx = get_live_session_context(session_id, log_prefix="ToDoTool")
            if ctx:
                return ctx
        except Exception as e:
            logger.warning(f"通过 session_id 获取 session_context 失败: {e}")
        return None

    def _get_todo_path(self, session_id: Optional[str] = None) -> str:
        """获取任务清单文件路径（沙箱虚拟路径）"""
        # 确定文件名
        if session_id:
            filename = f"TODO_LIST_{session_id}.md"
        else:
            filename = "TODO_LIST_default.md"

        # 尝试通过 session_id 获取虚拟工作区
        session_context = self._get_session_context(session_id)
        if session_context:
            try:
                sandbox_agent_workspace = session_context.sandbox_agent_workspace
                return os.path.join(sandbox_agent_workspace, filename)
            except Exception as e:
                logger.warning(f"通过 session_context 获取路径失败: {e}")

        # 退化为当前工作目录
        return os.path.join(os.getcwd(), filename)

    def _get_sandbox(self, session_id: Optional[str] = None):
        """通过 session_id 获取 sandbox"""
        session_context = self._get_session_context(session_id)
        if session_context:
            return getattr(session_context, 'sandbox', None)
        return None

    async def _clean_other_session_todo_files(self, session_id: Optional[str] = None, time_threshold: int = 300):
        """
        清理 workspace 下其他 session 的过期 todo 文件
        """
        session_context = self._get_session_context(session_id)
        if not session_context:
            return

        sandbox = getattr(session_context, 'sandbox', None)
        sandbox_agent_workspace = getattr(session_context, 'sandbox_agent_workspace', None)

        if not sandbox or not sandbox_agent_workspace:
            return

        try:
            now = datetime.datetime.now()
            pattern = re.compile(r'TODO_LIST_(.+?)\.md$')

            # 使用沙箱接口列出目录
            try:
                entries = await sandbox.list_directory(sandbox_agent_workspace)
                for entry in entries:
                    if not entry.is_file:
                        continue
                    filename = os.path.basename(entry.path)
                    match = pattern.match(filename)
                    if match:
                        other_session_id = match.group(1)
                        # 跳过当前 session
                        if other_session_id == session_id:
                            continue

                        try:
                            # 检查文件是否过期
                            file_mtime = entry.modified_time
                            if file_mtime and (now - datetime.datetime.fromtimestamp(file_mtime)).total_seconds() > time_threshold:
                                # 文件过期，删除
                                await sandbox.delete_file(entry.path)
                                logger.info(f"已删除过期 todo 文件: {filename} (session: {other_session_id})")
                        except Exception as e:
                            logger.warning(f"清理 todo 文件失败 {filename}: {e}")
            except Exception as e:
                logger.warning(f"列出目录失败: {e}")
        except Exception as e:
            logger.error(f"清理其他 session todo 文件失败: {e}")

    # 三态映射：markdown 复选框字符 ↔ status
    _STATUS_BY_MARK = {'x': 'completed', '-': 'in_progress', ' ': 'pending'}
    _MARK_BY_STATUS = {'completed': 'x', 'in_progress': '-', 'pending': ' '}
    _VALID_STATUSES = ('pending', 'in_progress', 'completed')

    @classmethod
    def _normalize_status(cls, status_value: Any) -> str:
        """将任意 status 输入归一化为三态。未识别值回落 pending。"""
        if isinstance(status_value, str):
            s = status_value.strip().lower()
            if s in cls._VALID_STATUSES:
                return s
            if s in ('done', 'finish', 'finished'):
                return 'completed'
            if s in ('doing', 'started', 'running', 'in-progress', 'inprogress'):
                return 'in_progress'
            if s in ('todo', 'open', 'not_started'):
                return 'pending'
        return 'pending'

    @classmethod
    def parse_todo_list(cls, content: str) -> List[Dict[str, Any]]:
        """
        静态方法：解析任务清单内容字符串

        Args:
            content: 任务清单文件内容

        Returns:
            List[Dict[str, Any]]: 解析后的任务列表
        """
        tasks = []
        lines = content.splitlines()

        # Regex 三态：[ ] pending、[-] in_progress、[x] completed
        pattern = re.compile(r'- \[(x|\-| )\] (.*?) \(ID: (.*?)\)(?: \(Created: (.*?)\))?(?: \(Updated: (.*?)\))?(?: \(Conclusion: (.*?)\))?$')

        for line in lines:
            line = line.strip()
            match = pattern.match(line)
            if match:
                mark = match.group(1)
                status = cls._STATUS_BY_MARK.get(mark, 'pending')
                content_text = match.group(2).strip()
                task_id = match.group(3).strip()
                created_at = match.group(4)
                updated_at = match.group(5)
                conclusion = match.group(6)

                if not created_at and updated_at:
                    created_at = updated_at

                tasks.append({
                    'id': task_id,
                    'content': content_text,
                    'status': status,
                    'completed': status == 'completed',
                    'created_at': created_at if created_at else None,
                    'updated_at': updated_at if updated_at else None,
                    'conclusion': conclusion if conclusion else None
                })
        return tasks

    async def _read_todo_file(self, file_path: str, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """读取并解析任务清单文件（通过沙箱接口）"""
        sandbox = self._get_sandbox(session_id)
        if not sandbox:
            raise ValueError("Sandbox not available for _read_todo_file")

        try:
            # 使用沙箱接口读取文件
            exists = await sandbox.file_exists(file_path)
            if not exists:
                return []
            content = await sandbox.read_file(file_path)
            return self.parse_todo_list(content)
        except Exception as e:
            logger.error(f"读取任务清单失败: {e}")
            return []

    async def _save_todo_file(self, file_path: str, tasks: List[Dict[str, Any]], session_id: Optional[str] = None) -> bool:
        """保存任务清单到文件（通过沙箱接口）"""
        sandbox = self._get_sandbox(session_id)
        try:
            # 生成 Markdown 内容
            md_content = "# ToDo List\n\n"

            def _status_of(t):
                return self._normalize_status(t.get('status'))

            pending_tasks = [t for t in tasks if _status_of(t) == 'pending']
            in_progress_tasks = [t for t in tasks if _status_of(t) == 'in_progress']
            completed_tasks = [t for t in tasks if _status_of(t) == 'completed']

            def _emit(section_title: str, items: List[Dict[str, Any]], mark: str, with_conclusion: bool = False) -> str:
                if not items:
                    return ''
                buf = f"## {section_title}\n"
                for t in items:
                    line = f"- [{mark}] {t.get('content', '')} (ID: {t.get('id')})"
                    if t.get('created_at'):
                        line += f" (Created: {t.get('created_at')})"
                    if t.get('updated_at'):
                        line += f" (Updated: {t.get('updated_at')})"
                    if with_conclusion and t.get('conclusion'):
                        line += f" (Conclusion: {t.get('conclusion')})"
                    buf += line + "\n"
                return buf + "\n"

            if not tasks:
                md_content += "(No tasks yet)\n"
            else:
                md_content += _emit("Pending", pending_tasks, ' ')
                md_content += _emit("In Progress", in_progress_tasks, '-')
                md_content += _emit("Completed", completed_tasks, 'x', with_conclusion=True)
                md_content = md_content.rstrip() + "\n"

            if not sandbox:
                raise ValueError("Sandbox not available for todo_write")

            # 使用沙箱接口写入文件
            await sandbox.write_file(file_path, md_content)

            # 同步到 system_context
            await self._sync_to_system_context(tasks, session_id)

            return True
        except Exception as e:
            logger.error(f"保存任务清单失败: {e}")
            return False

    async def _sync_to_system_context(self, tasks: List[Dict[str, Any]], session_id: Optional[str] = None):
        """同步任务列表到 session_context.system_context"""
        session_context = self._get_session_context(session_id)
        if not session_context:
            logger.warning(f"Cannot sync todo list: session_context not found for session_id={session_id}")
            return

        try:
            if not hasattr(session_context, 'system_context') or not isinstance(session_context.system_context, dict):
                logger.warning("session_context.system_context is invalid")
                return

            # 更新 todo_list
            session_context.system_context['todo_list'] = tasks
            logger.info(f"Synced todo list to system_context. Tasks: {len(tasks)}")
        except Exception as e:
            logger.warning(f"Failed to sync todo list to system_context: {e}")



    @tool(
        description_i18n={
            "zh": (
                "创建或更新任务清单。任务三态：pending(待办)/in_progress(进行中)/completed(已完成)。"
                "开始执行某条任务时，先把它的 status 标为 in_progress；执行完成后再改为 completed 并补充 conclusion。"
                "**增量更新原则**：每次调用本工具时，tasks 数组里只放本次需要新增或需要修改的任务条目，未发生变化的任务严禁再次传入；"
                "更新一条任务时，只填 id 加上真正变更的字段（如只改状态就只传 id+status，只补结论就只传 id+conclusion），不要把未变化字段也带上。"
                "新增任务必须包含 id 与 content；id 只要在本会话内唯一即可（推荐短小可读，例如 t1/t2 或语义化短串）。"
                "颗粒度要求：子任务的数量必须与任务真实复杂度匹配，不要为了\"看起来简洁\"硬把多步骤合并成一条。"
                "极简单/单步任务 1-3 条；常规多步任务 5-15 条；复杂、跨模块、跨阶段（全栈功能 / 调研+设计+实现+联调+验收 / 大型重构等）"
                "可以拆到 15-40 条甚至更多，关键看每一步是否可独立验收。"
                "如果一条 content 里包含\"并且/然后/接着\"等隐含多步动作，或预计需要多次工具调用 / 跨多个文件，就必须继续拆分；"
                "只有当两个动作真的属于同一个原子动作时才合并。"
            ),
            "en": (
                "Create or update the todo list. Three states: pending / in_progress / completed. "
                "Mark a task in_progress BEFORE you start working on it; mark it completed (with a conclusion) when done. "
                "**Incremental update rule**: each call must only include tasks that are NEW or that actually CHANGE. Never resend unchanged tasks. "
                "When updating a task, send only its id plus the fields that truly change (e.g. id+status to flip status, id+conclusion to add a conclusion). Do not echo unchanged fields. "
                "New tasks must include id and content; the id only needs to be unique within this session (short and readable, e.g. t1/t2 or a semantic slug). "
                "Granularity rule: the number of subtasks MUST match the real complexity of the task. Do NOT collapse multiple steps into one just to keep the list short. "
                "Trivial/single-step task: 1-3 items. Normal multi-step task: 5-15 items. "
                "Complex, cross-module, multi-stage tasks (full-stack feature, research + design + implementation + integration + verification, large refactor, etc.) can legitimately reach 15-40 items or more, as long as each step is independently verifiable. "
                "If a single content describes multiple actions (\"and/then/after that\"), or is expected to need multiple tool calls / changes across multiple files, split it further. Only merge when two actions truly form one atomic action."
            ),
        },
        param_description_i18n={
            "tasks": {
                "zh": (
                    "任务列表。**只放本次新增或需要变更的任务**，未变化的任务严禁再次传入。"
                    "更新任务时只填 id 加真正变更的字段（id+status 切换状态，id+conclusion 补结论）。"
                    "新增任务必须包含 id, content；status 取值 pending / in_progress / completed，缺省为 pending；"
                    "开始执行前先标 in_progress，结束后再标 completed。"
                    "颗粒度要按任务复杂度自适应：极简单 1-3 条 / 常规 5-15 条 / 复杂多阶段 15-40+ 条；"
                    "禁止为了\"清单短\"把可独立验收的多步骤合并成一条。"
                ),
                "en": (
                    "List of tasks. **Only include tasks that are new or actually changing in this call**; never resend unchanged tasks. "
                    "When updating, send only id plus the truly changed fields (id+status to flip state, id+conclusion to add a conclusion). "
                    "New tasks must include id and content. status is one of pending / in_progress / completed, default pending; "
                    "mark in_progress before you start, completed when done. "
                    "Granularity must match task complexity: trivial 1-3 / normal 5-15 / complex multi-stage 15-40+ items; "
                    "never merge independently verifiable steps into one just to make the list shorter."
                )
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
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                            "description": "Task status. Use 'pending' (not started), 'in_progress' (mark this BEFORE you start working on it), or 'completed' (done). Default 'pending' for new tasks. For an update call, only include this field if the status actually changes."
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
    async def todo_write(self, tasks: List[Dict[str, Any]], session_id: str) -> str:
        """
        创建或更新任务清单。
        如果任务ID已存在，则更新该任务；如果不存在，则添加新任务。

        Args:
            tasks: 任务列表，例如 [{'id': '1', 'content': '任务内容', 'completed': False}]
            session_id: 会话ID（必填）
        """
        logger.debug(f"ToDoTool: todo_write called. session_id={session_id}")

        file_path = self._get_todo_path(session_id)
        current_tasks = await self._read_todo_file(file_path, session_id)

        # 建立索引以便更新
        task_map = {str(t.get('id')): t for t in current_tasks}

        updated_count = 0
        added_count = 0

        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        for new_task in tasks:
            task_id = str(new_task.get('id'))
            if not task_id:
                continue

            # 入参中不再支持 completed 字段，统一忽略，避免与 status 冲突
            new_task.pop('completed', None)

            # 仅当显式提供 status 时才归一化（未提供则保留旧值，实现「只传变更字段」）
            if 'status' in new_task:
                new_task['status'] = self._normalize_status(new_task.get('status'))

            new_task['updated_at'] = now_str

            if task_id in task_map:
                # 更新 - 保留原有的 created_at
                existing_task = task_map[task_id]
                new_task['created_at'] = existing_task.get('created_at', now_str)

                # 如果新的 content 为空但原有任务有 content，保留原有 content
                if ('content' not in new_task or not new_task['content']) and existing_task.get('content'):
                    new_task['content'] = existing_task['content']

                # 如果 content 仍为空但有 conclusion，使用 conclusion 作为 content
                if ('content' not in new_task or not new_task['content']) and 'conclusion' in new_task:
                    new_task['content'] = new_task['conclusion']

                task_map[task_id].update(new_task)
                updated_count += 1
            else:
                # 新增 - 设置 created_at 为当前时间
                # 使用微秒级时间戳确保唯一性
                created_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
                new_task['created_at'] = created_at

                # 如果没有 content 但有 conclusion，使用 conclusion 作为 content
                if ('content' not in new_task or not new_task['content']) and 'conclusion' in new_task:
                    new_task['content'] = new_task['conclusion']

                if 'content' not in new_task or not new_task['content']:
                     logger.warning(f"ToDoTool: New task {task_id} missing content. Skipping.", session_id=session_id)
                     continue

                task_map[task_id] = new_task
                added_count += 1

        # 转换回列表，对每条任务的 status 做归一化，缺省补 pending；保留 completed 派生字段供下游
        final_tasks = list(task_map.values())
        for t in final_tasks:
            normalized = self._normalize_status(t.get('status'))
            t['status'] = normalized
            t['completed'] = (normalized == 'completed')

        # 「未完成」= status != 'completed'（pending + in_progress 都算未完成）
        pending_tasks = [t for t in final_tasks if t.get('status') != 'completed']

        # 构建任务列表（用于返回）- 按 created_at 排序（如果没有 created_at 则使用 updated_at）
        def get_sort_key(task):
            # 优先使用 created_at，如果没有则使用 updated_at，如果都没有则返回空字符串
            return task.get('created_at') or task.get('updated_at') or ''

        sorted_tasks = sorted(final_tasks, key=get_sort_key)
        task_list = []
        for idx, t in enumerate(sorted_tasks, start=1):
            content = t.get('content', '')
            # 如果 content 为空，尝试使用 conclusion 或其他字段
            if not content:
                content = t.get('conclusion', '')
            if not content:
                content = t.get('title', '')
            if not content:
                content = f"任务 {t.get('id', idx)}"
                logger.warning(f"ToDoTool: Task {t.get('id')} has empty content, using default name.", session_id=session_id)

            task_list.append({
                "index": idx,
                "id": str(t.get('id', '')),
                "name": content,
                "status": t.get('status') or ('completed' if t.get('completed', False) else 'pending')
            })

        logger.debug(f"ToDoTool: Checking deletion condition - pending_tasks: {len(pending_tasks)}, final_tasks: {len(final_tasks)}, file_path: {file_path}", session_id=session_id)

        sandbox = self._get_sandbox(session_id)

        if not pending_tasks and final_tasks:
            # 所有任务都已完成，删除 todo 文件
            try:
                if sandbox:
                    exists = await sandbox.file_exists(file_path)
                    logger.debug(f"ToDoTool: Attempting to delete file: {file_path}, exists: {exists}", session_id=session_id)
                    if exists:
                        await sandbox.delete_file(file_path)
                        logger.info(f"ToDoTool: All tasks completed. Deleted todo file: {file_path}", session_id=session_id)
                        # 同步空列表到 system_context（文件已删除）
                        await self._sync_to_system_context([], session_id)
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

        if await self._save_todo_file(file_path, final_tasks, session_id):
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

    async def clean_old_tasks(self, session_id: Optional[str] = None, time_threshold: int = 300):
        """
        清理过期的任务（超过5分钟未更新的任务）
        如果清理后任务为空，删除 todo 文件
        同时清理 workspace 下其他 session 的过期 todo 文件

        Args:
            session_id: 会话ID
            time_threshold: 过期时间阈值（秒）
        """
        # 1. 清理当前 session 的 todo 文件
        file_path = self._get_todo_path(session_id)
        tasks = await self._read_todo_file(file_path, session_id)

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

        sandbox = self._get_sandbox(session_id)

        if has_changes:
            if not filtered_tasks:
                # 清理后为空，删除文件
                try:
                    if not sandbox:
                        raise ValueError("Sandbox not available for clean_old_tasks")
                    exists = await sandbox.file_exists(file_path)
                    if exists:
                        await sandbox.delete_file(file_path)
                        logger.info(f"已清理所有过期任务，删除空 todo 文件: {file_path}", session_id=session_id)
                        # 同步空列表到 system_context
                        await self._sync_to_system_context([], session_id)
                except Exception as e:
                    logger.error(f"删除空 todo 文件失败: {e}", session_id=session_id)
            else:
                # 保存过滤后的任务列表回文件（_save_todo_file 内部会同步到 system_context）
                await self._save_todo_file(file_path, filtered_tasks, session_id)
                logger.debug(f"已清理过期任务，剩余 {len(filtered_tasks)} 个任务", session_id=session_id)

        # 2. 清理 workspace 下其他 session 的过期 todo 文件
        await self._clean_other_session_todo_files(session_id, time_threshold)

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
    async def todo_read(self, session_id: str) -> str:
        """
        读取并显示当前未完成的任务。

        Args:
            session_id: 会话ID（必填）
        """
        file_path = self._get_todo_path(session_id)
        tasks = await self._read_todo_file(file_path, session_id)

        # 同步到 system_context
        await self._sync_to_system_context(tasks, session_id)

        unfinished = [t for t in tasks if self._normalize_status(t.get('status')) != 'completed']

        if not unfinished:
            return "当前没有未完成的任务。"

        result = "当前未完成任务清单:\n"
        for t in unfinished:
            status = self._normalize_status(t.get('status'))
            tag = "[进行中]" if status == 'in_progress' else "[待办]"
            result += f"- {tag} {t.get('content')} (ID: {t.get('id')})"
            if t.get('conclusion'):
                result += f" [结论: {t.get('conclusion')}]"
            result += "\n"

        return result
