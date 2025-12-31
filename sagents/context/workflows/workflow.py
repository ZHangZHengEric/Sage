from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
import json
from sagents.utils.logger import logger
from enum import Enum

class WorkflowFormat(Enum):
    """工作流格式类型枚举"""
    LEGACY = "legacy"  # 旧格式: Dict[str, List[str]]
    NESTED = "nested"  # 新格式: Dict[str, Dict[str, WorkflowStep]]

@dataclass
class WorkflowStep:
    """工作流步骤数据类"""
    id: str
    name: str
    description: str
    order: int = 0
    substeps: Optional[Dict[str, 'WorkflowStep']] = field(default_factory=dict)
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)
    
    def __post_init__(self):
        """初始化后的验证"""
        if not self.id:
            raise ValueError("WorkflowStep: id不能为空")
        if not self.name:
            raise ValueError("WorkflowStep: name不能为空")
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'order': self.order,
            'metadata': self.metadata or {}
        }
        if self.substeps:
            result['substeps'] = {k: v.to_dict() for k, v in self.substeps.items()}
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WorkflowStep':
        """从字典创建WorkflowStep实例"""
        if not isinstance(data, dict):
            raise ValueError("WorkflowStep.from_dict: 输入数据必须是字典")
            
        substeps = {}
        if 'substeps' in data and data['substeps']:
            if isinstance(data['substeps'], dict):
                substeps = {k: cls.from_dict(v) for k, v in data['substeps'].items()}
            else:
                logger.warning("WorkflowStep.from_dict: substeps格式不正确，忽略")
        
        return cls(
            id=data.get('id', ''),
            name=data.get('name', ''),
            description=data.get('description', ''),
            order=data.get('order', 0),
            substeps=substeps,
            metadata=data.get('metadata', {})
        )
    
    def to_string(self, level: int = 0) -> str:
        """转换为字符串格式，保持层次结构"""
        indent = "  " * level
        result = f"{indent}{self.name}: {self.description}"
        
        if self.substeps:
            # 按order排序子步骤
            sorted_substeps = sorted(self.substeps.values(), key=lambda x: x.order)
            for substep in sorted_substeps:
                result += "\n" + substep.to_string(level + 1)
        
        return result
    
    def add_substep(self, substep: 'WorkflowStep') -> None:
        """添加子步骤"""
        if not self.substeps:
            self.substeps = {}
        self.substeps[substep.id] = substep
        logger.debug(f"WorkflowStep: 为步骤 '{self.id}' 添加子步骤 '{substep.id}'")
    
    def remove_substep(self, substep_id: str) -> bool:
        """移除子步骤"""
        if self.substeps and substep_id in self.substeps:
            del self.substeps[substep_id]
            logger.debug(f"WorkflowStep: 从步骤 '{self.id}' 移除子步骤 '{substep_id}'")
            return True
        return False
    
    def get_substep(self, substep_id: str) -> Optional['WorkflowStep']:
        """获取子步骤"""
        if self.substeps:
            return self.substeps.get(substep_id)
        return None
    
    def get_all_substeps_flat(self) -> List['WorkflowStep']:
        """获取所有子步骤的扁平列表（包括嵌套的子步骤）"""
        result = []
        if self.substeps:
            for substep in self.substeps.values():
                result.append(substep)
                result.extend(substep.get_all_substeps_flat())
        return result
    
    def clone(self) -> 'WorkflowStep':
        """克隆步骤"""
        return WorkflowStep.from_dict(self.to_dict())


@dataclass
class Workflow:
    """工作流数据类"""
    name: str
    description: str = ""
    steps: Dict[str, WorkflowStep] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    format_type: WorkflowFormat = WorkflowFormat.NESTED
    
    def __post_init__(self):
        """初始化后的验证"""
        if not self.name:
            raise ValueError("Workflow: name不能为空")
    
    def add_step(self, step: WorkflowStep) -> None:
        """添加步骤"""
        if not isinstance(step, WorkflowStep):
            raise ValueError("Workflow.add_step: step必须是WorkflowStep实例")
        self.steps[step.id] = step
        logger.debug(f"Workflow '{self.name}': 添加步骤 '{step.id}', 步骤描述: {step.description}")
    
    def remove_step(self, step_id: str) -> bool:
        """移除步骤"""
        if step_id in self.steps:
            del self.steps[step_id]
            logger.debug(f"Workflow '{self.name}': 移除步骤 '{step_id}'")
            return True
        logger.warning(f"Workflow '{self.name}': 尝试移除不存在的步骤 '{step_id}'")
        return False
    
    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        """获取步骤"""
        return self.steps.get(step_id)
    
    def get_ordered_steps(self) -> List[WorkflowStep]:
        """获取按order排序的步骤列表"""
        return sorted(self.steps.values(), key=lambda x: x.order)
    
    def reorder_steps(self) -> None:
        """重新排序步骤（自动分配order）"""
        ordered_steps = sorted(self.steps.values(), key=lambda x: x.order)
        for i, step in enumerate(ordered_steps, 1):
            step.order = i
        logger.debug(f"Workflow '{self.name}': 重新排序了 {len(ordered_steps)} 个步骤")
    
    def to_string_list(self) -> List[str]:
        """转换为字符串列表格式（兼容旧格式）"""
        result = []
        ordered_steps = self.get_ordered_steps()
        
        for step in ordered_steps:
            result.append(step.to_string())
        
        return result
    
    def to_nested_dict(self) -> Dict[str, Dict[str, Any]]:
        """转换为嵌套字典格式"""
        return {step_id: step.to_dict() for step_id, step in self.steps.items()}
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为完整字典格式"""
        return {
            'name': self.name,
            'description': self.description,
            'steps': self.to_nested_dict(),
            'metadata': self.metadata or {},
            'format_type': self.format_type.value
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Workflow':
        """从字典创建Workflow实例"""
        if not isinstance(data, dict):
            raise ValueError("Workflow.from_dict: 输入数据必须是字典")
            
        steps = {}
        if 'steps' in data and data['steps']:
            if isinstance(data['steps'], dict):
                steps = {k: WorkflowStep.from_dict(v) for k, v in data['steps'].items()}
            else:
                logger.warning("Workflow.from_dict: steps格式不正确，忽略")
        
        format_type = WorkflowFormat.NESTED
        if 'format_type' in data:
            try:
                format_type = WorkflowFormat(data['format_type'])
            except ValueError:
                logger.warning(f"Workflow.from_dict: 不支持的格式类型 '{data['format_type']}'，使用默认格式")
        
        return cls(
            name=data.get('name', ''),
            description=data.get('description', ''),
            steps=steps,
            metadata=data.get('metadata', {}),
            format_type=format_type
        )
    
    @classmethod
    def from_legacy_format(cls, name: str, steps: List[str], description: str = "") -> 'Workflow':
        """从旧格式（字符串列表）创建Workflow实例"""
        if not isinstance(steps, list):
            raise ValueError("Workflow.from_legacy_format: steps必须是字符串列表")
            
        workflow = cls(name=name, description=description, format_type=WorkflowFormat.LEGACY)
        
        for i, step_text in enumerate(steps):
            if isinstance(step_text, str):
                step = WorkflowStep(
                    id=f"step_{i+1}",
                    name=f"步骤 {i+1}",
                    description=step_text.strip(),
                    order=i+1
                )
                workflow.add_step(step)
            else:
                logger.warning(f"Workflow.from_legacy_format: 跳过非字符串步骤: {step_text}")
        
        logger.info(f"Workflow: 从旧格式创建工作流 '{name}'，包含 {len(workflow.steps)} 个步骤")
        return workflow
    
    def to_json(self) -> str:
        """转换为JSON字符串"""
        try:
            return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Workflow '{self.name}': 转换为JSON时发生错误: {str(e)}")
            return "{}"
    
    @classmethod
    def from_json(cls, json_str: str) -> 'Workflow':
        """从JSON字符串创建Workflow实例"""
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except json.JSONDecodeError as e:
            logger.error(f"Workflow.from_json: JSON解析错误: {str(e)}")
            raise ValueError(f"无效的JSON格式: {str(e)}")
    
    def clone(self) -> 'Workflow':
        """克隆工作流"""
        return Workflow.from_dict(self.to_dict())
    
    def get_step_count(self) -> int:
        """获取步骤总数（包括子步骤）"""
        total = len(self.steps)
        for step in self.steps.values():
            total += len(step.get_all_substeps_flat())
        return total
    
    def validate(self) -> List[str]:
        """验证工作流的有效性，返回错误列表"""
        errors = []
        
        if not self.name:
            errors.append("工作流名称不能为空")
        
        if not self.steps:
            errors.append("工作流必须包含至少一个步骤")
            return errors
        
        # 检查步骤ID重复
        step_ids = list(self.steps.keys())
        if len(step_ids) != len(set(step_ids)):
            errors.append("存在重复的步骤ID")
        
        # 检查步骤order重复
        orders = [step.order for step in self.steps.values()]
        if len(orders) != len(set(orders)):
            errors.append("存在重复的步骤顺序")
        
        # 验证每个步骤
        for step_id, step in self.steps.items():
            if not step.id:
                errors.append(f"步骤 '{step_id}' 的ID为空")
            if not step.name:
                errors.append(f"步骤 '{step_id}' 的名称为空")
        
        return errors
    
    def is_valid(self) -> bool:
        """检查工作流是否有效"""
        return len(self.validate()) == 0