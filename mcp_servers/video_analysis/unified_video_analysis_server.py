#!/usr/bin/env python3
"""
Unified video analysis service.

The tool surface stays small while provider credentials, URLs, and model names
are selected from environment variables.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import FastMCP

from sagents.tool.mcp_tool_base import sage_mcp_tool
from sagents.utils.logger import logger

mcp = FastMCP("Unified Video Analysis Service")

DEFAULT_PROMPT = """请分析这个视频，并重点返回：

1. 视频整体内容和主要事件
2. 关键人物、物体、场景和动作
3. 重要时间点或片段
4. 视频中的文字、画面信息和可听到的关键信息
5. 可以直接用于后续创作、剪辑或判断的结论

请用结构化方式回答。"""

SUPPORTED_VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".avi",
    ".mkv",
    ".webm",
    ".mpeg",
    ".mpg",
}


class VideoAnalysisError(Exception):
    """Raised when video analysis cannot proceed."""


@dataclass
class VideoInput:
    source: str
    mime_type: str
    is_url: bool
    data_url: Optional[str] = None
    base64_data: Optional[str] = None


class BaseVideoProvider:
    name = ""
    required_env_vars: tuple[str, ...] = ()

    @classmethod
    def is_available(cls) -> bool:
        return all((os.environ.get(var) or "").strip() for var in cls.required_env_vars)

    @classmethod
    def missing_env_vars(cls) -> list[str]:
        return [
            var
            for var in cls.required_env_vars
            if not (os.environ.get(var) or "").strip()
        ]

    async def analyze(self, video: VideoInput, prompt: str) -> str:
        raise NotImplementedError


class QwenVideoProvider(BaseVideoProvider):
    """OpenAI-compatible video analysis provider for Alibaba Cloud Bailian/DashScope."""

    name = "qwen"
    required_env_vars = ("QWEN_VIDEO_API_KEY", "QWEN_VIDEO_MODEL")
    default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    @classmethod
    def api_key(cls) -> str:
        return (os.environ.get("QWEN_VIDEO_API_KEY") or "").strip()

    @classmethod
    def model(cls) -> str:
        return (os.environ.get("QWEN_VIDEO_MODEL") or "").strip()

    @classmethod
    def base_url(cls) -> str:
        return (
            os.environ.get("QWEN_VIDEO_BASE_URL") or cls.default_base_url
        ).strip().rstrip("/")

    async def analyze(self, video: VideoInput, prompt: str) -> str:
        video_url = video.source if video.is_url else video.data_url
        if not video_url:
            raise VideoAnalysisError(
                "本地视频无法转换为模型可读取的 data URL"
            )

        payload = {
            "model": self.model(),
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "video_url", "video_url": {"url": video_url}},
                    ],
                }
            ],
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key()}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(180.0, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.base_url()}/chat/completions",
                headers=headers,
                json=payload,
            )
        if response.status_code in {401, 403}:
            raise VideoAnalysisError(
                "Qwen 视频分析 API Key 无效或没有模型权限"
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise VideoAnalysisError(
                "Qwen 视频分析请求失败: "
                f"HTTP {response.status_code} {response.text[:500]}"
            ) from exc

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise VideoAnalysisError("Qwen 视频分析未返回结果")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            return "\n".join(str(item.get("text", item)) for item in content)
        return str(content or "")


class GeminiVideoProvider(BaseVideoProvider):
    """Native Gemini generateContent provider."""

    name = "gemini"
    required_env_vars = ("GEMINI_VIDEO_API_KEY", "GEMINI_VIDEO_MODEL")
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"

    @classmethod
    def api_key(cls) -> str:
        return (os.environ.get("GEMINI_VIDEO_API_KEY") or "").strip()

    @classmethod
    def model(cls) -> str:
        return (os.environ.get("GEMINI_VIDEO_MODEL") or "").strip()

    @classmethod
    def base_url(cls) -> str:
        return (
            os.environ.get("GEMINI_VIDEO_BASE_URL") or cls.default_base_url
        ).strip().rstrip("/")

    async def analyze(self, video: VideoInput, prompt: str) -> str:
        if video.is_url:
            video_part: dict[str, Any] = {
                "file_data": {
                    "file_uri": video.source,
                    "mime_type": video.mime_type,
                }
            }
        else:
            if not video.base64_data:
                raise VideoAnalysisError(
                    "本地视频无法转换为 Gemini inline_data"
                )
            video_part = {
                "inline_data": {
                    "mime_type": video.mime_type,
                    "data": video.base64_data,
                }
            }

        payload = {
            "contents": [
                {
                    "parts": [
                        video_part,
                        {"text": prompt},
                    ]
                }
            ]
        }
        url = f"{self.base_url()}/models/{self.model()}:generateContent"
        headers = {
            "x-goog-api-key": self.api_key(),
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(180.0, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
        if response.status_code in {401, 403}:
            raise VideoAnalysisError(
                "Gemini 视频分析 API Key 无效或没有模型权限"
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise VideoAnalysisError(
                "Gemini 视频分析请求失败: "
                f"HTTP {response.status_code} {response.text[:500]}"
            ) from exc

        data = response.json()
        texts: list[str] = []
        for candidate in data.get("candidates") or []:
            content = candidate.get("content") or {}
            for part in content.get("parts") or []:
                if "text" in part:
                    texts.append(str(part["text"]))
        if not texts:
            raise VideoAnalysisError("Gemini 视频分析未返回文本结果")
        return "\n".join(texts)


PROVIDER_CLASSES: tuple[type[BaseVideoProvider], ...] = (
    QwenVideoProvider,
    GeminiVideoProvider,
)


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def _guess_video_mime(path_or_url: str) -> str:
    mime_type, _ = mimetypes.guess_type(path_or_url)
    if mime_type and mime_type.startswith("video/"):
        return mime_type
    return "video/mp4"


def _validate_video_extension(path_or_url: str) -> None:
    suffix = Path(urlparse(path_or_url).path).suffix.lower()
    if suffix and suffix not in SUPPORTED_VIDEO_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_VIDEO_EXTENSIONS))
        raise VideoAnalysisError(
            f"不支持的视频格式: {suffix}，支持的格式: {supported}"
        )


def _read_local_video_base64(video_path: str) -> str:
    path = Path(video_path).expanduser()
    if not path.exists():
        raise VideoAnalysisError(f"视频文件不存在: {video_path}")
    if not path.is_file():
        raise VideoAnalysisError(f"视频路径不是文件: {video_path}")
    max_bytes = int(
        os.environ.get(
            "VIDEO_ANALYSIS_INLINE_MAX_BYTES",
            str(20 * 1024 * 1024),
        )
    )
    size = path.stat().st_size
    if size > max_bytes:
        raise VideoAnalysisError(
            f"视频文件过大（{size} bytes），超过本地 inline 限制 "
            f"{max_bytes} bytes；请改用可公开访问的 URL 或提高 "
            "VIDEO_ANALYSIS_INLINE_MAX_BYTES"
        )
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def prepare_video_input(video_path: str) -> VideoInput:
    source = (video_path or "").strip()
    if not source:
        raise VideoAnalysisError("video_path 不能为空")
    _validate_video_extension(source)
    mime_type = _guess_video_mime(source)

    if _is_url(source):
        return VideoInput(source=source, mime_type=mime_type, is_url=True)

    base64_data = _read_local_video_base64(source)
    return VideoInput(
        source=source,
        mime_type=mime_type,
        is_url=False,
        data_url=f"data:{mime_type};base64,{base64_data}",
        base64_data=base64_data,
    )


def get_available_providers() -> list[BaseVideoProvider]:
    preferred = (os.environ.get("SAGE_VIDEO_ANALYSIS_PROVIDER") or "").strip().lower()
    provider_classes = list(PROVIDER_CLASSES)
    if preferred:
        provider_classes.sort(key=lambda cls: 0 if cls.name == preferred else 1)

    providers: list[BaseVideoProvider] = []
    for provider_class in provider_classes:
        if provider_class.is_available():
            providers.append(provider_class())
    return providers


def get_config_error() -> str:
    lines = [
        "未配置任何可用的视频分析提供商。",
        "",
        "需要至少配置以下一组环境变量:",
        "",
        "Qwen / 阿里云百炼（OpenAI-compatible）:",
        "  QWEN_VIDEO_API_KEY=your_api_key",
        "  QWEN_VIDEO_MODEL=qwen3.5-omni-flash",
        "  QWEN_VIDEO_BASE_URL=https://dashscope.aliyuncs.com/"
        "compatible-mode/v1  # 可选",
        "",
        "Gemini:",
        "  GEMINI_VIDEO_API_KEY=your_api_key",
        "  GEMINI_VIDEO_MODEL=gemini-3.5-flash",
        "  GEMINI_VIDEO_BASE_URL=https://generativelanguage.googleapis.com/"
        "v1beta  # 可选",
        "",
        "可选: SAGE_VIDEO_ANALYSIS_PROVIDER=qwen 或 gemini",
    ]
    return "\n".join(lines)


async def analyze_video_impl(
    video_path: str,
    prompt: Optional[str] = None,
) -> dict[str, Any]:
    providers = get_available_providers()
    if not providers:
        return {
            "status": "error",
            "message": "未配置任何可用的视频分析提供商",
            "config_help": get_config_error(),
        }

    try:
        video = prepare_video_input(video_path)
    except VideoAnalysisError as exc:
        return {"status": "error", "message": str(exc)}

    user_prompt = (prompt or "").strip() or DEFAULT_PROMPT
    errors: list[dict[str, str]] = []
    for provider in providers:
        try:
            result = await provider.analyze(video, user_prompt)
            return {
                "status": "success",
                "message": "视频分析完成",
                "data": {
                    "description": result,
                    "video_path": video.source,
                    "mime_type": video.mime_type,
                    "provider": provider.name,
                },
            }
        except Exception as exc:
            logger.warning(f"视频分析提供商 {provider.name} 失败: {exc}")
            errors.append({"provider": provider.name, "error": str(exc)})

    return {
        "status": "error",
        "message": "所有视频分析提供商都失败了",
        "errors": errors,
    }


@mcp.tool(
    name="analyze_video",
    description=(
        "Analyze the contents of a video file path or HTTP/HTTPS video URL with "
        "a configured video-capable multimodal model. Use this when the user "
        "asks to summarize a video, identify scenes/actions/objects/people, "
        "extract on-screen text or audible cues, answer questions about video "
        "content, or find important moments and approximate timestamps. Do not "
        "use it for still-image-only analysis, web search, video generation, or "
        "video editing. Returns JSON containing status, the analysis text, input "
        "video path or URL, MIME type, and any configuration or execution errors."
    ),
)
@sage_mcp_tool(
    server_name="unified_video_analysis_server",
    description_i18n={
        "zh": (
            "用已配置的可理解视频的多模态模型，分析一个视频文件路径或 "
            "HTTP/HTTPS 视频 URL。适合在用户要求总结视频、识别场景/动作/"
            "物体/人物、提取画面文字或可听到的关键信息、"
            "回答视频内容问题、寻找重要片段和大致时间点时使用。"
            "不要用于纯图片分析、网页搜索、视频生成或视频剪辑。"
            "返回包含状态、分析文本、输入视频路径或 URL、MIME 类型、"
            "配置或执行错误的 JSON。"
        ),
        "en": (
            "Analyze the contents of a video file path or HTTP/HTTPS video URL "
            "with a configured video-capable multimodal model. Use this when the "
            "user asks to summarize a video, identify scenes/actions/objects/"
            "people, extract on-screen text or audible cues, answer questions "
            "about video content, or find important moments and approximate "
            "timestamps. Do not use it for still-image-only analysis, web search, "
            "video generation, or video editing. Returns JSON containing status, "
            "the analysis text, input video path or URL, MIME type, and any "
            "configuration or execution errors."
        ),
        "pt": (
            "Analisa o conteúdo de um caminho de arquivo de vídeo ou URL de "
            "vídeo HTTP/HTTPS com um modelo multimodal configurado que entende "
            "vídeo. Use quando o usuário pedir resumo, cenas, ações, objetos, "
            "pessoas, texto na tela, sinais audíveis, respostas sobre o conteúdo "
            "ou momentos importantes com horários aproximados. Não use para "
            "análise apenas de imagens, busca na web, geração de vídeo ou edição "
            "de vídeo. Retorna JSON com status, análise, caminho ou URL, tipo "
            "MIME e erros de configuração ou execução."
        ),
    },
    param_description_i18n={
        "video_path": {
            "zh": (
                "要分析的视频文件路径或 HTTP/HTTPS 视频 URL。"
                "如果用户提供的是本地文件，直接传入该文件路径。"
            ),
            "en": (
                "Video file path or HTTP/HTTPS video URL to analyze. If the user "
                "provides a local file, pass that file path directly."
            ),
            "pt": (
                "Caminho do arquivo de vídeo ou URL HTTP/HTTPS a analisar. Se o "
                "usuário fornecer um arquivo local, passe esse caminho diretamente."
            ),
        },
        "prompt": {
            "zh": (
                "可选的自定义分析提示词。用于说明要回答的问题、"
                "关注的时间段、需要的输出结构或需要优先提取的信息；"
                "不要放 API Key、模型名或 Base URL。"
            ),
            "en": (
                "Optional custom analysis prompt. Use it to specify the question, "
                "time range, desired output structure, or details to prioritize; "
                "do not include API keys, model names, or base URLs."
            ),
            "pt": (
                "Prompt personalizado opcional para a análise. Use para indicar "
                "a pergunta, intervalo de tempo, estrutura de saída desejada ou "
                "detalhes prioritários; não inclua chaves de API, nomes de modelo "
                "ou base URLs."
            ),
        },
    },
)
async def analyze_video(video_path: str, prompt: str = "") -> str:
    """
    Analyze video content.

    Args:
        video_path: Video file path or HTTP/HTTPS URL.
        prompt: Optional custom prompt.

    Returns:
        JSON string with the video analysis result.
    """
    result = await analyze_video_impl(video_path=video_path, prompt=prompt)
    return json.dumps(result, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()
