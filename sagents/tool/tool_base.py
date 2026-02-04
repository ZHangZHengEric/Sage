from typing import Dict, Any, List, Optional, Union, get_origin, get_args
from sagents.utils.logger import logger
import inspect
import traceback
from functools import wraps
import copy
from docstring_parser import parse, DocstringStyle
from .tool_schema import ToolSpec
import os
import time

_DISCOVERED_TOOLS = {}

def tool(
    disabled: bool = False,
    description_i18n: Optional[Dict[str, str]] = None,
    param_description_i18n: Optional[Dict[str, Dict[str, str]]] = None,
    return_data: Optional[Dict[str, Any]] = None,
    return_properties_i18n: Optional[Dict[str, Dict[str, Any]]] = None,
):
    """Decorator factory for registering tool methods，如果disabled为True，则不注册该方法。

    新增：
    - description_i18n: 工具描述的多语言字典，例如 {"zh": "读取文件", "en": "Read file"}
    - param_description_i18n: 参数描述的多语言字典，形如 {param_name: {lang: text}}
    - return_data: 返回数据的结构描述（JSON Schema风格），如 {"type":"object","properties":{...}}
    - return_properties_i18n: 返回对象的根级 description 的多语言描述（仅根描述）
    """
    def decorator(func):
        if disabled:
            logger.info(f"Tool {func.__name__} is disabled, not registering")
            return func
        logger.debug(f"Applying tool decorator to {func.__qualname__}")
        _profile = os.environ.get("SAGENTS_PROFILING_TOOL_DECORATOR", "").lower() in ("1", "true", "yes")
        _t_total_start = time.perf_counter() if _profile else None
        docstring_text = inspect.getdoc(func) or ""
        parsed_docstring = None
        _t_parse_start = time.perf_counter() if _profile else None
        if docstring_text:
            parsed_docstring = parse(docstring_text, style=DocstringStyle.GOOGLE)
        _t_parse_end = time.perf_counter() if _profile else None

        parsed_description = ""
        if parsed_docstring:
            parsed_description = parsed_docstring.short_description or ""
            if parsed_docstring.long_description:
                parsed_description += "\n" + parsed_docstring.long_description

        _t_sig_start = time.perf_counter() if _profile else None
        sig = inspect.signature(func)
        parameters = {}
        required = []

        def _infer_json_type(annotation: Any) -> str:
            try:
                if annotation is inspect.Parameter.empty or annotation is None:
                    return "string"
                origin = get_origin(annotation)
                args = get_args(annotation)
                if origin is Union:
                    non_none = [a for a in args if a is not type(None)]  # noqa: E721
                    if len(non_none) == 1:
                        return _infer_json_type(non_none[0])
                    return "string"
                if origin in (list, List, tuple):
                    return "array"
                if origin in (dict, Dict):
                    return "object"
                if origin in (str,):
                    return "string"
                if origin in (int,):
                    return "integer"
                if origin in (float,):
                    return "number"
                if origin in (bool,):
                    return "boolean"
                if isinstance(annotation, type):
                    name = annotation.__name__.lower()
                    return {
                        "str": "string",
                        "int": "integer",
                        "float": "number",
                        "bool": "boolean",
                        "dict": "object",
                        "list": "array",
                        "tuple": "array",
                    }.get(name, "string")
            except Exception:
                pass
            return "string"

        _param_desc_i18n_map = param_description_i18n or {}
        doc_param_map = {}
        if parsed_docstring and parsed_docstring.params:
            doc_param_map = {p.arg_name: p.description for p in parsed_docstring.params}

        for name, param in sig.parameters.items():
            if name == "self":
                continue

            param_info = {"type": "string", "description": ""}
            if param.annotation != inspect.Parameter.empty:
                param_info["type"] = _infer_json_type(param.annotation)

            param_desc = doc_param_map.get(name, "")
            param_info["description"] = param_desc or f"The {name} parameter"

            if name in _param_desc_i18n_map and isinstance(_param_desc_i18n_map[name], dict):
                param_info["description_i18n"] = _param_desc_i18n_map[name]

            if param.default == inspect.Parameter.empty:
                required.append(name)

            parameters[name] = param_info
        _t_params_end = time.perf_counter() if _profile else None

        tool_name = func.__name__
        logger.debug(f"Registering tool: {tool_name}")
        logger.debug(f"Parameters: {parameters}")
        logger.debug(f"Required: {required}")

        spec_return_data: Optional[Dict[str, Any]] = None
        _t_returns_start = time.perf_counter() if _profile else None
        try:
            if return_data and isinstance(return_data, dict):
                spec_return_data = copy.deepcopy(return_data)
            else:
                if parsed_docstring:
                    returns_obj = getattr(parsed_docstring, "returns", None)
                    if returns_obj and (returns_obj.description or returns_obj.return_type_name):
                        spec_return_data = {
                            "type": "object",
                            "description": (returns_obj.description or "").strip(),
                        }
        except Exception:
            spec_return_data = spec_return_data or None

        try:
            if spec_return_data is not None:
                root_i18n = None
                if isinstance(return_properties_i18n, dict):
                    if "description" in return_properties_i18n and isinstance(return_properties_i18n["description"], dict):
                        root_i18n = return_properties_i18n["description"]
                if root_i18n:
                    spec_return_data["description_i18n"] = root_i18n
        except Exception:
            pass
        _t_returns_end = time.perf_counter() if _profile else None

        spec = ToolSpec(
            name=tool_name,
            description=parsed_description or "",
            description_i18n=description_i18n or {},
            func=func,
            parameters=parameters,
            required=required,
            return_data=spec_return_data,
            return_properties_i18n=return_properties_i18n or None,
        )
        if _profile:
            _t_total_end = time.perf_counter()
            try:
                logger.info(
                    f"Tool decorator timing {tool_name}: parse={((_t_parse_end or 0)-(_t_parse_start or 0)):.3f}s, "
                    f"sig_params={((_t_params_end or 0)-(_t_sig_start or 0)):.3f}s, "
                    f"returns={((_t_returns_end or 0)-(_t_returns_start or 0)):.3f}s, "
                    f"total={((_t_total_end or 0)-(_t_total_start or 0)):.3f}s"
                )
            except Exception:
                try:
                    logger.error(traceback.format_exc())
                except Exception:
                    pass

        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                logger.debug(f"Calling async tool: {tool_name} with {len(kwargs)} args")
                result = await func(*args, **kwargs)
                logger.debug(f"Completed async tool: {tool_name}")
                return result
        else:
            @wraps(func)
            def wrapper(*args, **kwargs):
                logger.debug(f"Calling tool: {tool_name} with {len(kwargs)} args")
                result = func(*args, **kwargs)
                logger.debug(f"Completed tool: {tool_name}")
                return result

        wrapper._tool_spec = spec
        func._tool_spec = spec
        if "." in func.__qualname__:
            func._tool_owner_qualname = func.__qualname__.rsplit(".", 1)[0]
            func._tool_owner_module = func.__module__
            wrapper._tool_owner_qualname = func._tool_owner_qualname
            wrapper._tool_owner_module = func._tool_owner_module

        module_name = func.__module__
        if module_name not in _DISCOVERED_TOOLS:
            _DISCOVERED_TOOLS[module_name] = []
        _DISCOVERED_TOOLS[module_name].append(func)

        return wrapper
    return decorator
