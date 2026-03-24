"""
Tool call parser for streaming JSON parameters using ijson + regex
"""

import ijson
import io
import json
import re
from typing import List, Tuple, Set


class ToolCallParser:
    """Tool call parser using ijson + regex for streaming JSON parsing"""
    
    def __init__(self):
        self.buffer = ""
        self.parsed_keys: Set[str] = set()
        self.full_args = None
    
    def _try_regex_parse(self, buffer: str) -> List[Tuple[str, str]]:
        """使用正则表达式尝试解析不完整的 JSON"""
        pairs = []
        
        # 匹配 "key": "value" 格式（value 可能不完整）
        pattern1 = r'"([^"]+)"\s*:\s*"([^"]*)'
        for match in re.finditer(pattern1, buffer):
            key = match.group(1)
            value = match.group(2)
            if key not in self.parsed_keys:
                pairs.append((key, value))
                self.parsed_keys.add(key)
        
        # 匹配 "key": number 格式
        pattern2 = r'"([^"]+)"\s*:\s*(-?\d+\.?\d*)'
        for match in re.finditer(pattern2, buffer):
            key = match.group(1)
            value = match.group(2)
            if key not in self.parsed_keys:
                pairs.append((key, value))
                self.parsed_keys.add(key)
        
        # 匹配 "key": true/false/null 格式
        pattern3 = r'"([^"]+)"\s*:\s*(true|false|null)'
        for match in re.finditer(pattern3, buffer):
            key = match.group(1)
            value = match.group(2)
            if key not in self.parsed_keys:
                pairs.append((key, value))
                self.parsed_keys.add(key)
        
        return pairs
    
    def feed_string(self, new_args: str) -> List[Tuple[str, str]]:
        """
        Parse args string, return new key-value pairs as they become available
        
        Returns:
            List[Tuple[str, str]]: list of (key, value) pairs
        """
        # 累积数据
        self.buffer += new_args
        new_pairs = []
        
        # Try to parse complete JSON first
        try:
            result = json.loads(self.buffer)
            if isinstance(result, dict):
                self.full_args = result
                # If complete JSON parsed, return all key-value pairs
                for key, value in result.items():
                    if key not in self.parsed_keys:
                        new_pairs.append((key, str(value) if not isinstance(value, (int, float, bool)) else str(value)))
                        self.parsed_keys.add(key)
                return new_pairs
        except json.JSONDecodeError:
            pass
        
        # Try ijson for incremental parsing
        try:
            stream = io.BytesIO(self.buffer.encode('utf-8'))
            parser = ijson.parse(stream)
            
            current_key = None
            
            for prefix, event, value in parser:
                if event == 'map_key':
                    current_key = value
                elif event == 'string' and current_key and '.' not in prefix:
                    if current_key not in self.parsed_keys:
                        new_pairs.append((current_key, value))
                        self.parsed_keys.add(current_key)
                elif event == 'number' and current_key and '.' not in prefix:
                    if current_key not in self.parsed_keys:
                        new_pairs.append((current_key, str(value)))
                        self.parsed_keys.add(current_key)
                elif event == 'boolean' and current_key and '.' not in prefix:
                    if current_key not in self.parsed_keys:
                        new_pairs.append((current_key, str(value)))
                        self.parsed_keys.add(current_key)
                elif event == 'null' and current_key and '.' not in prefix:
                    if current_key not in self.parsed_keys:
                        new_pairs.append((current_key, 'null'))
                        self.parsed_keys.add(current_key)
        
        except (ijson.IncompleteJSONError, Exception):
            pass
        
        # If ijson didn't find new pairs, try regex
        if not new_pairs:
            new_pairs = self._try_regex_parse(self.buffer)
        
        return new_pairs
    
    def get_full_args(self) -> dict:
        """Get the fully parsed args if available"""
        return self.full_args
    
    def reset(self):
        self.buffer = ""
        self.parsed_keys = set()
        self.full_args = None
