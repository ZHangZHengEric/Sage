from typing import Dict, Any, List, Optional, Union, get_origin, get_args
from sagents.utils.logger import logger
import inspect
import json
import traceback
from functools import wraps
from docstring_parser import parse,DocstringStyle
from .tool_config import ToolSpec
import os
import time

class ToolBase:
    _tools: Dict[str, ToolSpec] = {}  # Class-level registry
    
    def __init__(self):
        logger.debug(f"Initializing {self.__class__.__name__}")
        self.tools = {}  # Instance-specific registry
        # Auto-register decorated methods
        for name, method in inspect.getmembers(self, inspect.ismethod):
            if hasattr(method, '_tool_spec'):
                spec = method._tool_spec
                self.tools[name] = spec
                if name not in self.__class__._tools:
                    self.__class__._tools[name] = spec
                logger.debug(f"Registered tool: {name} to {self.__class__.__name__}")
    
    @classmethod
    def tool(
        cls,
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
            logger.info(f"Applying tool decorator to {func.__name__} in {cls.__name__}")
            _profile = os.environ.get("SAGENTS_PROFILING_TOOL_DECORATOR", "").lower() in ("1", "true", "yes")
            _t_total_start = time.perf_counter() if _profile else None
            # Parse full docstring using docstring_parser
            docstring_text = inspect.getdoc(func) or ""
            _t_parse_start = time.perf_counter() if _profile else None
            parsed_docstring = parse(docstring_text,style=DocstringStyle.GOOGLE)
            _t_parse_end = time.perf_counter() if _profile else None
            
            # Use parsed description if available
            parsed_description = parsed_docstring.short_description or ""
            if parsed_docstring.long_description:
                parsed_description += "\n" + parsed_docstring.long_description
            
            # Extract parameters from signature
            _t_sig_start = time.perf_counter() if _profile else None
            sig = inspect.signature(func)
            parameters = {}
            required = []

            # Helper: infer JSON schema type from Python/typing annotation
            def _infer_json_type(annotation: Any) -> str:
                try:
                    if annotation is inspect.Parameter.empty or annotation is None:
                        return "string"
                    # Resolve typing constructs
                    origin = get_origin(annotation)
                    args = get_args(annotation)
                    if origin is Union:
                        # Treat Optional[T] as T
                        non_none = [a for a in args if a is not type(None)]  # noqa: E721
                        if len(non_none) == 1:
                            return _infer_json_type(non_none[0])
                        # Fallback for general Union
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
                    # Non-typing builtins
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

            # 便于参数多语言查找
            _param_desc_i18n_map = param_description_i18n or {}

            for name, param in sig.parameters.items():
                if name == "self":
                    continue
                    
                param_info = {"type": "string", "description": ""}  # Default values
                if param.annotation != inspect.Parameter.empty:
                    param_info["type"] = _infer_json_type(param.annotation)
                    
                
                # Get parameter description from parsed docstring
                param_desc = ""
                for doc_param in parsed_docstring.params:
                    if doc_param.arg_name == name:
                        param_desc = doc_param.description
                        break
                
                # Use docstring description if available, otherwise default
                param_info["description"] = param_desc or f"The {name} parameter"

                # 注入参数多语言描述（如果提供）
                if name in _param_desc_i18n_map and isinstance(_param_desc_i18n_map[name], dict):
                    # 仅在提供时加入该键，避免无意义的空结构
                    param_info["description_i18n"] = _param_desc_i18n_map[name]
                
                if param.default == inspect.Parameter.empty:
                    required.append(name)
                
                parameters[name] = param_info
            _t_params_end = time.perf_counter() if _profile else None

            # Always use function name as tool name
            tool_name = func.__name__
            logger.debug(f"Registering tool: {tool_name} to {cls.__name__}")
            logger.debug(f"Parameters: {parameters}")
            logger.debug(f"Required: {required}")

            # 处理返回结构：优先使用传入的 return_data，其次从 docstring 的 Returns 提取描述
            spec_return_data: Optional[Dict[str, Any]] = None
            _t_returns_start = time.perf_counter() if _profile else None
            try:
                if return_data and isinstance(return_data, dict):
                    # 复制以避免外部引用被修改
                    spec_return_data = json.loads(json.dumps(return_data))
                else:
                    # 从 docstring 的 Returns 区块提取简要描述
                    returns_obj = getattr(parsed_docstring, "returns", None)
                    if returns_obj and (returns_obj.description or returns_obj.return_type_name):
                        spec_return_data = {
                            "type": "object",
                            "description": (returns_obj.description or "").strip(),
                        }
            except Exception:
                # 保底：不影响工具注册
                spec_return_data = spec_return_data or None

            # 合并返回结构的多语言描述到结构体的描述字段中（仅根 description），便于后续本地化导出
            try:
                if spec_return_data is not None:
                    # 根描述多语言，仅支持 {"description": {...}}
                    root_i18n = None
                    if isinstance(return_properties_i18n, dict):
                        if "description" in return_properties_i18n and isinstance(return_properties_i18n["description"], dict):
                            root_i18n = return_properties_i18n["description"]
                    if root_i18n:
                        spec_return_data["description_i18n"] = root_i18n
            except Exception:
                # 不影响注册
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
            
            @wraps(func)
            def wrapper(*args, **kwargs):
                logger.debug(f"Calling tool: {tool_name} with {len(kwargs)} args")
                result = func(*args, **kwargs)
                logger.debug(f"Completed tool: {tool_name}")
                return result
            
            # Store the tool spec on both the wrapper and original function
            wrapper._tool_spec = spec
            func._tool_spec = spec
            
            # Set __objclass__ to enable instance method binding detection
            wrapper.__objclass__ = cls
            func.__objclass__ = cls
            
            # Register in class registry
            # DEPRECATED: Registration is now handled by __init_subclass__ to avoid shared registry issues
            # if not hasattr(func, '_is_classmethod'):
            #     # For instance methods, register in class registry
            #     if not hasattr(cls, '_tools'):
            #         cls._tools = {}
            #     cls._tools[tool_name] = spec
            
            logger.debug(f"Registered tool to toolbase: {tool_name}")
            return wrapper
        return decorator

    def __init_subclass__(cls, **kwargs):
        """Initialize subclass and register its tools"""
        super().__init_subclass__(**kwargs)
        # Create a fresh registry for the subclass
        cls._tools = {}
        # Register tools defined in this subclass
        for name, value in cls.__dict__.items():
            if hasattr(value, '_tool_spec'):
                cls._tools[value._tool_spec.name] = value._tool_spec
                logger.debug(f"Registered tool {value._tool_spec.name} to {cls.__name__}")

    @classmethod
    def get_tools(cls) -> Dict[str, ToolSpec]:
        logger.debug(f"Getting tools for {cls.__name__}")
        return cls._tools

    def get_openai_tools(self, lang: Optional[str] = None, fallback_chain: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Get OpenAI-compatible tool specifications for this instance，支持可选语言化。

        Args:
            lang: 优先语言代码（如 "zh"、"en"）；不填则返回默认描述
            fallback_chain: 语言回退链，例如 ["zh", "en"]
        """
        logger.debug(f"Getting OpenAI tools for {self.__class__.__name__} instance")

        def _resolve_text(base: str, i18n: Optional[Dict[str, str]]) -> str:
            if not i18n or not isinstance(i18n, dict) or not lang:
                return base
            # 优先 lang，然后 fallback_chain
            if lang in i18n and i18n[lang]:
                return i18n[lang]
            if fallback_chain:
                for fb in fallback_chain:
                    if fb in i18n and i18n[fb]:
                        return i18n[fb]
            # 常用兜底
            for fb in ["zh", "en", "pt"]:
                if fb in i18n and i18n[fb]:
                    return i18n[fb]
            return base

        tools = []
        for tool_spec in self.tools.values():
            # 解析工具描述
            tool_desc = _resolve_text(
                getattr(tool_spec, "description", ""),
                getattr(tool_spec, "description_i18n", None),
            )
            # 解析参数描述
            localized_params = {}
            for p_name, p_info in getattr(tool_spec, "parameters", {}).items():
                p_desc = p_info.get("description", "")
                p_desc_i18n = p_info.get("description_i18n")
                p_local_desc = _resolve_text(p_desc, p_desc_i18n)
                # 保留原有结构，覆盖描述
                new_info = dict(p_info)
                new_info["description"] = p_local_desc
                # 移除导出中的 description_i18n
                if "description_i18n" in new_info:
                    new_info.pop("description_i18n", None)
                localized_params[p_name] = new_info

            # 返回结构本地化：移除object根级描述，应用属性级 description_i18n 或映射 return_properties_i18n
            localized_returns = None
            try:
                rd = getattr(tool_spec, "return_data", None)
                if isinstance(rd, dict):
                    # 深拷贝以避免外部修改
                    localized_returns = json.loads(json.dumps(rd))
                    # 对于 object 类型，移除根级 description/description_i18n
                    if localized_returns.get("type") == "object":
                        localized_returns.pop("description", None)
                        localized_returns.pop("description_i18n", None)

                    # 属性级 i18n 映射（由装饰器提供），用于 returns 的属性本地化
                    rdi = getattr(tool_spec, "return_properties_i18n", None)

                    def _apply_prop_i18n(props: Dict[str, Any], rdi_map: Optional[Dict[str, Dict[str, str]]] = None):
                        if not isinstance(props, dict):
                            return
                        for _pname, _pinfo in props.items():
                            di18n = _pinfo.get("description_i18n")
                            candidate_i18n: Optional[Dict[str, str]] = None
                            if isinstance(di18n, dict):
                                candidate_i18n = di18n
                            elif isinstance(rdi_map, dict):
                                mapped = rdi_map.get(_pname)
                                if isinstance(mapped, dict):
                                    candidate_i18n = mapped
                            if isinstance(candidate_i18n, dict):
                                _pinfo["description"] = _resolve_text(_pinfo.get("description", ""), candidate_i18n)
                                _pinfo.pop("description_i18n", None)

                    # properties 层级
                    props = localized_returns.get("properties")
                    if isinstance(props, dict):
                        _apply_prop_i18n(props, rdi)

                    # additionalProperties 层级（object 或其他）
                    ap = localized_returns.get("additionalProperties")
                    if isinstance(ap, dict):
                        if ap.get("type") == "object":
                            # additionalProperties 下的属性不使用 rdi_map；仅消费嵌入式 description_i18n
                            ap_props = ap.get("properties")
                            if isinstance(ap_props, dict):
                                _apply_prop_i18n(ap_props, None)
                        else:
                            di18n = ap.get("description_i18n")
                            if isinstance(di18n, dict):
                                ap["description"] = _resolve_text(ap.get("description", ""), di18n)
                                ap.pop("description_i18n", None)
            except Exception:
                # 打印traceback便于调试
                try:
                    logger.error(traceback.format_exc())
                except Exception:
                    pass
                localized_returns = localized_returns or None

            tools.append({
                "type": "function",
                "function": {
                    "name": tool_spec.name,
                    "description": tool_desc,
                    "parameters": {
                        "type": "object",
                        "properties": localized_params,
                        "required": tool_spec.required,
                    },
                    **({"returns": localized_returns} if localized_returns else {}),
                },
            })
        return tools
