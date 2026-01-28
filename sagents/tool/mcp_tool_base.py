from typing import Optional, Union, get_origin, get_args
from functools import wraps
import inspect
from docstring_parser import parse
from .tool_schema import SageMcpToolSpec

# Global registry for discovered MCP tools
_DISCOVERED_MCP_TOOLS = {}

try:
    from typing import Annotated
except ImportError:
    try:
        from typing_extensions import Annotated
    except ImportError:
        Annotated = None

try:
    from pydantic.fields import FieldInfo
except ImportError:
    class FieldInfo:
        pass

def get_json_schema_type(py_type, type_mapping):
    """Recursively map Python type to JSON schema type definition"""
    origin = get_origin(py_type)
    args = get_args(py_type)
    
    # Handle Annotated
    if Annotated is not None and origin is Annotated:
        # First argument is the type
        if args:
            return get_json_schema_type(args[0], type_mapping)
        return "string"

    # Handle Optional (Union[T, None])
    if origin is Union:
        non_none_types = [t for t in args if t is not type(None)]
        if non_none_types:
            # Use the first non-None type
            return get_json_schema_type(non_none_types[0], type_mapping)
        return "string" # Fallback

    # Direct mapping
    if py_type in type_mapping:
        return type_mapping[py_type]
    
    # List/Array
    if origin is list or py_type is list:
        return "array"

    # Dict/Object
    if origin is dict or py_type is dict:
        return "object"

    return "string" # Default fallback

def get_detailed_schema(py_type, type_mapping):
    """Get detailed JSON schema including items/properties for nested types"""
    origin = get_origin(py_type)
    args = get_args(py_type)
    
    schema = {}

    # Handle Annotated
    if Annotated is not None and origin is Annotated:
        # First argument is the type
        if args:
            base_schema = get_detailed_schema(args[0], type_mapping)
            schema.update(base_schema)
            
            # Extract info from Annotated metadata
            for metadata in args[1:]:
                # Handle pydantic Field
                if isinstance(metadata, FieldInfo):
                    if metadata.description:
                        schema["description"] = metadata.description
                    if metadata.json_schema_extra:
                        schema.update(metadata.json_schema_extra)
                # Fallback for generic objects with these attributes
                elif hasattr(metadata, "description") or hasattr(metadata, "json_schema_extra"):
                    if hasattr(metadata, "description") and metadata.description:
                        schema["description"] = metadata.description
                    if hasattr(metadata, "json_schema_extra") and metadata.json_schema_extra:
                        schema.update(metadata.json_schema_extra)
        return schema
    
    if origin is Union:
        non_none_types = [t for t in args if t is not type(None)]
        if non_none_types:
            return get_detailed_schema(non_none_types[0], type_mapping)
        return {}

    if origin is list or py_type is list:
        if args:
            item_type = get_json_schema_type(args[0], type_mapping)
            item_detailed = get_detailed_schema(args[0], type_mapping)
            items_schema = {"type": item_type}
            items_schema.update(item_detailed)
            schema["items"] = items_schema
            
    elif origin is dict or py_type is dict:
        if args and len(args) >= 2:
            # args[0] is key (must be str), args[1] is value
            value_type = get_json_schema_type(args[1], type_mapping)
            value_detailed = get_detailed_schema(args[1], type_mapping)
            additional_props = {"type": value_type}
            additional_props.update(value_detailed)
            schema["additionalProperties"] = additional_props
            
    return schema

def sage_mcp_tool(
    name: Optional[str] = None,
    description: Optional[str] = None,
    **kwargs
):
    """
    Decorator to mark a function as a built-in MCP tool for sagents.
    This allows sagents to discover and register this tool without starting a separate MCP server.
    
    Args:
        name: Tool name (default: function name)
        description: Tool description (default: docstring)
        **kwargs: Additional configuration:
            - description_i18n: Dict[str, str]
            - param_description_i18n: Dict[str, Dict[str, str]]
            - return_data: Dict[str, Any]
            - return_properties_i18n: Dict[str, Dict[str, Any]]
    """
    description_i18n = kwargs.get("description_i18n")
    param_description_i18n = kwargs.get("param_description_i18n")
    return_data = kwargs.get("return_data")
    return_properties_i18n = kwargs.get("return_properties_i18n")

    def decorator(func):
        tool_name = name or func.__name__

        # Parse docstring
        docstring = func.__doc__ or ""
        parsed_docstring = parse(docstring)
        tool_desc = description or parsed_docstring.short_description or ""
        if parsed_docstring.long_description:
            tool_desc += "\n" + parsed_docstring.long_description

        # Parse parameters
        sig = inspect.signature(func)
        parameters = {}
        required = []

        # Map docstring params
        doc_params = {p.arg_name: p.description for p in parsed_docstring.params}

        type_mapping = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
        }

        for param_name, param in sig.parameters.items():
            if param_name == "self" or param_name == "cls":
                continue

            param_type = "string"  # default
            detailed_schema = {}

            if param.annotation != inspect.Parameter.empty:
                param_type = get_json_schema_type(param.annotation, type_mapping)
                detailed_schema = get_detailed_schema(param.annotation, type_mapping)

            param_info = {
                "type": param_type,
                "description": doc_params.get(param_name, ""),
            }
            param_info.update(detailed_schema)

            # Handle defaults
            if param.default == inspect.Parameter.empty:
                required.append(param_name)
            else:
                pass

            parameters[param_name] = param_info

        # Handle return data
        spec_return_data = None
        if return_data:
            spec_return_data = return_data
        else:
            returns_obj = getattr(parsed_docstring, "returns", None)
            if returns_obj and (returns_obj.description or returns_obj.return_type_name):
                spec_return_data = {
                    "type": "object",
                    "description": (returns_obj.description or "").strip(),
                }

        spec = SageMcpToolSpec(
            name=tool_name,
            description=tool_desc,
            description_i18n=description_i18n or {},
            func=func,
            parameters=parameters,
            required=required,
            return_data=spec_return_data,
            return_properties_i18n=return_properties_i18n,
            param_description_i18n=param_description_i18n
        )

        # Store ToolSpec on the function
        func._mcp_tool_spec = spec
        func._is_sagents_mcp_tool = True

        # Add to global registry
        module_name = func.__module__
        if module_name not in _DISCOVERED_MCP_TOOLS:
            _DISCOVERED_MCP_TOOLS[module_name] = []
        _DISCOVERED_MCP_TOOLS[module_name].append(func)

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        wrapper._mcp_tool_spec = spec
        wrapper._is_sagents_mcp_tool = True

        return wrapper
    return decorator
