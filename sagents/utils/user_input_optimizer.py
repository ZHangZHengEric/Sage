"""
用户输入优化工具类
"""

from __future__ import annotations

import traceback
from datetime import datetime
from typing import Any, Dict, List

from sagents.utils.logger import logger


class UserInputOptimizer:
    """将用户输入整理成更清晰的请求。"""

    async def optimize_user_input(
        self,
        current_input: str,
        history_messages: List[Dict[str, str]],
        llm_client: Any,
        model: str,
    ) -> Dict[str, Any]:
        try:
            prompt = self._build_prompt(current_input=current_input, history_messages=history_messages)
            optimized_input = (await self._call_llm(llm_client, prompt, model)).strip()

            if not optimized_input:
                return self._fallback_result(current_input)

            return {
                "success": True,
                "optimized_input": optimized_input,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception as exc:
            logger.error(f"优化用户输入时发生错误: {exc}")
            logger.error(traceback.format_exc())
            return self._fallback_result(
                current_input,
                error_message=str(exc),
                error_type=type(exc).__name__,
            )

    def _build_prompt(self, current_input: str, history_messages: List[Dict[str, str]]) -> str:
        history_lines: List[str] = []
        for message in history_messages or []:
            role = (message.get("role") or "assistant").strip()
            content = (message.get("content") or "").strip()
            if not content:
                continue
            history_lines.append(f"[{role}] {content}")

        history_text = "\n".join(history_lines) if history_lines else "无"

        return f"""你是一个“用户意图整理与任务成型助手”。

你的任务不是简单润色，而是基于最近对话上下文，准确理解用户真正想让 agent 做什么，并将当前输入整理成一个更完整、更明确、更可执行的正式请求。

你的输出应当帮助后续 agent 立即进入执行，而不是还需要再次猜测用户意图。

请遵守以下规则：
1. 严格保留用户原始意图，不要杜撰用户没有表达过的新需求。
2. 如果上下文已经明确了对象、文件、代码位置、目标、限制条件、偏好、验收标准、输出形式，请自然补全到请求里。
3. 如果用户表达模糊，你可以根据上下文把隐含意图说清楚，但只能做高置信度补全，不能擅自扩展任务范围。
4. 让请求尽量包含这些关键信息中的已知部分：
   - 要做什么
   - 为什么做 / 目标是什么
   - 作用对象是什么（文件、模块、页面、功能、数据、环境等）
   - 约束或注意事项是什么
   - 用户期望最终输出什么结果
5. 如果用户其实是在请求 agent 继续上一个任务、修复某个问题、补齐某项实现、调整某个行为，要把这种“后续动作意图”明确表达出来。
6. 如果用户已经说得很清楚，只做轻微增强，让表达更完整、更利于执行。
7. 保持用户原本使用的语言和语气，不要切换语言。
8. 不要输出解释、分析过程、前言、标题、项目符号或备注。
9. 只输出一段可直接发送给 agent 的“优化后用户请求正文”。

最近对话上下文：
{history_text}

当前用户输入：
{current_input}
"""

    async def _call_llm(self, client: Any, prompt: str, model: str) -> str:
        if hasattr(client, "chat"):
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=800,
            )
            return response.choices[0].message.content or ""

        if hasattr(client, "generate"):
            return client.generate(prompt, model=model) or ""

        logger.error("不支持的LLM客户端类型")
        return ""

    def _fallback_result(
        self,
        current_input: str,
        error_message: str = "",
        error_type: str = "",
    ) -> Dict[str, Any]:
        return {
            "success": False,
            "optimized_input": current_input,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "fallback",
            "error_message": error_message,
            "error_type": error_type,
        }
