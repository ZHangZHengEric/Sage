import copy
import json
import re
from typing import Any, Dict, Union

from loguru import logger


class ContentProcessor:
    BASE64_PATTERN = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+")

    @classmethod
    def clean_content(cls, result: Dict[str, Any]) -> Dict[str, Any]:
        """Return a display-safe copy. Never mutate the caller's message dict.

        Tool results are decoded to objects for SSE/history clients. Ledger
        persistence and LLM request conversion stringify dicts separately so
        OpenAI-compatible gateways still receive string content.
        """
        result = copy.deepcopy(result)
        if result.get("role") == "tool":
            content = result.get("content")
            if isinstance(content, dict):
                cls._truncate_large_fields(content)
                cls._remove_base64_from_results(content)
                result["content"] = content
            elif isinstance(content, str):
                result["content"] = cls._process_tool_content(content)
        return result

    @classmethod
    def _remove_base64_from_results(cls, data: Any) -> bool:
        modified = False
        if (
            isinstance(data, dict)
            and "results" in data
            and isinstance(data["results"], list)
        ):
            for item in data["results"]:
                if isinstance(item, dict) and "image" in item:
                    val = item["image"]
                    if isinstance(val, str) and val.startswith("data:image"):
                        item["image"] = "[BASE64_IMAGE_REMOVED_FOR_DISPLAY]"
                        modified = True
        return modified

    @classmethod
    def _process_tool_content(cls, content_str: str) -> Union[str, Dict[str, Any]]:
        if not content_str.strip().startswith("{"):
            return content_str

        try:
            data = json.loads(content_str)
        except json.JSONDecodeError as e:
            logger.warning(f"解析工具结果JSON失败: {e}")
            return content_str

        if not isinstance(data, dict):
            return content_str

        data = cls._flatten_nested_json(data)
        cls._truncate_large_fields(data)
        cls._remove_base64_from_results(data)
        return data

    @classmethod
    def _flatten_nested_json(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(data, dict) and "content" in data:
            inner = data["content"]
            if isinstance(inner, str) and inner.strip().startswith("{"):
                try:
                    return json.loads(inner)
                except json.JSONDecodeError:
                    pass
        return data

    @classmethod
    def _truncate_large_fields(cls, data: Any, max_len: int = 5000) -> None:
        if (
            isinstance(data, dict)
            and "results" in data
            and isinstance(data["results"], list)
        ):
            for item in data["results"]:
                if isinstance(item, dict):
                    for field in ["snippet", "description", "content"]:
                        val = item.get(field)
                        if isinstance(val, str) and len(val) > max_len:
                            item[field] = val[:max_len] + "...[TRUNCATED]"
