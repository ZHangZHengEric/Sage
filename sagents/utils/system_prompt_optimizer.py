"""
Agent系统指令优化工具类

该模块提供了优化Agent系统指令的功能，包括：
- 解析现有的系统指令内容
- 使用大模型优化指令的语言表达和结构
- 按照标准markdown格式输出优化后的系统指令
- 支持角色、技能、偏好、限制等标准化结构

作者: Eric ZZ
创建时间: 2025-01-28
"""

import json
import re
import traceback
from typing import Dict, Any, List, Optional, Union
from datetime import datetime

try:
    from sagents.utils.logger import logger
except ImportError:
    from logger import logger


class SystemPromptOptimizer:
    """Agent系统指令优化工具类"""

    def __init__(self):
        """
        初始化SystemPromptOptimizer
        """
        logger.info("SystemPromptOptimizer initialized")

        # 标准化的markdown模板结构
        self.standard_template = {
            "role": "## 角色",
            "skills": "## 技能",
            "preferences": "## 偏好或者指导",
            "tool_guidance": "### 工具使用指导",
            "content_preference": "### 结果内容偏好",
            "format_preference": "### 结果形式偏好",
            "terminology": "### 特殊名词定义",
            "constraints": "## 限制"
        }

    async def optimize_system_prompt(
        self,
        current_prompt: str,
        llm_client,
        model: str = "gpt-3.5-turbo",
        optimization_goal: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        优化系统指令

        Args:
            current_prompt: 当前的系统指令内容
            llm_client: 大模型客户端
            model: 大模型名称，默认为gpt-3.5-turbo
            optimization_goal: 优化目标，指定优化的方向和重点，可选

        Returns:
            Dict包含：
            - optimized_prompt: 优化后的markdown格式系统指令
            - analysis: 优化分析报告
            - sections: 各个部分的内容字典
        """
        try:
            logger.info("开始优化系统指令")

            # 1. 分析当前指令内容
            analysis = await self._analyze_current_prompt(current_prompt, llm_client, model, optimization_goal)
            logger.info("完成当前指令分析")

            # 2. 生成优化后的各个部分（默认使用分段生成，更精确）
            try:
                sections = await self._generate_optimized_sections_segmented(
                    current_prompt, analysis, llm_client, model, optimization_goal
                )
                logger.info("完成分段内容生成")
            except Exception as e:
                logger.warning(f"分段生成失败，尝试整体生成: {str(e)}")
                sections = await self._generate_optimized_sections(
                    current_prompt, analysis, llm_client, model, optimization_goal
                )
                logger.info("完成整体内容生成")

            # 3. 格式化为markdown
            optimized_prompt = self._format_to_markdown(sections)
            logger.info("完成markdown格式化")

            result = {
                "success": True,
                "optimized_prompt": optimized_prompt,
                "analysis": analysis,
                "sections": sections,
                "timestamp": datetime.now().isoformat()
            }

            logger.info("系统指令优化完成")
            return result

        except Exception as e:
            logger.error(f"优化系统指令时发生错误: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                "success": False,
                "error": str(e),
                "message": "系统指令优化失败",
                "timestamp": datetime.now().isoformat()
            }

    async def _analyze_current_prompt(self, prompt: str, client, model: str, optimization_goal: Optional[str] = None) -> Dict[str, Any]:
        """
        分析当前系统指令的内容和结构

        Args:
            prompt: 当前系统指令
            client: LLM客户端
            model: 模型名称
            optimization_goal: 优化目标，可选

        Returns:
            分析结果字典
        """
        try:
            # 构建分析提示词，如果有优化目标则加入相关指导
            optimization_guidance = ""
            if optimization_goal:
                optimization_guidance = f"""

特别注意：本次优化的目标是：{optimization_goal}
请在分析时特别关注与此目标相关的内容，并在分析结果中重点标注需要针对此目标进行改进的地方。
"""

            analysis_prompt = f"""
请分析以下Agent系统指令的内容和结构，识别出其中包含的信息：

当前系统指令：
{prompt}
{optimization_guidance}
请从以下维度进行分析：
1. 角色定义：Agent扮演什么角色
2. 核心技能：Agent具备哪些能力
3. 工作偏好：Agent的工作方式和偏好
4. 工具使用：是否涉及工具使用指导
5. 输出要求：对结果内容和形式的要求
6. 限制条件：Agent需要遵守的限制
7. 特殊术语：是否有特定领域的术语定义
8. 语言问题：表达不清晰或可以改进的地方

请以JSON格式返回分析结果：
{{
    "role_info": "角色相关信息",
    "skills_info": "技能相关信息", 
    "preferences_info": "偏好相关信息",
    "tool_info": "工具使用相关信息",
    "output_requirements": "输出要求相关信息",
    "constraints_info": "限制条件相关信息",
    "terminology_info": "特殊术语相关信息",
    "language_issues": "语言表达问题和改进建议"
}}
"""

            response = await self._call_llm(client, analysis_prompt, model)
            analysis_json = self._extract_json_from_response(response)

            if analysis_json:
                return json.loads(analysis_json)
            else:
                logger.warning("无法解析分析结果，使用默认分析")
                return self._get_default_analysis(prompt)

        except Exception as e:
            logger.error(f"分析当前指令时发生错误: {str(e)}")
            logger.error(traceback.format_exc())
            return self._get_default_analysis(prompt)

    async def _generate_optimized_sections(
        self,
        original_prompt: str,
        analysis: Dict[str, Any],
        client,
        model: str,
        optimization_goal: Optional[str] = None
    ) -> Dict[str, str]:
        """
        生成优化后的各个部分内容

        Args:
            original_prompt: 原始指令
            analysis: 分析结果
            client: LLM客户端
            model: 模型名称
            optimization_goal: 优化目标，可选

        Returns:
            各部分内容字典
        """
        try:
            # 构建优化目标指导
            optimization_guidance = ""
            if optimization_goal:
                optimization_guidance = f"""

优化目标：{optimization_goal}
请在生成各个部分时特别关注此优化目标，确保生成的内容能够更好地满足这个目标。
"""

            sections_prompt = f"""
请对以下原始指令进行结构化整理，只能重新组织和改善表述，绝对不能添加任何新内容。

原始指令：
{original_prompt}

分析结果：
{json.dumps(analysis, ensure_ascii=False, indent=2)}
{optimization_guidance}

**严格要求**：
1. **只能重新组织原有内容**：不得添加任何原始指令中没有明确提到的信息
2. **禁止编造任何内容**：包括但不限于新的功能、限制、术语、数字、时间限制等
3. **完全保留原始细节**：所有具体的名词、数字、规则必须原样保留
4. **不得扩展或推理**：不能基于原始内容进行任何推理或扩展

**处理规则**：
- 如果原始指令中没有某个部分的内容，该部分应该为空或简短
- 只能改善语言表述的清晰度，不能改变含义
- 不能添加任何示例、解释或补充说明
- 不能添加任何原始指令中没有的专业术语或概念

请严格按照原始指令内容整理各个部分：

1. **角色部分**：仅重新表述原始指令中的角色描述
2. **技能部分**：仅列出原始指令中明确提到的技能（如果没有则简短）
3. **工具使用指导**：仅包含原始指令中的工具使用要求（如果没有则为空）
4. **结果内容偏好**：仅包含原始指令中的内容要求（如果没有则为空）
5. **结果形式偏好**：仅包含原始指令中的格式要求（如果没有则为空）
6. **特殊名词定义**：仅包含原始指令中已定义的术语（如果没有则为空）
7. **限制部分**：仅包含原始指令中的限制和禁止事项（如果没有则为空）

请以JSON格式返回：
{{
    "role": "角色部分内容（仅基于原始指令）",
    "skills": "技能部分内容（仅原始指令中的技能）",
    "tool_guidance": "工具使用指导内容（仅原始指令中的指导，没有则为空）",
    "content_preference": "结果内容偏好内容（仅原始指令中的偏好，没有则为空）",
    "format_preference": "结果形式偏好内容（仅原始指令中的格式要求，没有则为空）",
    "terminology": "特殊名词定义内容（仅原始指令中的定义，没有则为空）",
    "constraints": "限制部分内容（仅原始指令中的限制，没有则为空）"
}}
"""

            response = await self._call_llm(client, sections_prompt, model)
            sections_json = self._extract_json_from_response(response)

            if sections_json:
                parsed_sections = json.loads(sections_json)
                # 确保所有值都是字符串类型，如果是列表则转换为字符串
                normalized_sections = {}
                for key, value in parsed_sections.items():
                    if isinstance(value, list):
                        # 如果是列表，转换为markdown列表格式
                        normalized_sections[key] = self._format_list_content(value)
                    else:
                        # 如果是字符串或其他类型，转换为字符串
                        normalized_sections[key] = str(value)
                return normalized_sections
            else:
                logger.error("JSON解析失败，无法生成优化内容")
                raise ValueError("JSON解析失败，可能是生成内容过长或格式不正确")

        except Exception as e:
            logger.error(f"生成优化部分时发生错误: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    async def _generate_optimized_sections_segmented(
        self,
        original_prompt: str,
        analysis: Dict[str, Any],
        client,
        model: str,
        optimization_goal: Optional[str] = None
    ) -> Dict[str, str]:
        """
        分段生成优化后的各个部分，提高稳定性

        Args:
            original_prompt: 原始系统指令
            analysis: 分析结果
            client: LLM客户端
            model: 模型名称
            optimization_goal: 优化目标（可选）

        Returns:
            包含各部分内容的字典
        """
        try:
            logger.info("开始分段生成优化内容")
            logger.info(f"原始指令长度: {len(original_prompt)} 字符")
            logger.info(f"使用模型: {model}")
            if optimization_goal:
                logger.info(f"优化目标: {optimization_goal}")
            else:
                logger.info("使用默认优化算法（无特定目标）")

            sections = {}

            # 定义需要生成的部分 - 优化后的定义，更加明确各部分的职责
            section_definitions = {
                "role": {
                    "description": "角色定义内容（简洁明确的角色描述，说明AI的身份和主要职责）",
                    "examples": "例如：你是一个专业的数据分析师、你是一个客户服务助手等",
                    "avoid_confusion": "不要包含具体的技能列表或操作指导"
                },
                "skills": {
                    "description": "技能列表内容（无序列表格式，每项技能要具体明确，说明AI具备的专业能力）",
                    "examples": "例如：数据分析能力、客户沟通技巧、问题解决能力等",
                    "avoid_confusion": "不要包含工具使用方法或具体操作步骤"
                },
                "tool_guidance": {
                    "description": "工具使用指导内容（无序列表格式，具体说明何时使用哪些工具，以及使用的条件和方法）",
                    "examples": "例如：使用CRM工具查询客户信息、使用计算器进行数值计算等",
                    "avoid_confusion": "专注于工具的使用方法，不要包含一般性的行为要求或禁止事项"
                },
                "content_preference": {
                    "description": "结果内容偏好（无序列表格式，说明回答内容的质量标准、详细程度、专业性要求等积极的内容要求）",
                    "examples": "例如：回答要准确详细、提供具体的数据支持、包含实用的建议等",
                    "avoid_confusion": "专注于积极的内容要求，不要包含禁止性的限制条件"
                },
                "format_preference": {
                    "description": "结果形式偏好（无序列表格式，说明回答的格式要求、结构规范、展示方式等）",
                    "examples": "例如：使用表格展示数据、采用分点列举、包含标题和小结等",
                    "avoid_confusion": "专注于格式和展示方式，不要包含内容质量要求或禁止事项"
                },
                "terminology": {
                    "description": "特殊名词定义（无序列表格式，格式：术语名称：详细定义和使用说明）",
                    "examples": "例如：CRM：客户关系管理系统，用于管理客户信息和销售流程",
                    "avoid_confusion": "只包含专业术语的定义，不要包含操作指导或限制条件"
                },
                "constraints": {
                    "description": "限制和约束（无序列表格式，明确的禁止行为、边界条件、安全要求等消极限制）",
                    "examples": "例如：不要泄露客户隐私、不要提供医疗建议、不要执行危险操作等",
                    "avoid_confusion": "只包含明确的禁止事项和限制条件，不要包含积极的要求或建议"
                }
            }

            # 优化生成顺序：按照逻辑依赖关系排序
            # 1. role - 基础角色定义
            # 2. skills - 基于角色的技能
            # 3. tool_guidance - 基于技能的工具使用
            # 4. content_preference - 内容要求
            # 5. format_preference - 格式要求
            # 6. terminology - 专业术语
            # 7. constraints - 最后处理限制条件
            generation_order = ["role", "skills", "tool_guidance", "content_preference", "format_preference", "terminology", "constraints"]

            logger.info(f"计划生成 {len(generation_order)} 个部分，顺序: {generation_order}")

            # 逐个生成每个部分，后续部分可以参考已生成的部分
            for i, section_key in enumerate(generation_order, 1):
                try:
                    logger.info(f"[{i}/{len(generation_order)}] 正在生成部分: {section_key}")

                    section_info = section_definitions[section_key]

                    # 构建已生成部分的上下文信息
                    context_info = ""
                    if sections:
                        context_info = "\n\n**已生成的其他部分（供参考，避免重复内容）**：\n"
                        for existing_key, existing_content in sections.items():
                            if existing_content.strip() != "无":
                                context_info += f"- {existing_key}: {existing_content[:100]}{'...' if len(existing_content) > 100 else ''}\n"
                        context_info += "\n**请确保当前生成的内容与上述部分不重复，各部分职责明确分离。**"

                    # 构建单个部分的生成prompt
                    section_prompt = f"""
请从原始系统指令中提取并优化"{section_key}"部分的内容。

原始系统指令：
{original_prompt}

{f"优化目标：{optimization_goal}" if optimization_goal else ""}

**当前部分定义**：
{section_info['description']}

**内容示例**：
{section_info['examples']}

**避免混淆**：
{section_info['avoid_confusion']}

{context_info}

**优化要求**：
1. **内容忠实性**：只能使用原始指令中已有的信息，不能添加新的功能、限制或概念
2. **语言优化**：可以改善表述方式，使语言更清晰、更专业、更有条理
3. **结构优化**：可以重新组织内容结构，使逻辑更清晰
4. **保留细节**：所有具体的名词、数字、规则必须原样保留
5. **职责分离**：严格按照当前部分的定义提取内容，不要包含其他部分的内容

**允许的优化**：
- 改善语言表述的清晰度和专业性
- 调整句式结构，使表达更流畅
- 重新组织内容顺序，使逻辑更清晰
- 统一术语使用，保持一致性
- 优化格式，使内容更易读

**严格禁止**：
- 添加原始指令中没有的新信息
- 编造具体的数字、名称或规则
- 添加新的功能要求或限制条件
- 推理或扩展原始内容的含义
- 包含其他部分应该包含的内容

**特别注意**：
- 如果原始指令中没有明确的"{section_key}"相关内容，请返回"无"
- 不要将其他部分的内容错误归类到当前部分
- 严格按照部分定义的职责范围提取内容

**重要输出要求**：
- 直接输出优化后的内容，不要添加任何说明文字
- 不要包含"以下是优化后的..."、"内容如下："等描述性前缀
- 不要包装在JSON对象中
- 不要添加任何解释或说明
- 只输出纯粹的内容本身

示例：
错误输出：以下是优化后的"{section_key}"内容：
- **具体内容**

正确输出：
- **具体内容**
"""

                    logger.info(f"[{section_key}] 发送prompt长度: {len(section_prompt)} 字符")

                    response = await self._call_llm(client, section_prompt, model)

                    logger.info(f"[{section_key}] 收到响应长度: {len(response)} 字符")

                    # 清理响应内容 - 移除多余的描述性文字
                    content = self._clean_response_content(response.strip(), section_key)

                    # 记录原始响应内容（截取前200字符用于日志）
                    content_preview = content[:200] + "..." if len(content) > 200 else content
                    logger.info(f"[{section_key}] 清理后内容预览: {content_preview}")

                    # 如果内容看起来像JSON数组，尝试解析
                    if content.startswith('[') and content.endswith(']'):
                        try:
                            parsed_content = json.loads(content)
                            if isinstance(parsed_content, list):
                                logger.info(f"[{section_key}] 检测到JSON数组格式，转换为markdown列表")
                                content = self._format_list_content(parsed_content)
                        except json.JSONDecodeError:
                            logger.warning(f"[{section_key}] JSON解析失败，保持原内容")
                            # 如果解析失败，保持原内容
                            pass

                    sections[section_key] = content

                    # 记录最终内容状态
                    if content.strip() == "无":
                        logger.info(f"[{section_key}] ✓ 完成生成 - 原始指令中无相关内容")
                    else:
                        logger.info(f"[{section_key}] ✓ 完成生成 - 最终内容长度: {len(content)} 字符")

                except Exception as e:
                    logger.error(f"[{section_key}] ❌ 生成失败: {str(e)}")
                    logger.error(traceback.format_exc())
                    # 如果单个部分失败，使用默认内容
                    sections[section_key] = f"[{section_key}部分生成失败，请手动编辑]"
                    logger.warning(f"[{section_key}] 使用默认错误内容")

            # 统计生成结果
            successful_sections = [k for k, v in sections.items() if not v.startswith("[") and not v.endswith("失败，请手动编辑]")]
            empty_sections = [k for k, v in sections.items() if v.strip() == "无"]
            failed_sections = [k for k, v in sections.items() if v.startswith("[") and v.endswith("失败，请手动编辑]")]

            logger.info("=" * 50)
            logger.info("分段生成完成 - 统计结果:")
            logger.info(f"✓ 成功生成: {len(successful_sections)} 个部分 {successful_sections}")
            logger.info(f"○ 内容为空: {len(empty_sections)} 个部分 {empty_sections}")
            logger.info(f"❌ 生成失败: {len(failed_sections)} 个部分 {failed_sections}")
            logger.info("=" * 50)

            return sections

        except Exception as e:
            logger.error(f"分段生成优化部分时发生错误: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def _format_to_markdown(self, sections: Dict[str, str]) -> str:
        """
        将各部分内容格式化为标准markdown格式

        Args:
            sections: 各部分内容字典

        Returns:
            格式化后的markdown字符串
        """
        try:
            markdown_parts = []

            # 角色部分 - 保持段落格式
            if sections.get("role"):
                markdown_parts.append(f"{self.standard_template['role']}\n\n{sections['role']}")

            # 技能部分 - 转换为列表格式
            if sections.get("skills"):
                skills_content = self._format_list_content(sections['skills'])
                markdown_parts.append(f"{self.standard_template['skills']}\n\n{skills_content}")

            # 偏好或者指导部分
            markdown_parts.append(f"{self.standard_template['preferences']}")

            # 工具使用指导 - 转换为列表格式
            if sections.get("tool_guidance"):
                tool_guidance_content = self._format_list_content(sections['tool_guidance'])
                markdown_parts.append(f"{self.standard_template['tool_guidance']}\n\n{tool_guidance_content}")

            # 结果内容偏好 - 转换为列表格式
            if sections.get("content_preference"):
                content_preference_content = self._format_list_content(sections['content_preference'])
                markdown_parts.append(f"{self.standard_template['content_preference']}\n\n{content_preference_content}")

            # 结果形式偏好 - 转换为列表格式
            if sections.get("format_preference"):
                format_preference_content = self._format_list_content(sections['format_preference'])
                markdown_parts.append(f"{self.standard_template['format_preference']}\n\n{format_preference_content}")

            # 特殊名词定义 - 转换为列表格式
            if sections.get("terminology"):
                terminology_content = self._format_list_content(sections['terminology'])
                markdown_parts.append(f"{self.standard_template['terminology']}\n\n{terminology_content}")

            # 限制部分 - 转换为列表格式
            if sections.get("constraints"):
                constraints_content = self._format_list_content(sections['constraints'])
                markdown_parts.append(f"{self.standard_template['constraints']}\n\n{constraints_content}")

            return "\n\n".join(markdown_parts)

        except Exception as e:
            logger.error(f"格式化markdown时发生错误: {str(e)}")
            logger.error(traceback.format_exc())
            return self._get_fallback_markdown(sections)

    def _format_list_content(self, content) -> str:
        """
        将内容转换为markdown列表格式

        Args:
            content: 原始内容（可能是字符串、列表或字符串数组格式）

        Returns:
            格式化后的markdown列表
        """
        try:
            # 如果直接是列表类型
            if isinstance(content, list):
                cleaned_items = []
                for item in content:
                    cleaned_item = str(item).strip()
                    if cleaned_item.startswith('- '):
                        cleaned_item = cleaned_item[2:]
                    cleaned_items.append(f"- {cleaned_item}")
                return '\n'.join(cleaned_items)

            # 如果是字符串，尝试解析为JSON数组
            if isinstance(content, str):
                if content.strip().startswith('[') and content.strip().endswith(']'):
                    items = json.loads(content)
                    if isinstance(items, list):
                        # 清理每个项目，移除开头的"- "
                        cleaned_items = []
                        for item in items:
                            cleaned_item = str(item).strip()
                            if cleaned_item.startswith('- '):
                                cleaned_item = cleaned_item[2:]
                            cleaned_items.append(f"- {cleaned_item}")
                        return '\n'.join(cleaned_items)

                # 如果不是JSON数组格式，直接返回原内容
                return content

            # 其他类型转换为字符串
            return str(content)

        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"格式化列表内容时发生错误: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            # 如果解析失败，尝试转换为字符串返回
            return str(content)

    def _clean_response_content(self, content: str, section_key: str) -> str:
        """
        清理LLM响应内容，移除多余的描述性文字

        Args:
            content: 原始响应内容
            section_key: 当前处理的部分键名

        Returns:
            清理后的内容
        """
        try:
            # 移除常见的描述性前缀
            patterns_to_remove = [
                r'^以下是优化后的.*?：\s*',
                r'^优化后的.*?内容.*?：\s*',
                r'^.*?内容如下.*?：\s*',
                r'^.*?内容（.*?格式）.*?：\s*',
                r'^根据.*?，.*?内容.*?：\s*',
                r'^提取.*?内容.*?：\s*',
                r'^.*?部分的内容.*?：\s*',
                r'^.*?格式.*?：\s*',
                r'^以下.*?：\s*',
                r'^内容：\s*',
                r'^结果：\s*',
                r'^答案：\s*'
            ]

            cleaned_content = content

            # 逐个应用清理模式
            for pattern in patterns_to_remove:
                cleaned_content = re.sub(pattern, '', cleaned_content, flags=re.IGNORECASE | re.MULTILINE)

            # 移除开头的空行
            cleaned_content = cleaned_content.lstrip('\n\r ')

            # 如果清理后内容为空，返回原内容
            if not cleaned_content.strip():
                logger.warning(f"[{section_key}] 内容清理后为空，保持原内容")
                return content

            # 记录清理效果
            if cleaned_content != content:
                logger.info(f"[{section_key}] 已清理描述性前缀，原长度: {len(content)}, 清理后: {len(cleaned_content)}")

            return cleaned_content

        except Exception as e:
            logger.error(f"[{section_key}] 清理响应内容时发生错误: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            # 如果清理失败，返回原内容
            return content

    async def _call_llm(self, client, prompt: str, model: str) -> str:
        """
        调用大模型API

        Args:
            client: LLM客户端
            prompt: 提示词
            model: 模型名称

        Returns:
            模型响应
        """
        try:
            logger.debug(f"准备调用LLM - 模型: {model}, prompt长度: {len(prompt)} 字符")

            # 根据不同的客户端类型调用相应的方法
            if hasattr(client, 'chat'):
                # OpenAI风格的客户端
                logger.debug("使用OpenAI风格客户端调用")
                response = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=2000
                )
                result = response.choices[0].message.content
                logger.debug(f"LLM响应成功 - 响应长度: {len(result)} 字符")
                return result
            elif hasattr(client, 'generate'):
                # 其他类型的客户端
                logger.debug("使用generate方法调用")
                response = client.generate(prompt, model=model)
                logger.debug(f"LLM响应成功 - 响应长度: {len(response)} 字符")
                return response
            else:
                logger.error("不支持的LLM客户端类型")
                return ""

        except Exception as e:
            logger.error(f"调用LLM时发生错误: {str(e)}")
            logger.error(traceback.format_exc())
            return ""

    def _extract_json_from_response(self, response: str) -> Optional[str]:
        """
        从LLM响应中提取JSON内容

        Args:
            response: LLM响应文本

        Returns:
            提取的JSON字符串，如果提取失败返回None
        """
        try:
            # 尝试多种JSON提取模式
            patterns = [
                r'```json\s*(\{.*?\})\s*```',  # ```json {...} ```
                r'```\s*(\{.*?\})\s*```',      # ``` {...} ```
                r'(\{.*?\})',                   # 直接的JSON对象
            ]

            for pattern in patterns:
                matches = re.findall(pattern, response, re.DOTALL)
                if matches:
                    json_str = matches[0].strip()
                    # 验证JSON格式
                    json.loads(json_str)
                    return json_str

            logger.warning("无法从响应中提取有效的JSON")
            return None

        except Exception as e:
            logger.error(f"提取JSON时发生错误: {str(e)}")
            return None

    def _get_default_analysis(self, prompt: str) -> Dict[str, Any]:
        """
        获取默认的分析结果

        Args:
            prompt: 原始指令

        Returns:
            默认分析结果
        """
        return {
            "role_info": "从原始指令中提取的角色信息",
            "skills_info": "从原始指令中提取的技能信息",
            "preferences_info": "从原始指令中提取的偏好信息",
            "tool_info": "工具使用相关信息",
            "output_requirements": "输出要求信息",
            "constraints_info": "限制条件信息",
            "terminology_info": "特殊术语信息",
            "language_issues": "需要优化语言表达的清晰度和准确性"
        }

    def _get_default_sections(self, analysis: Dict[str, Any]) -> Dict[str, str]:
        """
        获取默认的部分内容

        Args:
            analysis: 分析结果

        Returns:
            默认部分内容
        """
        return {
            "role": "您是一个专业的AI助手，具备丰富的知识和经验，致力于为用户提供高质量的服务和支持。",
            "skills": "- 信息分析和处理能力\n- 问题解决和建议提供\n- 专业知识应用和解释\n- 逻辑推理和判断能力",
            "tool_guidance": "- 根据任务需求合理选择和使用可用工具\n- 确保工具使用的准确性和效率\n- 优先使用工具获取的真实信息，避免编造内容",
            "content_preference": "- 提供准确、相关、有价值的信息和建议\n- 确保内容的专业性和实用性\n- 保持信息的时效性和可靠性",
            "format_preference": "- 使用清晰的结构化格式\n- 包括适当的标题、列表和段落组织\n- 确保内容易读易懂",
            "terminology": "- 根据具体领域定义相关专业术语\n- 提供清晰的术语解释和说明",
            "constraints": "- 确保信息的准确性和可靠性\n- 遵循用户的具体要求和偏好\n- 保持专业和友好的交流方式\n- 避免提供可能有害或不当的内容"
        }

    def _get_fallback_result(self, original_prompt: str) -> Dict[str, Any]:
        """
        获取备用结果（当优化失败时）

        Args:
            original_prompt: 原始指令

        Returns:
            备用结果
        """
        return {
            "optimized_prompt": original_prompt,
            "analysis": {"error": "分析失败，返回原始内容"},
            "sections": {"error": "生成失败"},
            "timestamp": datetime.now().isoformat(),
            "status": "fallback"
        }

    def _get_fallback_markdown(self, sections: Dict[str, str]) -> str:
        """
        获取备用markdown格式（当格式化失败时）

        Args:
            sections: 部分内容

        Returns:
            备用markdown字符串
        """
        return f"""## 角色

{sections.get('role', '角色信息')}

## 技能

{sections.get('skills', '技能信息')}

## 偏好或者指导

### 工具使用指导

{sections.get('tool_guidance', '工具使用指导')}

### 结果内容偏好

{sections.get('content_preference', '结果内容偏好')}

### 结果形式偏好

{sections.get('format_preference', '结果形式偏好')}

### 特殊名词定义

{sections.get('terminology', '特殊名词定义')}

## 限制

{sections.get('constraints', '限制条件')}"""

    def save_optimized_prompt(self, result: Dict[str, Any], file_path: str) -> str:
        """
        保存优化后的系统指令到文件

        Args:
            result: 优化结果
            file_path: 保存路径

        Returns:
            保存状态信息
        """
        try:
            # 保存markdown格式的优化指令
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(result['optimized_prompt'])

            logger.info(f"优化结果已保存到: {file_path}")
            return f"成功保存到 {file_path}"

        except Exception as e:
            logger.error(f"保存文件时发生错误: {str(e)}")
            return f"保存失败: {str(e)}"


if __name__ == "__main__":
    # 测试用例
    optimizer = SystemPromptOptimizer()

    # 示例系统指令
    test_prompt = """
    你是一个销售助手，帮助用户查询客户信息和分析销售数据。
    你需要使用CRM工具来获取客户信息，使用数据分析工具来分析销售趋势。
    回答要准确，格式要清晰。不要泄露客户隐私信息。
    """

    print("SystemPromptOptimizer工具类已创建完成")
    print(f"测试指令: {test_prompt}")
