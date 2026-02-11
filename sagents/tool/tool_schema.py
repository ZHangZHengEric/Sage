from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, List, Callable, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
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
    description_i18n: Dict[str, str]
    func: Optional[Callable]
    parameters: Dict[str, Dict[str, Any]]  # Now includes description for each param
    required: List[str]
    server_name: str
    server_params: Union[StdioServerParameters, SseServerParameters, StreamableHttpServerParameters]
    return_data : Optional[Dict[str, Any]] = None # 返回数据格式
    return_properties_i18n: Optional[Dict[str, Dict[str, Any]]] = None # 返回对象属性描述的多语言
    param_description_i18n: Optional[Dict[str, Dict[str, str]]] = None # 参数描述多语言映射 param -> {lang: text}
    
@dataclass
class ToolSpec:
    name: str
    description: str
    description_i18n: Dict[str, str]
    func: Callable
    parameters: Dict[str, Dict[str, Any]]  # Now includes description for each param
    required: List[str]
    return_data : Optional[Dict[str, Any]] = None # 返回数据格式
    return_properties_i18n: Optional[Dict[str, Dict[str, Any]]] = None # 返回对象属性描述的多语言
    param_description_i18n: Optional[Dict[str, Dict[str, str]]] = None # 参数描述多语言映射 param -> {lang: text}

@dataclass
class SageMcpToolSpec(ToolSpec):
    server_name: str = ""
    """Spec for built-in MCP tools (annotated with @sage_mcp_tool)"""
    pass

@dataclass
class AgentToolSpec:
    name: str
    description: str
    description_i18n: Dict[str, str]
    func: Callable
    parameters: Dict[str, Dict[str, Any]]
    required: List[str]
    return_data : Optional[Dict[str, Any]] = None # 返回数据格式
    return_properties_i18n: Optional[Dict[str, Dict[str, Any]]] = None # 返回对象属性描述的多语言
    param_description_i18n: Optional[Dict[str, Dict[str, str]]] = None # 参数描述多语言映射 param -> {lang: text}

def convert_spec_to_openai_format(
    tool_spec: Union[McpToolSpec, ToolSpec, AgentToolSpec],
    lang: Optional[str] = None,
    fallback_chain: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """将工具规格转换为 OpenAI 兼容格式，并按需本地化描述与参数说明。

    - 本地化优先顺序：lang -> fallback_chain -> 常用兜底 -> 基础描述
    - 参数描述优先来源：参数自身的 description_i18n -> tool_spec.param_description_i18n
    - 返回结构：移除根级描述，属性级按 description_i18n 或 return_properties_i18n 本地化
    """

    def _resolve_text(base: str, i18n: Optional[Dict[str, str]]) -> str:
        if not i18n or not isinstance(i18n, dict) or not lang:
            return base or ""
        if lang in i18n and i18n[lang]:
            return i18n[lang]
        if fallback_chain:
            for fb in fallback_chain:
                if fb in i18n and i18n[fb]:
                    return i18n[fb]
        for fb in ["zh", "en", "pt"]:
            if fb in i18n and i18n[fb]:
                return i18n[fb]
        return base or ""

    def _recursive_localize(node: Any):
        if not isinstance(node, dict):
            return

        # 1. 本地化当前节点的 description
        desc = node.get("description", "")
        desc_i18n = node.get("description_i18n")
        if isinstance(desc_i18n, dict):
            node["description"] = _resolve_text(desc, desc_i18n)
        
        # 移除 description_i18n
        if "description_i18n" in node:
            node.pop("description_i18n", None)

        # 2. 递归处理 properties (object)
        if node.get("type") == "object" and "properties" in node and isinstance(node["properties"], dict):
            for prop in node["properties"].values():
                _recursive_localize(prop)

        # 3. 递归处理 items (array)
        if node.get("type") == "array" and "items" in node:
            _recursive_localize(node["items"])

    # 工具描述本地化
    localized_desc = _resolve_text(getattr(tool_spec, "description", ""), getattr(tool_spec, "description_i18n", None))

    # 参数本地化
    param_i18n_map: Optional[Dict[str, Dict[str, str]]] = getattr(tool_spec, "param_description_i18n", None)
    localized_params: Dict[str, Any] = {}
    
    # 既然有了 param_schema 支持，我们需要更深度的拷贝和递归处理
    # 为了避免修改原始数据，我们先进行深拷贝
    import json as _json
    raw_params = getattr(tool_spec, "parameters", {})
    try:
        # 使用 json 序列化反序列化进行深拷贝，确保彻底解耦
        localized_params = _json.loads(_json.dumps(raw_params))
    except Exception:
        # 如果无法 json 序列化（极少情况），退回到简单的 dict 拷贝
        localized_params = {k: dict(v) for k, v in raw_params.items()}

    for p_name, p_info in localized_params.items():
        # 优先处理顶层的 param_description_i18n 映射（兼容旧逻辑）
        p_desc = p_info.get("description", "")
        p_desc_i18n = p_info.get("description_i18n")
        
        candidate_i18n = None
        if isinstance(p_desc_i18n, dict):
            candidate_i18n = p_desc_i18n
        elif isinstance(param_i18n_map, dict):
            candidate_i18n = param_i18n_map.get(p_name)
        
        if candidate_i18n:
             p_info["description"] = _resolve_text(p_desc, candidate_i18n)
        
        # 递归处理该参数的内部结构（支持 param_schema 定义的深层 i18n）
        _recursive_localize(p_info)

    # 返回结构本地化
    localized_returns = None
    rd = getattr(tool_spec, "return_data", None)
    if isinstance(rd, dict):
        # 深拷贝以避免外部修改
        import json as _json
        localized_returns = _json.loads(_json.dumps(rd))
        # 对于 object 类型，移除根级 description/description_i18n
        if localized_returns.get("type") == "object":
            localized_returns.pop("description", None)
            localized_returns.pop("description_i18n", None)

        rdi_map = getattr(tool_spec, "return_properties_i18n", None)

        def _apply_prop_i18n(props: Dict[str, Any], rdi: Optional[Dict[str, Dict[str, str]]] = None):
            if not isinstance(props, dict):
                return
            for _pname, _pinfo in props.items():
                di18n = _pinfo.get("description_i18n")
                candidate: Optional[Dict[str, str]] = None
                if isinstance(di18n, dict):
                    candidate = di18n
                elif isinstance(rdi, dict):
                    mapped = rdi.get(_pname)
                    if isinstance(mapped, dict):
                        candidate = mapped
                base_desc = _pinfo.get("description", "")
                _pinfo["description"] = _resolve_text(base_desc, candidate)
                # 移除导出中的 description_i18n
                _pinfo.pop("description_i18n", None)

        # 应用到 returns.properties
        if isinstance(localized_returns.get("properties"), dict):
            _apply_prop_i18n(localized_returns["properties"], rdi_map)

    return {
        "type": "function",
        "function": {
            "name": tool_spec.name,
            "description": localized_desc,
            "parameters": {
                "type": "object",
                "properties": localized_params,
                "required": getattr(tool_spec, "required", []),
            },
            **({"returns": localized_returns} if localized_returns else {}),
        },
    }
