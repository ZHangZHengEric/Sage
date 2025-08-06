
import traceback
from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, Optional, Generator,Union
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole,MessageType
from sagents.context.session_context import SessionContext
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_base import AgentToolSpec
from sagents.context.tasks.task_manager import TaskManager
from sagents.context.tasks.task_base import TaskBase, TaskStatus
import json
import uuid
from copy import deepcopy
from openai import OpenAI

WorkflowStep = Dict[str, Any]  # 包含 id, name, description, order, substeps?
NestedWorkflow = Dict[str, WorkflowStep]  # {step_id: WorkflowStep}
WorkflowFormat = Union[Dict[str, List[str]], Dict[str, NestedWorkflow]]  # 兼容旧格式和新格式

def convert_nested_workflow_to_steps(nested_workflow: NestedWorkflow) -> List[str]:
    """
    将嵌套对象格式的工作流转换为字符串列表格式
    
    Args:
        nested_workflow: 嵌套对象格式的工作流 {step_id: WorkflowStep}
        
    Returns:
        List[str]: 字符串格式的工作流步骤列表
    """
    steps = []
    
    def process_step(step: WorkflowStep, level: int = 0) -> None:
        """递归处理步骤，保持层次结构"""
        indent = "  " * level
        step_text = f"{indent}{step.get('name', '')}: {step.get('description', '')}"
        steps.append(step_text)
        
        # 如果有子步骤，递归处理
        substeps = step.get('substeps', {})
        if substeps:
            # 按order排序子步骤
            sorted_substeps = sorted(
                substeps.items(), 
                key=lambda x: x[1].get('order', 0)
            )
            for substep_id, substep in sorted_substeps:
                process_step(substep, level + 1)
    
    # 按order排序根步骤
    if nested_workflow:
        sorted_steps = sorted(
            nested_workflow.items(), 
            key=lambda x: x[1].get('order', 0)
        )
        for step_id, step in sorted_steps:
            process_step(step)
    
    return steps


def detect_workflow_format(available_workflows: WorkflowFormat) -> str:
    """
    检测工作流格式类型
    
    Args:
        available_workflows: 工作流数据
        
    Returns:
        str: 'legacy' (旧格式 Dict[str, List[str]]) 或 'nested' (新格式 Dict[str, NestedWorkflow])
    """
    if not available_workflows:
        return 'legacy'
    
    # 获取第一个工作流来检测格式
    first_workflow = next(iter(available_workflows.values()))
    
    if isinstance(first_workflow, list):
        return 'legacy'
    elif isinstance(first_workflow, dict):
        # 进一步检查是否是嵌套工作流格式
        if first_workflow and isinstance(next(iter(first_workflow.values()), {}), dict):
            return 'nested'
    
    return 'legacy'


def normalize_workflows(available_workflows: WorkflowFormat) -> Dict[str, List[str]]:
    """
    将工作流标准化为字符串列表格式
    
    Args:
        available_workflows: 原始工作流数据（支持新旧格式）
        
    Returns:
        Dict[str, List[str]]: 标准化后的工作流（统一为字符串列表格式）
    """
    if not available_workflows:
        return {}
    
    format_type = detect_workflow_format(available_workflows)
    logger.info(f"WorkflowSelector: 检测到工作流格式: {format_type}")
    
    if format_type == 'legacy':
        # 旧格式，直接返回
        return available_workflows
    elif format_type == 'nested':
        # 新格式，需要转换
        normalized = {}
        for workflow_name, nested_workflow in available_workflows.items():
            normalized[workflow_name] = convert_nested_workflow_to_steps(nested_workflow)
        
        logger.info(f"WorkflowSelector: 已转换 {len(normalized)} 个嵌套工作流为字符串格式")
        return normalized
    
    return {}


class WorkflowSelectAgent(AgentBase):
    def __init__(self, model: Optional[OpenAI] = None, model_config: Dict[str, Any] = ..., system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.WORKFLOW_SELECT_PROMPT =  """
你是一个工作流选择专家。请根据用户的对话历史，从提供的工作流模板中选择最合适的一个。

**对话历史：**
{conversation_history}

**可用的工作流模板：**
{workflow_list}

**任务要求：**
1. 仔细分析对话历史中用户的核心需求和任务类型
2. 对比各个工作流模板的适用场景
3. 选择匹配的工作流，或者判断没有合适的工作流

**输出格式（JSON）：**
```json
{{
    "has_matching_workflow": true/false,
    "selected_workflow_index": 0
}}
```

请确保输出的JSON格式正确。
如果没有合适的工作流，请设置has_matching_workflow为false。
selected_workflow_index 从0 开始计数
"""
        self.agent_name = "WorkflowSelectAgent"
        self.agent_description = "工作流选择智能体，专门负责基于当前状态选择最合适的工作流"
        logger.info("WorkflowSelectAgent 初始化完成")

    def run_stream(self, session_context: SessionContext, tool_manager: ToolManager = None, session_id: str = None) -> Generator[List[MessageChunk], None, None]:
        message_manager = session_context.message_manager
        task_manager = session_context.task_manager

        task_description_messages = message_manager.extract_all_user_and_final_answer_messages()
        task_description_messages_str = MessageManager.convert_messages_to_str(task_description_messages)

        normalized_workflows = normalize_workflows(session_context.candidate_workflows)
        
        workflow_list = ""
        workflow_index_map = {}  # 索引到名称的映射
        for idx, (name, steps) in enumerate(normalized_workflows.items(), 0):
            workflow_index_map[idx] = name
            workflow_list += f"\n{idx}. **{name}**:\n"
            for step in steps:
                workflow_list += f"   - {step}\n"

        prompt = self.WORKFLOW_SELECT_PROMPT.format(
            conversation_history=task_description_messages_str,
            workflow_list=workflow_list
        )

        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                show_content=prompt,
                message_type=MessageType.GUIDE.value
            )
        ]
        all_content = ''
        for llm_repsonse_chunk in self._call_llm_streaming(messages=llm_request_message,
                                             session_id=session_id,
                                             step_name="workflow_select"):
            if len(llm_repsonse_chunk.choices) == 0:
                continue
            if llm_repsonse_chunk.choices[0].delta.content:
                all_content += llm_repsonse_chunk.choices[0].delta.content

        try:
            # 提取JSON部分
            logger.debug(f"WorkflowSelector: 原始LLM响应: {all_content}")
            json_start = all_content.find('{')
            json_end = all_content.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_content = all_content[json_start:json_end]
                result = json.loads(json_content)
                logger.debug(f"WorkflowSelector: 提取的JSON内容: {json_content}")
                has_matching = result.get('has_matching_workflow', False)
                selected_workflow_index = result.get('selected_workflow_index', 0)
                
                logger.info(f"WorkflowSelector: LLM分析结果 - 匹配: {has_matching}, 工作流索引: {selected_workflow_index}")
                if has_matching and selected_workflow_index in workflow_index_map:
                    logger.info(f"WorkflowSelector: 工作流名称: {workflow_index_map[selected_workflow_index]}")
                    selected_workflow_name = workflow_index_map[selected_workflow_index]
                    workflow_steps = normalized_workflows[selected_workflow_name]
                    logger.info(f"WorkflowSelector: 选择工作流: {selected_workflow_name}")
                    guidance = f"""
🔄 **推荐工作流: {selected_workflow_name}**

建议按以下步骤执行任务（可根据实际情况灵活调整）：

"""
    
                    for i, step in enumerate(workflow_steps, 1):
                        guidance += f"{step}\n"
    
                    guidance += """
💡 **执行建议:**
- 以上步骤仅作参考指导，请根据具体问题灵活调整
- 每完成一个步骤，评估进展并决定下一步行动
- 充分利用可用工具提高工作效率
- 如遇到问题，优先解决当前步骤的关键障碍

请参考此工作流来规划你的任务执行，但要根据具体情况灵活应用。
"""
                    session_context.add_and_update_system_context({'workflow_guidance': guidance})
                else:
                    logger.info("WorkflowSelector: 未找到合适的工作流")
            else:
                logger.error("WorkflowSelector: 无法从LLM响应中提取JSON内容")
                
        except json.JSONDecodeError as e:
            logger.error(f"WorkflowSelector: JSON解析失败: {str(e)}")
            logger.error(f"WorkflowSelector: 原始响应: {all_content}")
            yield [MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content=f"WorkflowSelector: 无法从LLM响应中提取JSON内容，原始响应: {all_content}",
                message_id=str(uuid.uuid4()),
                show_content="",
                message_type=MessageType.GUIDE.value
            )]


