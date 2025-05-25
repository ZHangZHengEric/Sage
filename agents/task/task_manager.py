from typing import Dict, List, Optional
from .task_base import TaskBase

class TaskManager:
    def __init__(self):
        self.tasks: Dict[str, TaskBase] = {}
        self.task_history: List[Dict[str, Any]] = []

    def add_task(self, task: TaskBase) -> str:
        """Add a new task and return its ID"""
        task_id = f"task_{len(self.tasks) + 1}"
        self.tasks[task_id] = task
        self.task_history.append({
            'task_id': task_id,
            'action': 'added',
            'task': task.to_dict()
        })
        return task_id

    def get_task(self, task_id: str) -> Optional[TaskBase]:
        """Get a task by ID"""
        return self.tasks.get(task_id)

    def update_task(self, task_id: str, **kwargs) -> bool:
        """Update task properties"""
        if task_id not in self.tasks:
            return False
        
        task = self.tasks[task_id]
        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)
        
        self.task_history.append({
            'task_id': task_id,
            'action': 'updated',
            'changes': kwargs
        })
        return True

    def get_all_tasks(self) -> Dict[str, TaskBase]:
        """Get all tasks"""
        return self.tasks

    def get_task_history(self) -> List[Dict[str, Any]]:
        """Get complete task history"""
        return self.task_history
