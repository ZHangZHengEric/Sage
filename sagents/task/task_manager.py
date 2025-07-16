from typing import Dict, List, Optional, Any, Tuple
import json
import datetime
from .task_base import TaskBase

class TaskManager:
    """
    任务管理器
    
    负责管理多个任务的生命周期，包括创建、更新、状态查询、依赖管理等。
    支持任务进度统计和结果索引功能。
    """
    
    def __init__(self, session_id: Optional[str] = None):
        """
        初始化任务管理器
        
        Args:
            session_id: 会话ID，用于标识任务管理器实例
        """
        self.session_id = session_id
        self.tasks: Dict[str, TaskBase] = {}
        self.task_history: List[Dict[str, Any]] = []
        self.created_time = datetime.datetime.now().isoformat()
        self.next_task_number = 1  # 用于生成顺序的task_id

    def add_task(self, task: TaskBase) -> str:
        """
        添加新任务并返回任务ID
        
        Args:
            task: 要添加的任务对象
            
        Returns:
            str: 任务ID
        """
        # 强制使用顺序编号作为task_id，覆盖TaskBase可能生成的UUID
        task.task_id = str(self.next_task_number)
        self.next_task_number += 1
        
        # 检查ID冲突（理论上不会发生，但保险起见）
        while task.task_id in self.tasks:
            task.task_id = str(self.next_task_number)
            self.next_task_number += 1
        
        # 更新title以反映新的task_id
        if not task.title or task.title.startswith("Task "):
            task.title = f"Task {task.task_id}"
        
        self.tasks[task.task_id] = task
        self._add_history_entry(task.task_id, 'added', {
            'task': task.to_summary_dict()
        })
        
        return task.task_id

    def add_tasks_batch(self, tasks: List[TaskBase]) -> List[str]:
        """
        批量添加任务
        
        Args:
            tasks: 任务列表
            
        Returns:
            List[str]: 任务ID列表
        """
        task_ids = []
        for task in tasks:
            task_id = self.add_task(task)
            task_ids.append(task_id)
        
        self._add_history_entry("batch", 'batch_added', {
            'count': len(tasks),
            'task_ids': task_ids
        })
        
        return task_ids

    def get_task(self, task_id: str) -> Optional[TaskBase]:
        """
        根据ID获取任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            Optional[TaskBase]: 任务对象，不存在则返回None
        """
        return self.tasks.get(task_id)

    def update_task(self, task_id: str, **kwargs) -> bool:
        """
        更新任务属性
        
        Args:
            task_id: 任务ID
            **kwargs: 要更新的属性
            
        Returns:
            bool: 更新是否成功
        """
        if task_id not in self.tasks:
            return False
        
        task = self.tasks[task_id]
        updated_fields = {}
        
        for key, value in kwargs.items():
            if hasattr(task, key):
                old_value = getattr(task, key)
                setattr(task, key, value)
                updated_fields[key] = {'old': old_value, 'new': value}
        
        if updated_fields:
            self._add_history_entry(task_id, 'updated', {
                'changes': updated_fields
            })
        
        return True

    def update_task_status(self, task_id: str, status) -> bool:
        """
        更新任务状态
        
        Args:
            task_id: 任务ID
            status: 新的任务状态（TaskStatus枚举）
            
        Returns:
            bool: 更新是否成功
        """
        if task_id not in self.tasks:
            return False
        
        task = self.tasks[task_id]
        old_status = task.status
        task.status = status
        
        self._add_history_entry(task_id, 'status_updated', {
            'old_status': old_status.value if hasattr(old_status, 'value') else str(old_status),
            'new_status': status.value if hasattr(status, 'value') else str(status)
        })
        
        return True

    def start_task(self, task_id: str, assigned_to: str = None) -> bool:
        """
        开始执行任务
        
        Args:
            task_id: 任务ID
            assigned_to: 执行者名称
            
        Returns:
            bool: 操作是否成功
        """
        task = self.get_task(task_id)
        if not task:
            return False
        
        task.start_execution(assigned_to)
        self._add_history_entry(task_id, 'started', {
            'assigned_to': assigned_to,
            'start_time': task.start_time
        })
        
        return True

    def complete_task(self, task_id: str, result: Any = None, 
                     execution_details: Dict[str, Any] = None) -> bool:
        """
        完成任务执行
        
        Args:
            task_id: 任务ID
            result: 执行结果
            execution_details: 执行详情
            
        Returns:
            bool: 操作是否成功
        """
        task = self.get_task(task_id)
        if not task:
            return False
        
        task.complete_execution(result, execution_details)
        self._add_history_entry(task_id, 'completed', {
            'result_type': type(result).__name__ if result else None,
            'end_time': task.end_time,
            'duration': task.get_execution_duration()
        })
        
        return True

    def fail_task(self, task_id: str, error_message: str, 
                 execution_details: Dict[str, Any] = None) -> bool:
        """
        标记任务失败
        
        Args:
            task_id: 任务ID
            error_message: 错误信息
            execution_details: 执行详情
            
        Returns:
            bool: 操作是否成功
        """
        task = self.get_task(task_id)
        if not task:
            return False
        
        task.fail_execution(error_message, execution_details)
        self._add_history_entry(task_id, 'failed', {
            'error': error_message,
            'end_time': task.end_time
        })
        
        return True

    def get_tasks_by_status(self, status) -> List[TaskBase]:
        """
        根据状态获取任务列表
        
        Args:
            status: 任务状态，可以是字符串或TaskStatus枚举
            
        Returns:
            List[TaskBase]: 匹配状态的任务列表
        """
        from .task_base import TaskStatus
        
        # 处理不同类型的status参数
        if isinstance(status, str):
            # 如果是字符串，尝试转换为枚举
            try:
                target_status = TaskStatus(status)
            except ValueError:
                target_status = status
        else:
            target_status = status
        
        return [task for task in self.tasks.values() if task.status == target_status]

    def get_ready_tasks(self) -> List[TaskBase]:
        """
        获取可以开始执行的任务（依赖已完成）
        
        Returns:
            List[TaskBase]: 可执行任务列表
        """
        from .task_base import TaskStatus
        completed_task_ids = set(task.task_id for task in self.tasks.values() 
                                if task.status == TaskStatus.COMPLETED)
        
        ready_tasks = []
        for task in self.tasks.values():
            # 检查任务是否处于待执行状态且依赖已满足
            if (task.status == TaskStatus.PENDING and 
                set(task.dependencies).issubset(completed_task_ids)):
                ready_tasks.append(task)
        
        # 按优先级排序
        ready_tasks.sort(key=lambda x: x.priority.value if hasattr(x.priority, 'value') else x.priority, reverse=True)
        return ready_tasks

    def get_next_task(self) -> Optional[TaskBase]:
        """
        获取下一个应该执行的任务
        
        Returns:
            Optional[TaskBase]: 下一个任务，没有则返回None
        """
        ready_tasks = self.get_ready_tasks()
        return ready_tasks[0] if ready_tasks else None

    def get_progress_stats(self) -> Dict[str, Any]:
        """
        获取整体进度统计
        
        Returns:
            Dict[str, Any]: 进度统计信息
        """
        total_tasks = len(self.tasks)
        if total_tasks == 0:
            return {
                'total_tasks': 0,
                'completed_tasks': 0,
                'failed_tasks': 0,
                'in_progress_tasks': 0,
                'pending_tasks': 0,
                'completion_rate': 0.0,
                'success_rate': 0.0
            }
        
        from .task_base import TaskStatus
        status_counts = {}
        for task in self.tasks.values():
            status_counts[task.status] = status_counts.get(task.status, 0) + 1
        
        completed = status_counts.get(TaskStatus.COMPLETED, 0)
        failed = status_counts.get(TaskStatus.FAILED, 0)
        in_progress = status_counts.get(TaskStatus.IN_PROGRESS, 0)
        pending = status_counts.get(TaskStatus.PENDING, 0)
        finished_tasks = completed + failed
        
        return {
            'total_tasks': total_tasks,
            'completed_tasks': completed,
            'failed_tasks': failed,
            'in_progress_tasks': in_progress,
            'pending_tasks': pending,
            'completion_rate': (finished_tasks / total_tasks) * 100,
            'success_rate': (completed / max(finished_tasks, 1)) * 100,
            'status_breakdown': status_counts
        }

    def get_task_dependencies_graph(self) -> Dict[str, List[str]]:
        """
        获取任务依赖关系图
        
        Returns:
            Dict[str, List[str]]: 任务依赖图 {task_id: [dependent_task_ids]}
        """
        dependency_graph = {}
        for task in self.tasks.values():
            dependency_graph[task.task_id] = task.dependencies.copy()
        return dependency_graph

    def get_execution_summary(self) -> Dict[str, Any]:
        """
        获取执行摘要（用于减少token使用）
        
        Returns:
            Dict[str, Any]: 执行摘要
        """
        from .task_base import TaskStatus
        completed_tasks = self.get_tasks_by_status(TaskStatus.COMPLETED)
        failed_tasks = self.get_tasks_by_status(TaskStatus.FAILED)
        in_progress_tasks = self.get_tasks_by_status(TaskStatus.IN_PROGRESS)
        
        # 收集关键执行信息
        total_files_created = 0
        total_tools_used = set()
        total_tokens_used = 0
        key_results = []
        
        for task in completed_tasks + failed_tasks:
            if task.execution_details:
                total_files_created += len(task.execution_details.get('output_files', []))
                tool_calls = task.execution_details.get('tool_calls', [])
                if isinstance(tool_calls, list):
                    for tool_call in tool_calls:
                        if isinstance(tool_call, dict):
                            total_tools_used.add(tool_call.get('tool_name', 'unknown'))
                        else:
                            total_tools_used.add(str(tool_call))
                
                # 统计token使用量
                metrics = task.execution_details.get('metrics', {})
                if isinstance(metrics, dict):
                    total_tokens_used += metrics.get('tokens_used', 0)
                
                if task.result:
                    key_results.append({
                        'task_id': task.task_id,
                        'description': task.description[:100],
                        'result_type': type(task.result).__name__
                    })
        
        return {
            'session_id': self.session_id,
            'progress': self.get_progress_stats(),
            'execution_metrics': {
                'total_files_created': total_files_created,
                'tools_used': list(total_tools_used),
                'tools_count': len(total_tools_used),
                'total_tokens_used': total_tokens_used
            },
            'performance_metrics': {
                'total_tokens_used': total_tokens_used,
                'average_tokens_per_task': total_tokens_used / max(len(completed_tasks + failed_tasks), 1)
            },
            'current_status': {
                'in_progress_count': len(in_progress_tasks),
                'failed_count': len(failed_tasks),
                'next_task_ready': self.get_next_task() is not None
            },
            'failed_tasks': [task.to_summary_dict() for task in failed_tasks],
            'key_results': key_results[:5],  # 只保留前5个关键结果
            'last_updated': datetime.datetime.now().isoformat()
        }

    def get_tasks_summary_for_agent(self, agent_name: str) -> Dict[str, Any]:
        """
        为特定Agent获取相关任务摘要
        
        Args:
            agent_name: Agent名称
            
        Returns:
            Dict[str, Any]: 相关任务摘要
        """
        # 获取分配给该Agent的任务
        assigned_tasks = [task for task in self.tasks.values() 
                         if task.assigned_to == agent_name]
        
        # 获取该Agent可能感兴趣的任务（基于类型匹配）
        relevant_statuses = ['pending', 'in_progress', 'completed']
        relevant_tasks = [task for task in self.tasks.values() 
                         if task.status in relevant_statuses]
        
        return {
            'agent_name': agent_name,
            'assigned_tasks': [task.to_summary_dict() for task in assigned_tasks],
            'relevant_tasks': [task.to_summary_dict() for task in relevant_tasks[-10:]],  # 最近10个
            'next_available_task': self.get_next_task().to_summary_dict() if self.get_next_task() else None
        }

    def get_all_tasks(self) -> List[TaskBase]:
        """
        获取所有任务的列表（按task_id顺序排序）
        
        Returns:
            List[TaskBase]: 任务对象列表，按task_id数字顺序排序
        """
        # 按task_id的数字值排序
        sorted_tasks = sorted(self.tasks.values(), key=lambda task: int(task.task_id) if task.task_id.isdigit() else float('inf'))
        return sorted_tasks

    def get_task_history(self) -> List[Dict[str, Any]]:
        """获取完整任务历史"""
        return self.task_history

    def clear_completed_tasks(self) -> int:
        """
        清理已完成的任务（保留摘要）
        
        Returns:
            int: 清理的任务数量
        """
        completed_tasks = self.get_tasks_by_status('completed')
        cleared_count = 0
        
        for task in completed_tasks:
            # 保存摘要到历史
            self._add_history_entry(task.task_id, 'archived', {
                'summary': task.to_summary_dict(),
                'archived_time': datetime.datetime.now().isoformat()
            })
            
            # 从活跃任务中移除
            del self.tasks[task.task_id]
            cleared_count += 1
        
        return cleared_count

    def to_dict(self) -> Dict[str, Any]:
        """
        将TaskManager转换为字典格式
        
        Returns:
            Dict[str, Any]: 包含TaskManager状态的字典
        """
        return {
            'session_id': self.session_id,
            'created_time': self.created_time,
            'next_task_number': self.next_task_number,
            'tasks': {task_id: task.to_dict() for task_id, task in self.tasks.items()},
            'task_history': self.task_history
        }

    def to_json(self) -> str:
        """序列化为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def save_to_file(self, file_path: str) -> bool:
        """
        保存到文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 保存是否成功
        """
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(self.to_json())
            return True
        except Exception as e:
            print(f"保存任务管理器失败: {e}")
            return False

    @classmethod
    def from_json(cls, json_str: str) -> 'TaskManager':
        """从JSON字符串创建任务管理器"""
        data = json.loads(json_str)
        manager = cls(session_id=data.get('session_id'))
        manager.created_time = data.get('created_time', manager.created_time)
        manager.next_task_number = data.get('next_task_number', 1)
        manager.task_history = data.get('task_history', [])
        
        # 重建任务对象
        tasks_data = data.get('tasks', {})
        for task_id, task_data in tasks_data.items():
            task = TaskBase.from_dict(task_data)
            manager.tasks[task_id] = task
        
        return manager

    @classmethod
    def load_from_file(cls, file_path: str) -> Optional['TaskManager']:
        """
        从文件加载任务管理器
        
        Args:
            file_path: 文件路径
            
        Returns:
            Optional[TaskManager]: 任务管理器对象，失败则返回None
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                json_str = f.read()
            return cls.from_json(json_str)
        except Exception as e:
            print(f"加载任务管理器失败: {e}")
            return None

    def _add_history_entry(self, task_id: str, action: str, details: Dict[str, Any]) -> None:
        """添加历史记录条目"""
        entry = {
            'timestamp': datetime.datetime.now().isoformat(),
            'task_id': task_id,
            'action': action,
            'details': details
        }
        self.task_history.append(entry)

    def get_status_description(self) -> str:
        """
        获取任务管理器的简化状态描述字符串
        
        Returns:
            str: 格式化的状态描述字符串，包含所有任务的基本信息
        """
        try:
            # 获取所有任务
            all_tasks = self.get_all_tasks()
            if not all_tasks:
                return "任务管理器中暂无任务"
            
            # 构建简化的状态描述
            status_lines = [f"任务管理器包含 {len(all_tasks)} 个任务："]
            
            for task in all_tasks:
                status_info = f"- 任务ID: {task.task_id}, 描述: {task.description}, 状态: {task.status.value}"
                status_lines.append(status_info)
            
            return "\n".join(status_lines)
            
        except Exception as e:
            return f"任务管理器状态获取失败: {str(e)}"

    def get_compact_status_description(self) -> str:
        """
        获取任务管理器的紧凑状态描述字符串（用于简短展示）
        
        Returns:
            str: 紧凑格式的状态描述字符串
        """
        try:
            all_tasks = self.get_all_tasks()
            if not all_tasks:
                return "暂无任务"
            
            stats = self.get_progress_stats()
            
            # 构建紧凑描述
            status_info = f"任务总数: {stats['total_tasks']} | "
            status_info += f"已完成: {stats['completed_tasks']} | "
            status_info += f"进行中: {stats['in_progress_tasks']} | "
            status_info += f"待执行: {stats['pending_tasks']}"
            
            if stats['failed_tasks'] > 0:
                status_info += f" | 失败: {stats['failed_tasks']}"
            
            status_info += f" | 完成率: {stats['completion_rate']:.1f}%"
            
            # 添加当前活动任务信息
            in_progress_tasks = self.get_tasks_by_status('in_progress')
            if in_progress_tasks:
                current_task = in_progress_tasks[0]  # 假设只有一个任务在执行
                status_info += f" | 当前执行: {current_task.task_id}"
            
            return status_info
            
        except Exception as e:
            return f"状态获取失败: {str(e)}"

    def get_task_status_by_id(self, task_id: str) -> str:
        """
        获取指定任务的详细状态描述
        
        Args:
            task_id: 任务ID
            
        Returns:
            str: 任务的详细状态描述
        """
        task = self.get_task(task_id)
        if not task:
            return f"任务ID {task_id} 不存在"
        
        try:
            status_info = f"任务 {task.task_id} 详细信息：\n"
            status_info += f"- 标题: {task.title}\n"
            status_info += f"- 描述: {task.description}\n"
            status_info += f"- 状态: {task.status.value}\n"
            status_info += f"- 优先级: {task.priority.value}\n"
            status_info += f"- 类型: {task.type}\n"
            
            if task.dependencies:
                status_info += f"- 依赖任务: {', '.join(task.dependencies)}\n"
            
            if task.assigned_to:
                status_info += f"- 执行者: {task.assigned_to}\n"
            
            if task.estimated_duration:
                status_info += f"- 预计时长: {task.estimated_duration}秒\n"
            
            # 时间信息
            status_info += f"- 创建时间: {task.created_time}\n"
            if task.start_time:
                status_info += f"- 开始时间: {task.start_time}\n"
            if task.end_time:
                status_info += f"- 结束时间: {task.end_time}\n"
                duration = task.get_execution_duration()
                if duration:
                    status_info += f"- 执行耗时: {duration:.2f}秒\n"
            
            # 执行详情
            if task.execution_details:
                details = task.execution_details
                if details.get('tool_calls'):
                    status_info += f"- 工具调用次数: {len(details['tool_calls'])}\n"
                if details.get('output_files'):
                    status_info += f"- 生成文件数: {len(details['output_files'])}\n"
                if details.get('errors'):
                    status_info += f"- 错误数: {len(details['errors'])}\n"
                if details.get('warnings'):
                    status_info += f"- 警告数: {len(details['warnings'])}\n"
            
            # 结果信息
            if task.result:
                result_type = type(task.result).__name__
                status_info += f"- 执行结果类型: {result_type}\n"
            
            return status_info.rstrip()
            
        except Exception as e:
            return f"获取任务 {task_id} 状态失败: {str(e)}"

    def __repr__(self) -> str:
        """字符串表示"""
        stats = self.get_progress_stats()
        return f"TaskManager(session={self.session_id}, tasks={stats['total_tasks']}, completed={stats['completed_tasks']})"
