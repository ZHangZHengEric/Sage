from typing import Any, Dict, List, Optional, Union

from sagents.context.workflows.workflow import Workflow, WorkflowFormat, WorkflowStep
from sagents.utils.logger import logger


class WorkflowManager:
    """工作流管理器 - 负责工作流的集中管理和操作"""
    
    def __init__(self):
        self.workflows: Dict[str, Workflow] = {}
        logger.info("WorkflowManager: 初始化完成")
    
    def add_workflow(self, workflow: Workflow) -> None:
        """添加工作流"""
        self.workflows[workflow.name] = workflow
        logger.info(f"WorkflowManager: 添加工作流 '{workflow.name}'")
    
    def remove_workflow(self, name: str) -> bool:
        """移除工作流"""
        if name in self.workflows:
            del self.workflows[name]
            logger.info(f"WorkflowManager: 移除工作流 '{name}'")
            return True
        logger.warning(f"WorkflowManager: 尝试移除不存在的工作流 '{name}'")
        return False
    
    def get_workflow(self, name: str) -> Optional[Workflow]:
        """获取工作流"""
        workflow = self.workflows.get(name)
        if workflow:
            logger.debug(f"WorkflowManager: 获取工作流 '{name}' 成功")
        else:
            logger.warning(f"WorkflowManager: 工作流 '{name}' 不存在")
        return workflow
    
    def list_workflows(self) -> List[str]:
        """列出所有工作流名称"""
        workflow_names = list(self.workflows.keys())
        logger.debug(f"WorkflowManager: 当前有 {len(workflow_names)} 个工作流")
        return workflow_names
    
    def get_all_workflows(self) -> Dict[str, Workflow]:
        """获取所有工作流"""
        return self.workflows.copy()
    
    def clear_workflows(self) -> None:
        """清空所有工作流"""
        count = len(self.workflows)
        self.workflows.clear()
        logger.info(f"WorkflowManager: 已清空 {count} 个工作流")
    
    def detect_format(self, data: Any) -> WorkflowFormat:
        """检测工作流数据格式"""
        if not data:
            return WorkflowFormat.LEGACY
            
        if isinstance(data, dict):
            # 检查是否是旧格式 Dict[str, List[str]]
            first_value = next(iter(data.values()), None)
            if isinstance(first_value, list):
                return WorkflowFormat.LEGACY
            elif isinstance(first_value, dict):
                # 进一步检查是否是嵌套工作流格式
                if first_value and isinstance(next(iter(first_value.values()), {}), dict):
                    return WorkflowFormat.NESTED
        
        return WorkflowFormat.LEGACY
    
    def normalize_workflows(self, raw_workflows: Union[Dict[str, List[str]], Dict[str, Dict[str, Any]]]) -> Dict[str, Workflow]:
        """标准化工作流数据为Workflow对象"""
        if not raw_workflows:
            logger.warning("WorkflowManager: 输入的工作流数据为空")
            return {}
            
        normalized = {}
        format_type = self.detect_format(raw_workflows)
        
        logger.info(f"WorkflowManager: 检测到工作流格式: {format_type.value}")
        
        try:
            if format_type == WorkflowFormat.LEGACY:
                # 旧格式转换
                for name, steps in raw_workflows.items():
                    if isinstance(steps, list):
                        workflow = Workflow.from_legacy_format(name, steps)
                        normalized[name] = workflow
                    else:
                        logger.error(f"WorkflowManager: 工作流 '{name}' 的步骤格式不正确")
                        
            elif format_type == WorkflowFormat.NESTED:
                # 新格式转换
                for name, nested_steps in raw_workflows.items():
                    if isinstance(nested_steps, dict):
                        workflow = Workflow(name=name, format_type=WorkflowFormat.NESTED)
                        for step_id, step_data in nested_steps.items():
                            if isinstance(step_data, dict):
                                step = WorkflowStep.from_dict(step_data)
                                workflow.add_step(step)
                            else:
                                logger.error(f"WorkflowManager: 工作流 '{name}' 中步骤 '{step_id}' 格式不正确")
                        normalized[name] = workflow
                    else:
                        logger.error(f"WorkflowManager: 工作流 '{name}' 的格式不正确")
        
        except Exception as e:
            logger.error(f"WorkflowManager: 标准化工作流时发生错误: {str(e)}")
            return {}
        
        logger.info(f"WorkflowManager: 已标准化 {len(normalized)} 个工作流")
        return normalized
    
    def load_workflows_from_dict(self, raw_workflows: Union[Dict[str, List[str]], Dict[str, Dict[str, Any]]]) -> bool:
        """从字典数据加载工作流"""
        try:
            normalized = self.normalize_workflows(raw_workflows)
            for name, workflow in normalized.items():
                self.add_workflow(workflow)
            logger.info(f"WorkflowManager: 成功加载 {len(normalized)} 个工作流")
            return True
        except Exception as e:
            logger.error(f"WorkflowManager: 加载工作流时发生错误: {str(e)}")
            return False
            
    def format_workflow_list(self) -> str:
        """格式化工作流列表用于选择，返回格式化字符串"""
        workflow_list = ""
        
        for idx, (name, workflow) in enumerate(self.workflows.items(), 0):
            workflow_list += f"\n{idx}. **{name}**:\n"
            steps = workflow.to_string_list()
            for step in steps:
                workflow_list += f"   - {step}\n"
        
        return workflow_list
    
    def get_workflow_by_index(self, index: int) -> Optional[Workflow]:
        """根据索引获取工作流"""
        workflow_names = self.list_workflows()
        if 0 <= index < len(workflow_names):
            return self.get_workflow(workflow_names[index])
        return None
    
    def format_workflows_for_context(self,workflows_name:List[str]) -> str:
        """格式化系统提示"""
        workflow_list = ""
        find_workflows_nums = 0
        for name in workflows_name:
            workflow_guidance = ""
            workflow = self.get_workflow(name)
            if workflow:
                find_workflows_nums += 1
                workflow_guidance += f"""
🔄 **推荐工作流{find_workflows_nums}: {name}**

建议按以下步骤执行任务（可根据实际情况灵活调整）：

"""
                ordered_steps = workflow.get_ordered_steps()
                for i, step in enumerate(ordered_steps, 0):
                    print(step)
                    print(type(step))
                    workflow_guidance += f"{i}. {step.description}\n"

                workflow_list += workflow_guidance

        if find_workflows_nums > 0:
            workflow_list += """
💡 **执行建议:**
- 以上步骤仅作参考指导，请根据具体问题灵活调整
- 每完成一个步骤，评估进展并决定下一步行动
- 充分利用可用工具提高工作效率
- 如遇到问题，优先解决当前步骤的关键障碍

请参考此工作流来规划你的任务执行，但要根据具体情况灵活应用。"""
        return workflow_list
