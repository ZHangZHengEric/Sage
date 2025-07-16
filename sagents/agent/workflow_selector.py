"""
工作流选择器

使用大语言模型智能选择最合适的工作流模板。
传入用户问题和可用的工作流列表，让LLM判断哪个工作流最合适。

作者: Eric ZZ
版本: 1.0
"""

import json
from typing import Dict, List, Any, Optional, Tuple, Union
from sagents.utils.logger import logger

# 嵌套工作流步骤类型定义
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


def select_workflow_with_llm(
    model: Any, 
    model_config: Dict[str, Any],
    messages: List[Dict[str, Any]], 
    available_workflows: WorkflowFormat
) -> Tuple[Optional[str], Optional[List[str]]]:
    """
    使用大语言模型选择最合适的工作流
    
    Args:
        model: 语言模型实例
        model_config: 模型配置
        messages: 包含用户新输入的完整消息历史
        available_workflows: 可用的工作流字典 (支持新旧格式)
        
    Returns:
        Tuple[workflow_name, workflow_steps]: 选择的工作流名称、步骤
    """
    if not messages or not available_workflows:
        return None, None
    
    # 标准化工作流格式为字符串列表格式，用于LLM处理
    normalized_workflows = normalize_workflows(available_workflows)
    
    # 提取用户消息内容用于日志显示
    user_content = ""
    for msg in messages:
        if msg.get('role') == 'user':
            user_content = msg.get('content', '')[:50]
            break
    
    logger.info(f"WorkflowSelector: 开始使用LLM选择工作流，消息历史长度: {len(messages)}")
    if user_content:
        logger.info(f"WorkflowSelector: 最新用户消息: {user_content}...")
    
    try:
        # 构建工作流列表，使用索引编号
        workflow_list = ""
        workflow_index_map = {}  # 索引到名称的映射
        for idx, (name, steps) in enumerate(normalized_workflows.items(), 1):
            workflow_index_map[idx] = name
            workflow_list += f"\n{idx}. **{name}**:\n"
            for step in steps:
                workflow_list += f"   - {step}\n"
        
        # 构建对话历史文本
        conversation_history = ""
        for msg in messages:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            conversation_history += f"{role}: {content}\n"
        
        prompt = f"""
你是一个工作流选择专家。请根据用户的对话历史，从提供的工作流模板中选择最合适的一个。

**对话历史：**
{conversation_history}

**可用的工作流模板：**
{workflow_list}

**任务要求：**
1. 仔细分析对话历史中用户的核心需求和任务类型
2. 对比各个工作流模板的适用场景
3. 选择最匹配的工作流，或者判断没有合适的工作流

**输出格式（JSON）：**
```json
{{
    "has_matching_workflow": true/false,
    "selected_workflow_index": 1
}}
```

请确保输出的JSON格式正确。如果没有合适的工作流，请设置has_matching_workflow为false。
"""
        
        # 调用模型
        llm_messages = [
            {"role": "system", "content": "你是一个专业的工作流选择助手，能够准确分析用户需求并选择合适的工作流模板。"},
            {"role": "user", "content": prompt}
        ]
        
        response = model.chat.completions.create(
            messages=llm_messages,
            **model_config
        )
        response_content = response.choices[0].message.content.strip()
        
        logger.debug(f"WorkflowSelector: LLM响应内容: {response_content[:200]}...")
        
        # 解析LLM的响应
        try:
            # 提取JSON部分
            json_start = response_content.find('{')
            json_end = response_content.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_content = response_content[json_start:json_end]
                result = json.loads(json_content)
                
                has_matching = result.get('has_matching_workflow', False)
                selected_workflow_index = result.get('selected_workflow_index', 0)
                
                logger.info(f"WorkflowSelector: LLM分析结果 - 匹配: {has_matching}, 工作流索引: {selected_workflow_index}")
                
                if has_matching and selected_workflow_index in workflow_index_map:
                    selected_workflow_name = workflow_index_map[selected_workflow_index]
                    workflow_steps = normalized_workflows[selected_workflow_name]
                    
                    logger.info(f"WorkflowSelector: 选择工作流: {selected_workflow_name}")
                    return selected_workflow_name, workflow_steps
                else:
                    logger.info("WorkflowSelector: 未找到合适的工作流")
                    return None, None
                    
            else:
                logger.error("WorkflowSelector: 无法从LLM响应中提取JSON内容")
                return None, None
                
        except json.JSONDecodeError as e:
            logger.error(f"WorkflowSelector: JSON解析失败: {str(e)}")
            logger.error(f"WorkflowSelector: 原始响应: {response_content}")
            return None, None
            
    except Exception as e:
        logger.error(f"WorkflowSelector: 工作流选择失败: {str(e)}")
        return None, None


def create_workflow_guidance(workflow_name: str, workflow_steps: List[str]) -> str:
    """
    创建工作流指导文本
    
    Args:
        workflow_name: 工作流名称
        workflow_steps: 工作流步骤列表
        
    Returns:
        str: 格式化的工作流指导文本
    """
    guidance = f"""
🔄 **推荐工作流: {workflow_name}**

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
    
    return guidance 