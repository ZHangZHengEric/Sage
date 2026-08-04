import json
from typing import Any
import numpy as np


def make_serializable(obj: Any):
    if isinstance(obj, (np.integer, np.int64, np.int32)):  # pyright: ignore[reportArgumentType]
        return int(obj)
    if isinstance(obj, (np.floating, np.float64, np.float32)):  # pyright: ignore[reportArgumentType]
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, list):
        return [make_serializable(item) for item in obj]
    if isinstance(obj, dict):
        return {key: make_serializable(value) for key, value in obj.items()}
    # 特殊处理 OpenAI 的 ChatCompletion 对象
    if hasattr(obj, "usage") and hasattr(obj, "choices") and hasattr(obj, "model"):
        # 优先使用 SDK 的完整模型导出，避免遗漏 reasoning_content、
        # system_fingerprint、service_tier 以及供应商扩展字段。
        if hasattr(obj, "model_dump"):
            return make_serializable(obj.model_dump())
        # 兼容没有 model_dump 的旧 SDK 对象。
        result = {}
        for key, value in vars(obj).items():
            result[key] = make_serializable(value)
        return result
    if hasattr(obj, "to_dict"):
        return make_serializable(obj.to_dict())
    if hasattr(obj, "model_dump"):
        return make_serializable(obj.model_dump())
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
