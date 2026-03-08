import json
from typing import Any
import numpy as np


def make_serializable(obj: Any):
    if isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    if isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, list):
        return [make_serializable(item) for item in obj]
    if isinstance(obj, dict):
        return {key: make_serializable(value) for key, value in obj.items()}
    # 特殊处理 OpenAI 的 ChatCompletion 对象
    if hasattr(obj, "usage") and hasattr(obj, "choices") and hasattr(obj, "model"):
        # 这是 OpenAI 的响应对象，手动提取所有字段
        result = {}
        for key in ["id", "object", "created", "model", "choices", "usage"]:
            if hasattr(obj, key):
                value = getattr(obj, key)
                result[key] = make_serializable(value)
        return result
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        if hasattr(obj, "id") and hasattr(obj, "function"):
            result = {"id": obj.id, "type": getattr(obj, "type", "function")}
            function = obj.function if hasattr(obj, "function") else None
            if function:
                result["function"] = {
                    "name": getattr(function, "name", ""),
                    "arguments": getattr(function, "arguments", ""),
                }
            return result
        result = {}
        for key, value in obj.__dict__.items():
            try:
                json.dumps(value)
                result[key] = make_serializable(value)
            except (TypeError, ValueError):
                result[key] = str(value)
        return result
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)
