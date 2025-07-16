from typing import Dict, Any, List, Optional
from enum import Enum
import datetime
import uuid


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskPriority(Enum):
    """任务优先级枚举"""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class TaskBase:
    def __init__(self, description: str = None,
                 task_id: Optional[str] = None,
                 title: Optional[str] = None,
                 task_type: str = "normal",
                 status = None,
                 dependencies: Optional[List[str]] = None,
                 result: Optional[Any] = None,
                 priority = None,
                 estimated_duration: Optional[int] = None,
                 created_time: Optional[str] = None,
                 start_time: Optional[str] = None,
                 end_time: Optional[str] = None,
                 assigned_to: Optional[str] = None,
                 execution_details: Optional[Dict[str, Any]] = None,
                 execution_summary: Optional[Dict[str, Any]] = None,
                 summary_generated_at: Optional[str] = None):
        """
        初始化任务对象
        
        Args:
            description: 任务描述
            task_id: 任务唯一标识符，如果为None则自动生成
            title: 任务标题(简短描述)
            task_type: 任务类型 (normal, thinking, critical)
            status: 任务状态，可以是TaskStatus枚举或字符串
            dependencies: 依赖的任务ID列表
            result: 任务执行结果
            priority: 任务优先级，可以是TaskPriority枚举或整数
            estimated_duration: 预估执行时间(秒)
            created_time: 创建时间
            start_time: 开始执行时间
            end_time: 完成时间
            assigned_to: 负责执行的Agent名称
            execution_details: 执行详情，包含工具调用、文件输出等
            execution_summary: 任务执行总结
            summary_generated_at: 总结生成时间
        """
        # 基础字段
        self.task_id = task_id or str(uuid.uuid4())
        self.title = title or f"Task {self.task_id[:8]}"
        self.description = description or self.title
        self.type = task_type
        self.dependencies = dependencies or []
        self.result = result
        
        # 处理状态 - 支持枚举和字符串
        if status is None:
            self.status = TaskStatus.PENDING
        elif isinstance(status, TaskStatus):
            self.status = status
        else:
            # 尝试从字符串转换
            try:
                self.status = TaskStatus(status)
            except ValueError:
                self.status = TaskStatus.PENDING
        
        # 处理优先级 - 支持枚举和整数
        if priority is None:
            self.priority = TaskPriority.MEDIUM
        elif isinstance(priority, TaskPriority):
            self.priority = priority
        elif isinstance(priority, int):
            # 从整数转换为枚举
            if priority <= 1:
                self.priority = TaskPriority.LOW
            elif priority == 2:
                self.priority = TaskPriority.MEDIUM
            elif priority == 3:
                self.priority = TaskPriority.HIGH
            else:
                self.priority = TaskPriority.CRITICAL
        else:
            self.priority = TaskPriority.MEDIUM
        
        # 时间字段
        self.estimated_duration = estimated_duration
        self.created_time = created_time or datetime.datetime.now().isoformat()
        self.start_time = start_time
        self.end_time = end_time
        self.assigned_to = assigned_to
        
        # 执行详情结构化存储
        self.execution_details = execution_details or {
            'tool_calls': [],           # 调用的工具列表
            'output_files': [],         # 生成的文件路径列表
            'key_data': {},            # 关键数据和中间结果
            'errors': [],              # 执行过程中的错误
            'warnings': [],            # 警告信息
            'execution_log': [],       # 详细执行日志
            'metrics': {}              # 执行指标(耗时、token使用等)
        }
        
        # 执行总结字段
        self.execution_summary = execution_summary or {
            'result_documents': [],     # 执行过程中生成的文档路径列表
            'result_summary': ''        # 详细的任务执行结果总结文字
        }
        self.summary_generated_at = summary_generated_at

    def start_execution(self, assigned_to: str = None) -> None:
        """开始执行任务"""
        self.status = TaskStatus.IN_PROGRESS
        self.start_time = datetime.datetime.now().isoformat()
        if assigned_to:
            self.assigned_to = assigned_to

    def complete_execution(self, result: Any = None, 
                          execution_details: Dict[str, Any] = None) -> None:
        """完成任务执行"""
        self.status = TaskStatus.COMPLETED
        self.end_time = datetime.datetime.now().isoformat()
        if result is not None:
            self.result = result
        if execution_details:
            self.update_execution_details(execution_details)

    def fail_execution(self, error_message: str, 
                      execution_details: Dict[str, Any] = None) -> None:
        """标记任务执行失败"""
        self.status = TaskStatus.FAILED
        self.end_time = datetime.datetime.now().isoformat()
        self.execution_details['errors'].append({
            'timestamp': datetime.datetime.now().isoformat(),
            'message': error_message
        })
        if execution_details:
            self.update_execution_details(execution_details)

    def update_execution_details(self, details: Dict[str, Any]) -> None:
        """更新执行详情"""
        for key, value in details.items():
            if key in self.execution_details:
                if isinstance(self.execution_details[key], list):
                    if isinstance(value, list):
                        self.execution_details[key].extend(value)
                    else:
                        self.execution_details[key].append(value)
                elif isinstance(self.execution_details[key], dict):
                    self.execution_details[key].update(value)
                else:
                    self.execution_details[key] = value

    def add_tool_call(self, tool_name: str, tool_args: Dict[str, Any], 
                     tool_result: Any = None) -> None:
        """添加工具调用记录"""
        tool_call = {
            'timestamp': datetime.datetime.now().isoformat(),
            'tool_name': tool_name,
            'arguments': tool_args,
            'result': tool_result
        }
        self.execution_details['tool_calls'].append(tool_call)

    def add_output_file(self, file_path: str, file_type: str = "unknown") -> None:
        """添加输出文件记录"""
        file_record = {
            'path': file_path,
            'type': file_type,
            'created_time': datetime.datetime.now().isoformat()
        }
        self.execution_details['output_files'].append(file_record)

    def add_log_entry(self, message: str, level: str = "info") -> None:
        """添加执行日志"""
        log_entry = {
            'timestamp': datetime.datetime.now().isoformat(),
            'level': level,
            'message': message
        }
        self.execution_details['execution_log'].append(log_entry)

    def get_execution_duration(self) -> Optional[float]:
        """获取执行耗时(秒)"""
        if self.start_time and self.end_time:
            start = datetime.datetime.fromisoformat(self.start_time)
            end = datetime.datetime.fromisoformat(self.end_time)
            return (end - start).total_seconds()
        return None

    def is_ready_to_execute(self, completed_task_ids: List[str]) -> bool:
        """检查是否可以开始执行(依赖是否已完成)"""
        if self.status != TaskStatus.PENDING:
            return False
        return all(dep_id in completed_task_ids for dep_id in self.dependencies)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'task_id': self.task_id,
            'title': self.title,
            'description': self.description,
            'type': self.type,
            'status': self.status.value if isinstance(self.status, TaskStatus) else self.status,
            'dependencies': self.dependencies,
            'result': self.result,
            'priority': self.priority.value if isinstance(self.priority, TaskPriority) else self.priority,
            'estimated_duration': self.estimated_duration,
            'created_time': self.created_time,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'assigned_to': self.assigned_to,
            'execution_details': self.execution_details,
            'execution_summary': self.execution_summary,
            'summary_generated_at': self.summary_generated_at
        }

    def to_summary_dict(self) -> Dict[str, Any]:
        """转换为摘要格式(用于减少token使用)"""
        summary = {
            'task_id': self.task_id,
            'title': self.title,
            'description': self.description,
            'status': self.status.value if isinstance(self.status, TaskStatus) else self.status,
            'assigned_to': self.assigned_to,
            'priority': self.priority.value if isinstance(self.priority, TaskPriority) else self.priority
        }
        
        # 添加关键执行信息
        if self.execution_details:
            summary['execution_summary'] = {
                'tools_used': len(self.execution_details.get('tool_calls', [])),
                'files_created': len(self.execution_details.get('output_files', [])),
                'has_errors': len(self.execution_details.get('errors', [])) > 0,
                'duration': self.get_execution_duration()
            }
        
        # 添加执行总结信息
        if self.execution_summary:
            if isinstance(self.execution_summary, dict):
                summary['has_execution_summary'] = bool(self.execution_summary.get('result_summary', '').strip())
                summary['result_documents_count'] = len(self.execution_summary.get('result_documents', []))
                summary['summary_generated_at'] = self.summary_generated_at
            else:
                summary['has_execution_summary'] = bool(str(self.execution_summary).strip())
        else:
            summary['has_execution_summary'] = False
        
        return summary

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TaskBase':
        """从字典创建任务对象"""
        return cls(
            task_id=data.get('task_id'),
            title=data.get('title'),
            description=data.get('description'),
            task_type=data.get('type', 'normal'),
            status=data.get('status'),
            dependencies=data.get('dependencies', []),
            result=data.get('result'),
            priority=data.get('priority'),
            estimated_duration=data.get('estimated_duration'),
            created_time=data.get('created_time'),
            start_time=data.get('start_time'),
            end_time=data.get('end_time'),
            assigned_to=data.get('assigned_to'),
            execution_details=data.get('execution_details'),
            execution_summary=data.get('execution_summary'),
            summary_generated_at=data.get('summary_generated_at')
        )

    def __repr__(self) -> str:
        """字符串表示"""
        return f"TaskBase(id={self.task_id[:8]}, desc='{self.description[:50]}...', status={self.status})"
