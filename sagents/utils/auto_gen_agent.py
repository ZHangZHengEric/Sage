"""
自动生成Agent配置的工具类

该模块提供了通过大模型自动生成Agent配置的功能，包括：
- 根据描述生成Agent名称、描述和系统提示词
- 从工具管理器中智能选择合适的工具
- 生成工作流程配置
- 输出完整的Agent配置JSON

作者: Eric ZZ
创建时间: 2025-01-27
"""

import json
import time
import traceback
from typing import Dict, Any, List, Union, Optional
from datetime import datetime

from sagents.tool import ToolManager, ToolProxy
from sagents.utils.logger import logger
from sagents.utils.prompt_manager import PromptManager


class AutoGenAgentFunc:
    """自动生成Agent配置的工具类"""

    def __init__(self):
        """
        初始化AutoGenAgentFunc
        """
        logger.info("AutoGenAgentFunc initialized")

    async def generate_agent_config(
        self,
        agent_description: str,
        tool_manager: Union[ToolManager, ToolProxy],
        llm_client,
        model: str = "gpt-3.5-turbo",
        language: str = "en",
    ) -> Dict[str, Any]:
        """
        根据描述和工具管理器生成完整的Agent配置

        Args:
            agent_description: Agent的文字描述要求
            tool_manager: 工具管理器实例
            llm_client: 大模型客户端
            model: 大模型名称，默认为gpt-3.5-turbo

        Returns:
            完整的Agent配置字典
        """
        try:
            logger.info(f"开始生成Agent配置，描述: {agent_description[:100]}...")
            logger.info(f"使用模型: {model}")

            if not llm_client:
                raise ValueError("需要提供大模型客户端")

            # 获取所有可用工具信息
            available_tools = self._get_tools_info(tool_manager)
            logger.info(f"获取到 {len(available_tools)} 个可用工具")

            # 生成基础配置
            basic_config = await self._generate_basic_config(agent_description, available_tools, llm_client, model, language=language)
            if not basic_config:
                raise Exception("生成基础配置失败")

            # 根据tool_manager类型决定是否需要选择工具
            if isinstance(tool_manager, ToolProxy):
                # 如果是ToolProxy，直接使用其包含的工具，不再进行选择
                selected_tools = tool_manager.list_all_tools_name()
                logger.info(f"使用ToolProxy中预选的工具: {selected_tools}")
            else:
                # 如果是ToolManager，进行工具选择
                selected_tools = await self._select_tools(basic_config, available_tools, llm_client, model, language=language)
                if selected_tools is None:
                    raise Exception("选择工具失败")

            # 生成工作流程
            workflows = await self._generate_workflows(basic_config, selected_tools, llm_client, model, language=language)
            if workflows is None:
                raise Exception("生成工作流程失败")

            # 组装完整配置
            config = self._assemble_config(basic_config, selected_tools, workflows, language=language)

            logger.info("Agent配置生成完成")
            return config

        except Exception as e:
            logger.error(f"生成Agent配置失败: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def _get_tools_info(self, tool_manager: Union[ToolManager, ToolProxy]) -> List[Dict[str, Any]]:
        """
        从工具管理器或工具代理获取所有工具的详细信息

        Args:
            tool_manager: 工具管理器或工具代理实例

        Returns:
            工具信息列表
        """
        try:
            # 使用统一的list_tools()方法获取工具信息
            # ToolManager和ToolProxy都实现了这个方法
            tools_list = tool_manager.list_tools()

            tools_info = []
            for tool_dict in tools_list:
                tool_info = {
                    "name": tool_dict.get("name", ""),
                    "description": tool_dict.get("description", ""),
                    "parameters": tool_dict.get("parameters", {}),
                    "required": tool_dict.get("required", []),
                    "type": tool_dict.get("type", "unknown")
                }
                tools_info.append(tool_info)

            logger.debug(f"提取了 {len(tools_info)} 个工具的信息")
            return tools_info

        except Exception as e:
            logger.error(f"获取工具信息失败: {str(e)}")
            logger.error(traceback.format_exc())
            return []

    async def _generate_basic_config(self, description: str, available_tools: List[Dict], client, model: str, language: str = "en") -> Optional[Dict[str, Any]]:
        """
        生成基础配置（名称、描述、系统提示词等）

        Args:
            description: Agent描述
            available_tools: 可用工具列表
            client: 大模型客户端
            model: 模型名称

        Returns:
            dict: 基础配置，失败时返回None
        """
        try:
            # 生成工具能力摘要
            tools_summary = "\n".join([
                f"- {tool['name']}: {tool['description']}"
                for tool in available_tools
            ])

            prompt = PromptManager().get_prompt(
                "auto_gen_agent_basic_config_prompt",
                agent="common_util",
                language=language,
            ).format(description=description, tools_summary=tools_summary)

            logger.debug("调用大模型生成基础配置")
            response = await self._call_llm(client, prompt, model)

            # 解析响应
            try:
                # 提取JSON内容
                json_str = self._extract_json_from_response(response)
                logger.debug(f"提取的JSON字符串长度: {len(json_str)}")

                config = json.loads(json_str)
                required_fields = ["name", "description", "systemPrefix"]
                for field in required_fields:
                    if field not in config:
                        raise ValueError(f"缺少必需字段: {field}")

                logger.info(f"生成基础配置成功: {config['name']}")
                return config

            except json.JSONDecodeError as e:
                logger.error(f"解析大模型响应失败: {e}")
                logger.error(f"原始响应: {response}")
                logger.error(f"提取的JSON: {json_str if 'json_str' in locals() else 'N/A'}")
                # 返回默认配置
                return await self._get_default_basic_config(description, language=language)

        except Exception as e:
            logger.error(f"生成基础配置失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    async def _select_tools(self, basic_config: Dict, available_tools: List[Dict], client, model: str, language: str = "en") -> Optional[List[str]]:
        """
        根据Agent基础配置选择合适的工具

        Args:
            basic_config: Agent基础配置（包含name、description、systemPrefix）
            available_tools: 可用工具列表
            client: 大模型客户端
            model: 大模型名称

        Returns:
            选中的工具名称列表
        """
        try:
            tools_summary = "\n".join([
                f"- {tool['name']}: {tool['description']}"
                for tool in available_tools
            ])

            prompt = PromptManager().get_prompt(
                "auto_gen_agent_tool_selection_prompt",
                agent="common_util",
                language=language,
            ).format(
                name=basic_config.get("name", ""),
                description=basic_config.get("description", ""),
                systemPrefix=basic_config.get("systemPrefix", ""),
                tools_summary=tools_summary,
            )

            logger.debug("调用大模型选择工具")
            response = await self._call_llm(client, prompt, model)

            try:
                # 提取JSON内容
                json_str = self._extract_json_from_response(response)
                logger.debug(f"提取的JSON字符串长度: {len(json_str)}")

                selected_tools = json.loads(json_str)
                if not isinstance(selected_tools, list):
                    raise ValueError("响应不是数组格式")

                # 验证工具名称是否存在
                available_tool_names = [tool['name'] for tool in available_tools]
                valid_tools = [tool for tool in selected_tools if tool in available_tool_names]

                logger.info(f"选择了 {len(valid_tools)} 个工具: {valid_tools}")
                return valid_tools

            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"解析工具选择响应失败: {e}")
                logger.error(f"原始响应: {response}")
                logger.error(f"提取的JSON: {json_str if 'json_str' in locals() else 'N/A'}")
                # 返回一些基础工具
                return self._get_default_tools()

        except Exception as e:
            logger.error(f"选择工具失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    async def _generate_workflows(self, basic_config: Dict, selected_tools: List[str], client, model: str, language: str = "en") -> Optional[Dict[str, List[str]]]:
        """
        生成Agent的工作流程配置

        Args:
            basic_config: Agent基础配置（包含name、description、systemPrefix）
            selected_tools: 选中的工具列表
            client: 大模型客户端
            model: 大模型名称

        Returns:
            工作流程配置字典
        """
        try:
            tools_str = ", ".join(selected_tools)

            prompt = PromptManager().get_prompt(
                "auto_gen_agent_workflow_generation_prompt",
                agent="common_util",
                language=language,
            ).format(
                name=basic_config.get("name", ""),
                description=basic_config.get("description", ""),
                systemPrefix=basic_config.get("systemPrefix", ""),
                selected_tools=tools_str,
            )

            logger.debug("调用大模型生成工作流程")
            response = await self._call_llm(client, prompt, model)

            try:
                # 提取JSON内容
                json_str = self._extract_json_from_response(response)
                logger.debug(f"提取的JSON字符串长度: {len(json_str)}")

                workflows = json.loads(json_str)
                if not isinstance(workflows, dict):
                    raise ValueError("响应不是字典格式")

                logger.info(f"生成了 {len(workflows)} 个工作流程")
                return workflows

            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"解析工作流程响应失败: {e}")
                logger.error(f"原始响应: {response}")
                logger.error(f"提取的JSON: {json_str if 'json_str' in locals() else 'N/A'}")
                return self._get_default_workflows(language=language)

        except Exception as e:
            logger.error(f"生成工作流程失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def _assemble_config(self, basic_config: Dict, selected_tools: List[str], workflows: Dict, language: str = "en") -> Dict[str, Any]:
        """
        组装完整的Agent配置

        Args:
            basic_config: 基础配置
            selected_tools: 选中的工具
            workflows: 工作流程

        Returns:
            完整的Agent配置
        """
        try:
            max_loop_count = basic_config.get("maxLoopCount") or basic_config.get("max_loop_count")
            if max_loop_count is None:
                raise ValueError("maxLoopCount is required in generated agent config")

            config = {
                "id": str(int(time.time() * 1000)),  # 使用时间戳作为ID
                "name": basic_config.get("name", "Auto-generated Agent"),
                "description": basic_config.get("description", "Auto-generated assistant"),
                "systemPrefix": basic_config.get(
                    "systemPrefix",
                    PromptManager().get_prompt(
                        "auto_gen_agent_default_system_prefix",
                        agent="common_util",
                        language=language,
                    ),
                ),
                "deepThinking": False,
                "multiAgent": False,
                "moreSupport": False,
                "maxLoopCount": max_loop_count,
                "llmConfig": {
                    "model": "",
                    "maxTokens": "",
                    "temperature": ""
                },
                "availableTools": selected_tools,
                "systemContext": {},
                "availableWorkflows": workflows,
                "exportTime": datetime.now().isoformat() + "Z",
                "version": "1.0"
            }

            logger.info("Agent配置组装完成")
            return config

        except Exception as e:
            logger.error(f"组装配置失败: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def _extract_json_from_response(self, response: str) -> str:
        """
        从大模型响应中提取JSON内容

        Args:
            response: 大模型原始响应

        Returns:
            提取的JSON字符串
        """
        if not response:
            return ""

        # 尝试直接解析
        try:
            json.loads(response)
            return response
        except Exception:
            pass

        # 查找JSON代码块
        import re

        # 匹配 ```json ... ``` 格式，支持对象和数组
        json_pattern = r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```'
        match = re.search(json_pattern, response, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # 查找第一个完整的JSON对象
        brace_count = 0
        start_idx = -1

        for i, char in enumerate(response):
            if char == '{':
                if start_idx == -1:
                    start_idx = i
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0 and start_idx != -1:
                    json_str = response[start_idx:i+1]
                    try:
                        json.loads(json_str)
                        return json_str
                    except Exception:
                        continue

        # 查找第一个完整的JSON数组
        bracket_count = 0
        start_idx = -1

        for i, char in enumerate(response):
            if char == '[':
                if start_idx == -1:
                    start_idx = i
                bracket_count += 1
            elif char == ']':
                bracket_count -= 1
                if bracket_count == 0 and start_idx != -1:
                    json_str = response[start_idx:i+1]
                    try:
                        json.loads(json_str)
                        return json_str
                    except Exception:
                        continue

        # 如果都失败了，返回原始响应
        return response

    async def _call_llm(self, client, prompt: str, model: str) -> str:
        """
        调用大模型API

        Args:
            client: 大模型客户端
            prompt: 提示词
            model: 大模型名称

        Returns:
            大模型响应
        """
        try:
            logger.debug(f"调用大模型，客户端类型: {type(client)}")
            logger.debug(f"使用模型: {model}")
            logger.debug(f"提示词长度: {len(prompt)}")

            # 检查客户端是否有model属性，如果有则使用客户端的model
            actual_model = model
            if hasattr(client, 'model') and client.model:
                actual_model = client.model
                logger.debug(f"使用客户端设置的模型: {actual_model}")

            # 检查客户端类型，使用标准的OpenAI API调用方式
            if hasattr(client, 'chat') and hasattr(client.chat, 'completions'):
                logger.debug("使用OpenAI标准API调用")
                # OpenAI客户端，使用标准调用方式
                response = await client.chat.completions.create(
                    model=actual_model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=2000,
                    temperature=0.7
                )
                result = response.choices[0].message.content
                logger.debug(f"大模型响应长度: {len(result) if result else 0}")
                return result
            elif hasattr(client, 'chat'):
                logger.debug("使用chat方法调用")
                # 其他类型的chat客户端
                response = client.chat(prompt)
                result = str(response)
                logger.debug(f"大模型响应长度: {len(result)}")
                return result
            elif hasattr(client, 'complete'):
                logger.debug("使用complete方法调用")
                # complete方法的客户端
                response = client.complete(prompt)
                result = str(response)
                logger.debug(f"大模型响应长度: {len(result)}")
                return result
            elif hasattr(client, 'generate'):
                logger.debug("使用generate方法调用")
                # generate方法的客户端
                response = client.generate(prompt)
                result = str(response)
                logger.debug(f"大模型响应长度: {len(result)}")
                return result
            else:
                logger.debug("使用默认OpenAI格式调用")
                # 默认尝试OpenAI格式
                response = client.chat.completions.create(
                    model=actual_model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=2000,
                    temperature=0.7
                )
                result = response.choices[0].message.content
                logger.debug(f"大模型响应长度: {len(result) if result else 0}")
                return result or ""

        except Exception as e:
            logger.error(f"调用大模型失败: {str(e)}")
            logger.error(f"客户端类型: {type(client)}")
            logger.error(f"模型: {model}")
            logger.error(traceback.format_exc())
            raise

    async def _get_default_basic_config(self, description: str, language: str = "en") -> Dict[str, Any]:
        """获取默认的基础配置"""
        default_texts = {
            "zh": ("自动助手", "基于描述自动生成的助手"),
            "en": ("Auto Assistant", "Auto-generated assistant based on the description"),
            "pt": ("Assistente Automático", "Assistente gerado automaticamente com base na descrição"),
        }
        name, desc = default_texts.get(language, default_texts["en"])
        return {
            "name": name,
            "description": desc,
            "systemPrefix": PromptManager().get_prompt(
                "auto_gen_agent_default_basic_config_system_prefix",
                agent="common_util",
                language=language,
            ),
        }

    def _get_default_tools(self) -> List[str]:
        """获取默认工具列表"""
        return [
            "complete_task",
            "calculate",
            "file_read",
            "file_write",
            "search_web_page",
            "search_image_from_web"
        ]

    def _get_default_workflows(self, language: str = "en") -> Dict[str, List[str]]:
        """获取默认工作流程"""
        defaults = {
            "zh": {
                "信息检索流程": [
                    "接收用户请求",
                    "分析查询范围和需求",
                    "使用相关工具收集信息",
                    "整理并总结结果",
                    "向用户给出清晰答案",
                ],
                "任务执行流程": [
                    "理解用户的任务需求",
                    "制定执行计划",
                    "调用合适工具完成任务",
                    "验证执行结果",
                    "向用户汇报完成情况",
                ],
            },
            "en": {
                "Information lookup flow": [
                    "Receive the user's request",
                    "Analyze the query scope and requirements",
                    "Use the relevant tools to gather information",
                    "Organize and summarize the findings",
                    "Provide a clear answer to the user",
                ],
                "Task execution flow": [
                    "Understand the user's task requirements",
                    "Draft an execution plan",
                    "Invoke the appropriate tools to perform the task",
                    "Verify the execution result",
                    "Report completion to the user",
                ],
            },
            "pt": {
                "Fluxo de busca de informações": [
                    "Receber a solicitação do usuário",
                    "Analisar o escopo e os requisitos da consulta",
                    "Usar as ferramentas relevantes para coletar informações",
                    "Organizar e resumir os resultados",
                    "Fornecer uma resposta clara ao usuário",
                ],
                "Fluxo de execução de tarefas": [
                    "Entender os requisitos da tarefa do usuário",
                    "Elaborar um plano de execução",
                    "Invocar as ferramentas apropriadas para executar a tarefa",
                    "Verificar o resultado da execução",
                    "Informar a conclusão ao usuário",
                ],
            },
        }
        return defaults.get(language, defaults["en"])

    def save_config_to_file(self, config: Dict[str, Any], file_path: str) -> Optional[str]:
        """
        将配置保存到文件

        Args:
            config: Agent配置字典
            file_path: 保存路径

        Returns:
            保存成功时返回文件路径，失败时返回None
        """
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

            logger.info(f"配置已保存到: {file_path}")
            return file_path

        except Exception as e:
            logger.error(f"保存配置失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None


# 使用示例
if __name__ == "__main__":
    # 示例用法
    from sagents.tool.tool_manager import ToolManager

    # 创建工具管理器
    tool_manager = ToolManager()

    # 创建自动生成器
    auto_gen = AutoGenAgentFunc()

    # 生成配置（需要提供大模型客户端和模型名称）
    description = "创建一个销售助手，能够查询客户信息，分析客户需求，提供销售建议"

    # config = auto_gen.generate_agent_config(description, tool_manager, llm_client, "gpt-4")
    # auto_gen.save_config_to_file(config, "generated_agent_config.json")

    print("AutoGenAgentFunc工具类已创建完成")
