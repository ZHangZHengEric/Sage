from typing import Dict, Any, List, Optional

class TaskBase:
    def __init__(self, description: str, 
                 task_type: str = "normal",
                 status: str = "pending",
                 dependencies: Optional[List[str]] = None,
                 result: Optional[Any] = None):
        self.description = description
        self.type = task_type  # normal or thinking
        self.status = status  # pending, in_progress, completed, failed
        self.dependencies = dependencies or []
        self.result = result

    def to_dict(self) -> Dict[str, Any]:
        return {
            'description': self.description,
            'type': self.type,
            'status': self.status,
            'dependencies': self.dependencies,
            'result': self.result
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TaskBase':
        return cls(
            description=data['description'],
            task_type=data.get('type', 'normal'),
            status=data.get('status', 'pending'),
            dependencies=data.get('dependencies', []),
            result=data.get('result')
        )
