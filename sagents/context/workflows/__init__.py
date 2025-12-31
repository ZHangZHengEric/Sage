"""工作流管理模块

这个模块提供了标准化的工作流管理功能，包括：
- WorkflowStep: 工作流步骤数据类
- Workflow: 工作流数据类
- WorkflowManager: 工作流管理器
- WorkflowFormat: 工作流格式枚举

支持新旧两种工作流格式的自动检测和转换。
"""

from .workflow import WorkflowStep, Workflow, WorkflowFormat
from .workflow_manager import WorkflowManager

__all__ = [
    'WorkflowFormat',
    'WorkflowStep', 
    'Workflow',
    'WorkflowManager'
]

# 版本信息
__version__ = '1.0.0'

# 模块级别的便捷函数
def create_workflow_manager() -> WorkflowManager:
    """创建工作流管理器实例"""
    return WorkflowManager()

def create_workflow(name: str, description: str = "") -> Workflow:
    """创建工作流实例"""
    return Workflow(name=name, description=description)

def create_workflow_step(id: str, name: str, description: str, order: int = 0) -> WorkflowStep:
    """创建工作流步骤实例"""
    return WorkflowStep(id=id, name=name, description=description, order=order)