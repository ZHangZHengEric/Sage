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
        当用户的请求或者任务完成时，或者当你对用户进行询问和澄清时，或者要等待用户的下一步输入时，要调用该工具来中断会话。
        
        Returns:
            Dict[str, Any]: 包含状态信息的字典
        """
        return {
            "status": "success",
            "message": "任务已完成",
            "result": None
        }