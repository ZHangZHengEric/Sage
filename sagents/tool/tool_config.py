from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Union

from mcp import StdioServerParameters


@dataclass
class SseServerParameters:
    url: str
    api_key: Optional[str] = None

@dataclass
class StreamableHttpServerParameters:
    url: str
    api_key: Optional[str] = None


@dataclass
class McpToolSpec:
    name: str
    description: str
    func: Callable
    parameters: Dict[str, Dict[str, Any]]  # Now includes description for each param
    required: List[str]
    server_name: str
    server_params: Union[StdioServerParameters, SseServerParameters, StreamableHttpServerParameters]
    
@dataclass
class ToolSpec:
    name: str
    description: str
    func: Callable
    parameters: Dict[str, Dict[str, Any]]  # Now includes description for each param
    required: List[str]

@dataclass
class AgentToolSpec:
    name: str
    description: str
    func: Callable
    parameters: Dict[str, Dict[str, Any]]
    required: List[str]

def convert_spec_to_openai_format(tool_spec: Union[McpToolSpec,ToolSpec, AgentToolSpec]) -> Dict[str, Any]:
    return {
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
    }