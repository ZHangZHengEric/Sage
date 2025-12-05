import json
from openai import AsyncOpenAI
import yaml
import asyncio
from typing import Dict, Any
import re
from ..logger import logger


class BaseAgentProcessor:
    """基础代理处理器类，包含公共的API调用、文件操作和日志功能"""
    def __init__(
        self,
        api_key: str,
        base_url: str,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.total_tokens = 0

    async def call_qianxun(
        self,
        prompt,
        model_name: str = "qianxun-m9500",
        r_format: str = "text",
        max_tokens: int = 15000,
        temperature: float = 0.0001,
        top_p: float = 0.9,
        timeout: float = 1000,
    ) -> str:

        max_retries = 3

        for attempt in range(max_retries):
            try:
                if isinstance(prompt, list):
                    full_prompt = prompt
                else:
                    full_prompt = [{"role": "user", "content": prompt}]

                response = await self.client.chat.completions.create(
                    response_format={"type": r_format},
                    model=model_name,
                    messages=full_prompt,
                    temperature=temperature,
                    timeout=timeout,
                    max_tokens=max_tokens,
                    top_p=top_p,
                )
                break  # 成功则跳出

            except Exception as e:
                logger.warning(
                    f"API调用失败 (第 {attempt + 1} 次): {str(e)}", exc_info=True)
                if attempt == max_retries - 1:
                    logger.error("最终重试失败，放弃请求。", exc_info=True)
                    raise
                await asyncio.sleep(4)
        self.total_tokens += response.usage.total_tokens
        return response.choices[0].message.content

    def get_total_tokens(self) -> int:
        """获取总token数"""
        return self.total_tokens

    def read_yaml_file(self, file_path: str) -> Dict[str, Any]:
        """读取YAML文件"""
        with open(file_path, 'r', encoding='utf-8') as file:
            content = yaml.safe_load(file)
        return content
    
    def read_json_file(self, file_path: str) -> Dict[str, Any]:
        """读取JSON文件"""
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def parse_json_response(self, response: str) -> Any:
        """解析评估响应（兼容旧版本）"""
        # 第一步：尝试提取 ```json ... ``` 中的内容
        json_match = re.search(r'```json(.*?)```', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                logger.warning(f"解析 ```json 块失败: {json_match.group(1)}")

        # 第二步：如果没有找到 ```json 块，尝试将整个 response 当作 JSON 解析
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            logger.warning(f"解析完整响应为 JSON 失败: {response}")

        # 第三步：所有解析都失败，返回原始字符串
        return response
