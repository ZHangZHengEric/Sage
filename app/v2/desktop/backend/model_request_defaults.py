"""Desktop v2 request defaults for models without a verified capability profile.

These host-owned defaults do not import the v1 model/probing implementation.
Verified capability profiles continue to take precedence in run composition.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse


_REASONING_MODEL_PREFIXES: tuple[str, ...] = (
    "o1-",
    "o3-",
    "o4-",
    "gpt-5",  # gpt-5, gpt-5-, gpt-5.x, gpt-5-mini 等 reasoning 系
)


_REASONING_MODEL_EXACT: frozenset[str] = frozenset({"o1", "o3", "o4"})


_VALID_REASONING_EFFORTS: frozenset[str] = frozenset(
    {"minimal", "low", "medium", "high", "xhigh"}
)


_VALID_THINKING_LEVELS: frozenset[str] = _VALID_REASONING_EFFORTS | {"max"}


def is_openai_reasoning_model(model_name: str) -> bool:
    """是否为 OpenAI / 兼容三方的 reasoning 系列模型。

    判定基于显式前缀/精确名单，避免把 ``gpt-4o``/``gpt-4-turbo``/``gpt-3.5`` 这类
    非 reasoning 模型误判进 reasoning 路径。
    """
    if not model_name:
        return False
    name = model_name.strip().lower()
    if not name:
        return False
    if name in _REASONING_MODEL_EXACT:
        return True
    return any(name.startswith(prefix) for prefix in _REASONING_MODEL_PREFIXES)


def is_deepseek_model(model_name: str) -> bool:
    """Return whether the provider-facing model slug is a DeepSeek model."""
    if not model_name:
        return False
    name = model_name.strip().lower()
    return (
        name.startswith("deepseek-")
        or name.startswith("deepseek/")
        or "/deepseek-" in name
    )


def is_official_deepseek_endpoint(base_url: Optional[str]) -> bool:
    """Return whether ``base_url`` is DeepSeek's first-party API endpoint."""
    if not base_url:
        return False
    raw = str(base_url).strip()
    if not raw:
        return False
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    return (parsed.hostname or "").lower() == "api.deepseek.com"


def uses_deepseek_native_protocol(
    model_name: str, base_url: Optional[str]
) -> bool:
    """Whether a request should use DeepSeek's native Chat Completions contract.

    Third-party OpenAI-compatible endpoints may expose ``deepseek-*`` model names,
    but their reasoning/tool-call replay contracts are not guaranteed to match the
    first-party API.
    """
    return is_deepseek_model(model_name) and is_official_deepseek_endpoint(base_url)


def _endpoint_hostname(base_url: Optional[str]) -> str:
    if not base_url:
        return ""
    raw = str(base_url).strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    return (parsed.hostname or "").lower()


def _is_aliyun_model_studio_endpoint(base_url: Optional[str]) -> bool:
    hostname = _endpoint_hostname(base_url)
    return hostname == "dashscope.aliyuncs.com" or hostname.endswith(
        ".dashscope.aliyuncs.com"
    )


def _is_zhipu_endpoint(base_url: Optional[str]) -> bool:
    return _endpoint_hostname(base_url) == "open.bigmodel.cn"


def uses_aliyun_model_studio_protocol(base_url: Optional[str]) -> bool:
    return _is_aliyun_model_studio_endpoint(base_url)


def uses_zhipu_native_protocol(base_url: Optional[str]) -> bool:
    return _is_zhipu_endpoint(base_url)


def get_supported_thinking_levels(
    model_name: str,
    base_url: Optional[str] = None,
) -> tuple[str, ...]:
    """Return the discrete effort values supported by this model/provider pair.

    The frontend vocabulary stays fixed. This native capability list is used at
    the request boundary to map that vocabulary onto provider-specific values.
    An empty tuple means Sage only knows how to toggle thinking for that model.
    """
    name = str(model_name or "").strip().lower()
    if not name:
        return ()
    if uses_deepseek_native_protocol(name, base_url):
        return ("low", "high", "max")
    if is_openai_reasoning_model(name):
        if name.startswith("gpt-5.6"):
            return ("low", "medium", "high", "xhigh", "max")
        if name.startswith(
            ("gpt-5.2", "gpt-5.3", "gpt-5.4", "gpt-5.5")
        ):
            return ("low", "medium", "high", "xhigh")
        if name.startswith("gpt-5.1"):
            return ("low", "medium", "high")
        if name.startswith("gpt-5"):
            return ("minimal", "low", "medium", "high")
        return ("low", "medium", "high")
    if _is_aliyun_model_studio_endpoint(base_url):
        if name.startswith("deepseek-v4-"):
            return ("low", "high", "max")
        if name.startswith("qwen3.8-max-preview"):
            return ("low", "medium", "xhigh")
        if name.startswith(("glm-5", "glm-5.1", "glm-5.2")):
            return ("high", "max")
        if name in {"kimi/kimi-k3", "kimi-k3"}:
            return ("max",)
    if _is_zhipu_endpoint(base_url) and name.startswith("glm-5.2"):
        return ("high", "max")
    return ()


def normalize_reasoning_effort(
    model_name: str,
    thinking_level: str,
    *,
    base_url: Optional[str] = None,
) -> str:
    """Normalize the shared level vocabulary to a provider-supported value."""
    level = str(thinking_level or "").strip().lower()
    if level not in _VALID_THINKING_LEVELS:
        raise ValueError(f"Unsupported thinking level: {thinking_level}")
    supported = get_supported_thinking_levels(model_name, base_url)
    if not supported or level in supported:
        return level
    effort_rank = {
        "minimal": 0,
        "low": 1,
        "medium": 2,
        "high": 3,
        "xhigh": 4,
        "max": 5,
    }
    requested_rank = effort_rank[level]
    for candidate in supported:
        if effort_rank[candidate] >= requested_rank:
            return candidate
    return supported[-1]


def resolve_reasoning_effort(
    enable_thinking: bool,
    env_value: Optional[str] = None,
    default_off: str = "medium",
) -> str:
    """根据是否启用思考与环境变量解析最终的 ``reasoning_effort``。

    - ``enable_thinking=True`` → ``"medium"``
    - ``enable_thinking=False`` → ``env_value`` 优先（小写），无效或为空时回退 ``default_off``
    - 合法值：minimal / low / medium / high / xhigh
    """
    if enable_thinking:
        return "medium"
    if env_value is None:
        return default_off
    candidate = env_value.strip().lower()
    if candidate and candidate in _VALID_REASONING_EFFORTS:
        return candidate
    return default_off


def build_llm_extra_body(
    model_name: str,
    *,
    base_url: Optional[str] = None,
    enable_thinking: bool = False,
    thinking_level: Optional[str] = None,
    step_name: Optional[str] = None,
    reasoning_effort_off_env: Optional[str] = None,
    default_off: str = "medium",
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """构建与主 Agent 一致的 chat.completions ``extra_body``。

    - OpenAI reasoning（o1/o3/o4/gpt-5*）：设置 ``reasoning_effort``
    - 其他模型：设置 ``enable_thinking`` / ``thinking`` / ``chat_template_kwargs``
    - ``extra``：调用方附加字段（如能力探测的 ``top_k``）
    """
    extra_body: Dict[str, Any] = {}
    if step_name:
        extra_body["_step_name"] = step_name

    if thinking_level:
        enable_thinking = True

    supported_thinking_levels = get_supported_thinking_levels(
        model_name, base_url
    )
    if is_openai_reasoning_model(model_name):
        extra_body["reasoning_effort"] = (
            normalize_reasoning_effort(
                model_name, thinking_level, base_url=base_url
            )
            if thinking_level
            else resolve_reasoning_effort(
                enable_thinking=enable_thinking,
                env_value=reasoning_effort_off_env,
                default_off=default_off,
            )
        )
    elif uses_deepseek_native_protocol(model_name, base_url):
        # The first-party Chat Completions API only documents these native
        # fields. Do not mix in local-engine compatibility switches such as
        # enable_thinking/chat_template_kwargs.
        extra_body["thinking"] = {
            "type": "enabled" if enable_thinking else "disabled"
        }
        if thinking_level:
            extra_body["reasoning_effort"] = normalize_reasoning_effort(
                model_name, thinking_level, base_url=base_url
            )
    elif uses_aliyun_model_studio_protocol(base_url):
        extra_body["enable_thinking"] = enable_thinking
        if thinking_level and supported_thinking_levels:
            extra_body["reasoning_effort"] = normalize_reasoning_effort(
                model_name, thinking_level, base_url=base_url
            )
    elif uses_zhipu_native_protocol(base_url):
        extra_body["thinking"] = {
            "type": "enabled" if enable_thinking else "disabled"
        }
        if thinking_level and supported_thinking_levels:
            extra_body["reasoning_effort"] = normalize_reasoning_effort(
                model_name, thinking_level, base_url=base_url
            )
    else:
        extra_body["chat_template_kwargs"] = {"enable_thinking": enable_thinking}
        extra_body["enable_thinking"] = enable_thinking
        extra_body["thinking"] = {
            "type": "enabled" if enable_thinking else "disabled"
        }
    if extra:
        extra_body.update(extra)
    return extra_body
