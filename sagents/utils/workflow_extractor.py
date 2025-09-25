# -*- coding: utf-8 -*-
"""
Workflow Extractor - 从messages中提取workflow的工具类
用于分析agent对话记录，提取任务执行的workflow模式，以便指导后续类似任务的执行
"""

import json
import traceback
from typing import Dict, List, Any, Optional
import requests
from datetime import datetime


class WorkflowExtractor:
    """
    从agent对话messages中提取workflow的工具类
    """
    
    def __init__(self, api_key: str, model: str = "deepseek-v3", base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1", abstraction_level: str = "abstract"):
        """
        初始化WorkflowExtractor
        
        Args:
            api_key: API密钥
            model: 使用的模型名称
            base_url: API基础URL
            abstraction_level: 抽象程度，"abstract"(抽象)或"specific"(具体)
        """
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.abstraction_level = abstraction_level
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    
    def extract_workflows_from_messages(self, messages: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """
        从messages中提取workflow
        
        Args:
            messages: 对话消息列表
            
        Returns:
            Dict[str, List[str]]: 提取的workflow字典，格式为 {"任务名称": ["步骤1", "步骤2", ...]}
        """
        try:
            workflows = {}
            
            if self.abstraction_level == "both":
                # 提取抽象级别的任务和workflow
                abstract_tasks = self._extract_tasks(messages, "abstract")
                for task in abstract_tasks:
                    abstract_steps = self._extract_workflow_steps(messages, task, "abstract")
                    if abstract_steps:
                        workflows[task] = abstract_steps
                
                # 提取具体级别的任务和workflow
                specific_tasks = self._extract_tasks(messages, "specific")
                for task in specific_tasks:
                    specific_steps = self._extract_workflow_steps(messages, task, "specific")
                    if specific_steps:
                        workflows[task] = specific_steps
            else:
                # 提取指定级别的任务和workflow
                tasks = self._extract_tasks(messages, self.abstraction_level)
                for task in tasks:
                    steps = self._extract_workflow_steps(messages, task, self.abstraction_level)
                    if steps:
                        workflows[task] = steps
            
            return workflows
            
        except Exception as e:
            print(f"提取workflow时发生错误: {e}")
            traceback.print_exc()
            return {}
    
    def _extract_tasks(self, messages: List[Dict[str, Any]], abstraction_level: str = "abstract") -> List[str]:
        """
        从messages中提取任务列表
        
        Args:
            messages: 对话消息列表
            
        Returns:
            List[str]: 任务名称列表
        """
        try:
            # 构建用于提取任务的prompt
            messages_text = self._format_messages_for_analysis(messages)
            
            if abstraction_level == "abstract":
                task_requirements = """
请按照以下要求提取任务：
1. 一个用户请求只能抽象出一个主要任务
2. 识别用户提出的核心问题或需求，忽略次要的辅助任务
3. 任务名称应该具有通用性，不包含具体的变量值、参数或实例信息
4. 任务名称应该描述任务的类型而非具体内容
5. 返回JSON格式，只包含一个任务

示例：
{"task": "数据库查询与统计分析"}
{"task": "文件下载与内容分析"}
{"task": "客户信息查询与筛选"}"""
            else:  # specific
                 task_requirements = """
请按照以下要求提取任务：
1. 一个用户请求只能抽象出一个主要任务
2. 识别用户提出的核心问题或需求，忽略次要的辅助任务
3. 任务名称可以包含具体的业务场景、数据类型或操作对象，但不能包含具体的参数值
4. 任务名称应该描述参数的类型而非具体数值（如"按时间段"而非"2025年9月16日至21日"）
5. 任务名称应该更具体地描述要完成的工作，但保持一定的通用性
6. 返回JSON格式，只包含一个任务

示例：
{"task": "5G核心网SMF网元用户类型会话数按时间段统计分析"}
{"task": "销售数据库特定条件客户信息查询与业绩统计"}
{"task": "CSV格式数据文件导入清洗与格式转换"}
{"task": "指定时间范围订单数据分析与可视化报表生成"}"""
            
            prompt = f"""
请分析以下agent对话记录，识别出其中包含的主要任务。

对话记录：
{messages_text}

{task_requirements}

返回格式：
{{"task": "任务名称"}}
"""

            response = self._call_llm(prompt)
            
            if response:
                try:
                    # 处理可能包含markdown代码块的响应
                    cleaned_response = self._clean_json_response(response)
                    result = json.loads(cleaned_response)
                    task = result.get("task", "")
                    return [task] if task else []
                except json.JSONDecodeError:
                    print(f"解析任务JSON失败: {response}")
                    return []
            
            return []
            
        except Exception as e:
            print(f"提取任务列表时发生错误: {e}")
            traceback.print_exc()
            return []
    
    def _extract_workflow_steps(self, messages: List[Dict[str, Any]], task: str, abstraction_level: str = "abstract") -> List[str]:
        """
        为特定任务提取workflow步骤
        
        Args:
            messages: 对话消息列表
            task: 任务名称
            abstraction_level: 抽象程度，"abstract"(抽象)或"specific"(具体)
            
        Returns:
            List[str]: workflow步骤列表
        """
        try:
            messages_text = self._format_messages_for_analysis(messages)
            
            # 真实的工具名称列表
            real_tools = [
                "calculate", "file_read", "file_write", "complete_task",
                "get_customers_search_schema_on_salesmate", "search_customers_with_filters_on_salesmate",
                "get_askonce_database_tables", "execute_sql_code_on_askonce_database",
                "unified_web_search", "recall_user_memory", "remember_user_memory",
                "get_real_time_quote", "transfer_to_human", "list_files",
                "search_content_in_file", "web_search"
            ]
            
            # 根据抽象程度设置不同的prompt
            if abstraction_level == "specific":
                abstraction_instruction = """
4. 基于对话记录中实际执行的工具调用来生成步骤，一个工具调用对应一个步骤
5. 不要将"解析用户需求"作为步骤
6. 步骤应该具体明确，可以包含具体的工具名称、操作方法等详细信息
7. 对于使用工具的步骤，在步骤末尾添加"[工具: 工具名称]"标识
8. 工具名称必须从以下真实工具中选择：{', '.join(real_tools)}
9. 如果步骤不需要执行工具（如纯分析、思考步骤），则不要添加工具标识
10. 不要把一个工具调用拆分成多个步骤
11. 颗粒度可以更细，包含具体的操作细节"""
                example = """{{"workflow_steps": [
    "查询数据库表结构 - 确认包含关键字段的数据表 [工具: get_askonce_database_tables]",
    "编写并执行数据查询 - 构建查询语句并获取统计结果 [工具: execute_sql_code_on_askonce_database]",
    "数据清洗处理 - 标准化日期格式和数值单位 [工具: calculate]",
    "生成统计报告 - 汇总分类数据并计算关键指标 [工具: file_write]",
    "分析数据趋势 - 识别关键模式和异常值",
    "可视化展示 - 创建趋势图表对比不同类别数据 [工具: file_write]"
]}}"""
            else:  # abstract
                abstraction_instruction = """
4. 基于对话记录中实际执行的工具调用来生成步骤，一个工具调用对应一个步骤
5. 不要将"解析用户需求"作为步骤
6. 步骤应该具有通用性，避免过于具体的限定词（如"按天"、"按小时"等）
7. 对于使用工具的步骤，在步骤末尾添加"[工具: 工具名称]"标识
8. 工具名称必须从以下真实工具中选择：{', '.join(real_tools)}
9. 如果步骤不需要执行工具（如纯分析、思考步骤），则不要添加工具标识
10. 不要把一个工具调用拆分成多个步骤
11. 颗粒度适中，描述操作的类型而非具体内容
12. 对于非必选的步骤，在开头添加"【可选】"标识"""
                example = """{{"workflow_steps": [
    "查询数据库表结构 - 确认包含关键字段的数据表 [工具: get_askonce_database_tables]",
    "编写并执行数据查询 - 构建查询语句并获取统计结果 [工具: execute_sql_code_on_askonce_database]",
    "【可选】数据清洗处理 - 标准化数据格式和单位 [工具: calculate]",
    "生成统计报告 - 汇总数据并计算关键指标 [工具: file_write]",
    "分析数据趋势 - 识别关键模式和异常值",
    "可视化展示 - 创建图表展示分析结果 [工具: file_write]"
]}}"""

            prompt = f"""
请分析以下agent对话记录，为任务"{task}"提取工作流步骤。

对话记录：
{messages_text}

请按照以下要求提取工作流步骤：
1. 仔细分析对话记录中assistant实际执行的工具调用，基于这些真实的工具调用来生成步骤
2. 一个工具调用对应一个步骤，不要把一个工具调用拆分成多个步骤
3. 每个步骤格式为："动作描述 - 目标说明"，如果使用了工具则添加"[工具: 工具名称]"
{abstraction_instruction}
12. 按照执行顺序排列
13. 合并相似的操作，避免过于细化
14. 返回JSON格式的步骤列表，最多8步

返回格式：
{{"workflow_steps": ["步骤1 - 目标1", "步骤2 - 目标2", ...]}}

示例：
{example}
"""

            response = self._call_llm(prompt)
            
            if response:
                try:
                    # 处理可能包含markdown代码块的响应
                    cleaned_response = self._clean_json_response(response)
                    result = json.loads(cleaned_response)
                    return result.get("workflow_steps", [])
                except json.JSONDecodeError:
                    print(f"解析workflow步骤JSON失败: {response}")
                    return []
            
            return []
            
        except Exception as e:
            print(f"提取workflow步骤时发生错误: {e}")
            traceback.print_exc()
            return []
    
    def _format_messages_for_analysis(self, messages: List[Dict[str, Any]]) -> str:
        """
        格式化messages用于分析
        
        Args:
            messages: 对话消息列表
            
        Returns:
            str: 格式化后的文本
        """
        formatted_messages = []
        
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls", [])
            message_type = msg.get("message_type", "normal")
            
            # 格式化消息内容
            if role == "user":
                formatted_messages.append(f"用户: {content}")
            elif role == "assistant":
                if tool_calls:
                    # 处理工具调用
                    for tool_call in tool_calls:
                        function_name = tool_call.get("function", {}).get("name", "unknown")
                        arguments = tool_call.get("function", {}).get("arguments", "{}")
                        formatted_messages.append(f"助手调用工具: {function_name}({arguments})")
                elif content:
                    formatted_messages.append(f"助手: {content}")
            elif role == "tool":
                formatted_messages.append(f"工具返回: {content[:200]}...")  # 截取前200字符
        
        return "\n".join(formatted_messages)
    
    def _clean_json_response(self, response: str) -> str:
        """
        清理LLM响应中的markdown代码块格式
        
        Args:
            response: 原始响应
            
        Returns:
            str: 清理后的JSON字符串
        """
        # 移除markdown代码块标记
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]  # 移除 ```json
        elif response.startswith("```"):
            response = response[3:]   # 移除 ```
        
        if response.endswith("```"):
            response = response[:-3]  # 移除结尾的 ```
        
        return response.strip()
    
    def _call_llm(self, prompt: str) -> Optional[str]:
        """
        调用大语言模型
        
        Args:
            prompt: 提示词
            
        Returns:
            Optional[str]: 模型响应
        """
        try:
            url = f"{self.base_url}/chat/completions"
            
            data = {
                "model": self.model,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.1,
                "max_tokens": 2000
            }
            
            response = requests.post(url, headers=self.headers, json=data, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            return result["choices"][0]["message"]["content"]
            
        except Exception as e:
            print(f"调用LLM时发生错误: {e}")
            traceback.print_exc()
            return None
    
    def save_workflows_to_file(self, workflows: Dict[str, List[str]], output_path: str) -> bool:
        """
        将提取的workflows保存到文件
        
        Args:
            workflows: 提取的workflow字典
            output_path: 输出文件路径
            
        Returns:
            bool: 是否保存成功
        """
        try:
            # 添加时间戳和元数据
            output_data = {
                "extracted_at": datetime.now().isoformat(),
                "extractor_version": "1.0",
                "workflows": workflows
            }
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            
            print(f"Workflows已保存到: {output_path}")
            return True
            
        except Exception as e:
            print(f"保存workflows时发生错误: {e}")
            traceback.print_exc()
            return False
    
    def load_messages_from_file(self, file_path: str) -> List[Dict[str, Any]]:
        """
        从文件加载messages
        
        Args:
            file_path: messages文件路径
            
        Returns:
            List[Dict[str, Any]]: 消息列表
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                messages = json.load(f)
            
            if isinstance(messages, list):
                return messages
            else:
                print(f"文件格式错误，期望列表格式: {file_path}")
                return []
                
        except Exception as e:
            print(f"加载messages文件时发生错误: {e}")
            traceback.print_exc()
            return []