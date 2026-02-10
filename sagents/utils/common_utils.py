import json
import ast
from typing import Any, List, Union

def ensure_list(content: Union[str, List[Any]], separator: str = None) -> List[Any]:
    """
    Try to parse the input content into a list.
    
    Supports:
    1. Direct List input.
    2. JSON string parsing.
    3. Python literal evaluation (for stringified lists).
    4. Comma-separated strings (if not a JSON/Literal list).
    5. Space-separated strings (fallback).
    
    Args:
        content: The input string or list.
        separator: Optional specific separator to use for string splitting. 
                   If provided, it overrides the auto-detection logic for delimiters.

    Returns:
        A list containing the parsed items. Returns [content] if parsing fails but input was a string.
        Returns [] if content is None or empty string.
    """
    if content is None:
        return []
    
    if isinstance(content, list):
        return content
    
    if not isinstance(content, str):
        return [content]
    
    content = content.strip()
    if not content:
        return []

    # 1. Try JSON parsing
    try:
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    # 2. Try ast.literal_eval (safe eval)
    try:
        if content.startswith('[') and content.endswith(']'):
            parsed = ast.literal_eval(content)
            if isinstance(parsed, list):
                return parsed
    except Exception:
        pass
    
    # 3. Handle Delimiters (Comma or Space)
    # If a specific separator is provided, use it.
    if separator:
        return [item.strip() for item in content.split(separator) if item.strip()]

    # Auto-detect: if comma exists, assume comma-separated
    if ',' in content:
        return [item.strip() for item in content.split(',') if item.strip()]
    
    # Auto-detect: if space exists, assume space-separated
    if ' ' in content:
        return [item.strip() for item in content.split(' ') if item.strip()]

    # 4. Fallback: return as single item list
    return [content]
