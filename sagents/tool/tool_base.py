from operator import imod
from typing import Dict, Any, List, Callable, Optional, Type, Union, get_origin, get_args
from dataclasses import dataclass
from mcp import StdioServerParameters
from sagents.utils.logger import logger
import inspect
import json
from functools import wraps
from docstring_parser import parse,DocstringStyle
from .tool_config import ToolSpec, AgentToolSpec, McpToolSpec, SseServerParameters, StreamableHttpServerParameters

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
    def tool(cls,disabled:bool=False):
        """Decorator factory for registering tool methods，如果disabled为True，则不注册该方法"""
        def decorator(func):
            if disabled:
                logger.info(f"Tool {func.__name__} is disabled, not registering")
                return func
            logger.info(f"Applying tool decorator to {func.__name__} in {cls.__name__}")
            # Parse full docstring using docstring_parser
            docstring_text = inspect.getdoc(func) or ""
            parsed_docstring = parse(docstring_text,style=DocstringStyle.GOOGLE)
            
            # Use parsed description if available
            parsed_description = parsed_docstring.short_description or ""
            if parsed_docstring.long_description:
                parsed_description += "\n" + parsed_docstring.long_description
            
            # Extract parameters from signature
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
                
                if param.default == inspect.Parameter.empty:
                    required.append(name)
                
                parameters[name] = param_info
            
            # Always use function name as tool name
            tool_name = func.__name__
            logger.debug(f"Registering tool: {tool_name} to {cls.__name__}")
            logger.debug(f"Parameters: {parameters}")
            logger.debug(f"Required: {required}")
            spec = ToolSpec(
                name=tool_name,
                description=parsed_description or "",
                func=func,
                parameters=parameters,
                required=required
            )
            
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
            if not hasattr(func, '_is_classmethod'):
                # For instance methods, register in class registry
                if not hasattr(cls, '_tools'):
                    cls._tools = {}
                cls._tools[tool_name] = spec
            
            logger.debug(f"Registered tool to toolbase: {tool_name}")
            return wrapper
        return decorator

    @classmethod
    def get_tools(cls) -> Dict[str, ToolSpec]:
        logger.debug(f"Getting tools for {cls.__name__}")
        return cls._tools

    def get_openai_tools(self) -> List[Dict[str, Any]]:
        """Get OpenAI-compatible tool specifications for this instance"""
        logger.debug(f"Getting OpenAI tools for {self.__class__.__name__} instance")
        tools = []
        for tool_spec in self.tools.values():
            tools.append({
                "type": "function",
                "function": {
                    "name": tool_spec.name,
                    "description": tool_spec.description,
                    "parameters": {
                        "type": "object",
                        "properties": tool_spec.parameters,
                        "required": tool_spec.required
                    }
                }
            })
        return tools
