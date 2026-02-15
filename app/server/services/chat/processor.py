import json
import re
from typing import Any, Dict, Union

from loguru import logger



class ContentProcessor:
    """消息内容处理器"""
    
    BASE64_PATTERN = re.compile(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+')

    @classmethod
    def clean_content(cls, result: Dict[str, Any]) -> Dict[str, Any]:
        # 2. 处理工具调用结果（解析 JSON、扁平化、裁剪）
        if result.get('role') == 'tool':
            content = result.get('content')
            if isinstance(content, str):
                result['content'] = cls._process_tool_content(content)
        
        return result


    @classmethod
    def _remove_base64_from_results(cls, data: Any) -> bool:
        """从结果列表中移除 Base64 图片，返回是否有修改"""
        modified = False
        if isinstance(data, dict) and 'results' in data and isinstance(data['results'], list):
            for item in data['results']:
                if isinstance(item, dict) and 'image' in item:
                    val = item['image']
                    if isinstance(val, str) and val.startswith('data:image'):
                        item['image'] = '[BASE64_IMAGE_REMOVED_FOR_DISPLAY]'
                        modified = True
        return modified

    @classmethod
    def _process_tool_content(cls, content_str: str) -> Union[str, Dict[str, Any]]:
        """处理工具返回的内容：解析 JSON、扁平化嵌套、裁剪大字段"""
        if not content_str.strip().startswith('{'):
            return content_str
        
        try:
            data = json.loads(content_str)
        except json.JSONDecodeError as e:
            logger.warning(f"解析工具结果JSON失败: {e}")
            return content_str

        # 1. 扁平化：如果包含嵌套的 content JSON 字符串，尝试解析它
        data = cls._flatten_nested_json(data)

        # 2. 裁剪大字段
        cls._truncate_large_fields(data)
        
        return data

    @classmethod
    def _flatten_nested_json(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """尝试解析嵌套在 content 字段中的 JSON"""
        if isinstance(data, dict) and 'content' in data:
            inner = data['content']
            if isinstance(inner, str) and inner.strip().startswith('{'):
                try:
                    return json.loads(inner)
                except json.JSONDecodeError:
                    pass
        return data

    @classmethod
    def _truncate_large_fields(cls, data: Any, max_len: int = 1000) -> None:
        """裁剪 tool results 中过长的文本字段"""
        if isinstance(data, dict) and 'results' in data and isinstance(data['results'], list):
            for item in data['results']:
                if isinstance(item, dict):
                    for field in ['snippet', 'description', 'content']:
                        val = item.get(field)
                        if isinstance(val, str) and len(val) > max_len:
                            item[field] = val[:max_len] + '...[TRUNCATED]'

