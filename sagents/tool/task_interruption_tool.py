"""
任务完成工具
"""
from typing import Dict, Any
from .tool_base import ToolBase, ToolSpec

class TaskInterruptionTool(ToolBase):
    """任务中断工具"""
    
    def __init__(self):
        super().__init__()
    
    @ToolBase.tool()
    def ask_followup_question(self, question: str,follow_up:list['str']=None) -> Dict[str, Any]:
        """
        The ask_followup_question tool enables interactive communication by asking specific questions to gather additional information needed to complete tasks effectively.
        
        Args:
            question (str): The specific question to ask the user
            follow_up (list[str], optional):  A list of 2-4 suggested answers that help guide user responses
        
        Returns:
            Dict[str, Any]: A dictionary containing the status, message, result, and follow-up options.
        """
        return {
            "status": "ask_followup_question",
            "message": question,
            "result": None,
            "follow_up":follow_up
        }

    # @ToolBase.tool()
    def complete_task(self) -> Dict[str, Any]:
        """
        The complete_task tool is used to signal that the task has been successfully completed.
        
        Returns:
            Dict[str, Any]: A dictionary containing the status, message, and result.
        """
        return {
            "status": "success",
            "message": "Task completed successfully",
            "result": None
        }
