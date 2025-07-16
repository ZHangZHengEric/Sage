"""
任务完成工具
"""
from typing import Dict, Any
from .tool_base import ToolBase, ToolSpec

class TaskCompletionTool(ToolBase):
    """任务完成工具"""
    
    def __init__(self):
        super().__init__()

    @ToolBase.tool()
    def complete_task(self) -> Dict[str, Any]:
        """
        当用户的请求或者任务完成时，调用此工具来标记任务完成状态。
        
        Returns:
            Dict[str, Any]: 包含状态信息的字典
        """
        return {
            "status": "success",
            "message": "任务已完成",
            "result": None
        }