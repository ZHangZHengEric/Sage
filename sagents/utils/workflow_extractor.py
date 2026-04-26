# -*- coding: utf-8 -*-
"""
Workflow Extractor - 从messages中提取workflow的工具类
用于分析agent对话记录，提取任务执行的workflow模式，以便指导后续类似任务的执行
"""

import json
import traceback
from typing import Dict, List, Any, Optional
import httpx
from datetime import datetime
from sagents.utils.prompt_manager import PromptManager


class WorkflowExtractor:
    """
    从agent对话messages中提取workflow的工具类
    """
    
    def __init__(self, api_key: str, model: str = "deepseek-v3", base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1", abstraction_level: str = "abstract", language: str = "en"):
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
        self.language = language
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
                task_requirements = 'Extract only one general, abstract primary task, and return JSON: {"task": "task name"}.'
            else:  # specific
                task_requirements = 'Extract only one more specific but still general primary task, and return JSON: {"task": "task name"}.'
            
            prompt = PromptManager().get_prompt(
                "workflow_extractor_task_prompt",
                agent="common_util",
                language=self.language,
            ).format(messages_text=messages_text, task_requirements=task_requirements)

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
                abstraction_instruction = "The steps should be more specific and may include tool names and operation details; tool usage must match real execution."
            else:
                abstraction_instruction = "The steps should remain general and not be overly specific; tool usage must match real execution."

            prompt = PromptManager().get_prompt(
                "workflow_extractor_steps_prompt",
                agent="common_util",
                language=self.language,
            ).format(
                messages_text=messages_text,
                task=task,
                abstraction_instruction=abstraction_instruction,
                real_tools=", ".join(real_tools),
            )

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
            
            # 格式化消息内容
            if role == "user":
                formatted_messages.append(f"User: {content}")
            elif role == "assistant":
                if tool_calls:
                    # 处理工具调用
                    for tool_call in tool_calls:
                        function_name = tool_call.get("function", {}).get("name", "unknown")
                        arguments = tool_call.get("function", {}).get("arguments", "{}")
                        formatted_messages.append(f"Assistant called tool: {function_name}({arguments})")
                elif content:
                    formatted_messages.append(f"Assistant: {content}")
            elif role == "tool":
                formatted_messages.append(f"Tool returned: {content[:200]}...")  # 截取前200 characters
        
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
            
            with httpx.Client() as client:
                response = client.post(url, headers=self.headers, json=data, timeout=30)
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
                "extracted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
