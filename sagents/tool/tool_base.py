from operator import imod
from typing import Dict, Any, List, Callable, Optional, Type, Union
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
            
            for name, param in sig.parameters.items():
                if name == "self":
                    continue
                    
                param_info = {"type": "string", "description": ""}  # Default values
                if param.annotation != inspect.Parameter.empty:
                    type_name = param.annotation.__name__.lower()
                    if type_name == "str":
                        param_info["type"] = "string"
                    elif type_name == "int":
                        param_info["type"] = "integer"
                    elif type_name == "float":
                        param_info["type"] = "number"
                    elif type_name == "bool":
                        param_info["type"] = "boolean"
                    elif type_name == "dict":
                        param_info["type"] = "object"
                    elif type_name == "list":
                        param_info["type"] = "array"
                
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
