"""
图片理解工具 - 使用多模态大模型分析图片内容
"""

import asyncio
import base64
from pathlib import Path
from typing import Dict, Any, Optional
import io
from urllib.parse import urlparse

import httpx

from ..tool_base import tool
from sagents.utils.logger import logger
from sagents.utils.multimodal_image import (
    compress_image_to_jpeg_bytes_for_llm as _compress_image_to_jpeg_bytes_for_llm,
    get_mime_type as _get_mime_type_util,
)
from sagents.utils.agent_session_helper import (
    get_session_sandbox as _get_session_sandbox_util,
)
from sagents.utils.llm_request_utils import get_multimodal_support

# 尝试导入 PIL，如果不可用则给出警告
try:
    from PIL import Image

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning(
        "PIL (Pillow) 未安装，图片压缩功能将不可用。请安装: pip install Pillow"
    )


class ImageUnderstandingError(Exception):
    """图片理解异常"""

    pass


class ImageUnderstandingTool:
    """图片理解工具 - 将图片加入当前会话的原生多模态上下文"""

    def __init__(self):
        self.supported_formats = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

    def _get_sandbox(self, session_id: str):
        """通过 session_id 获取沙箱。详见
        ``sagents.utils.agent_session_helper.get_session_sandbox``。
        """
        return _get_session_sandbox_util(
            session_id,
            log_prefix="ImageUnderstandingTool",
            error_cls=ImageUnderstandingError,
        )

    def _get_mime_type(self, file_extension: str) -> str:
        """根据文件扩展名获取 MIME 类型。详见
        ``sagents.utils.multimodal_image.get_mime_type``。
        """
        return _get_mime_type_util(file_extension.lower())

    async def _read_image_base64_from_sandbox(self, sandbox, image_path: str) -> str:
        """
        从沙箱读取图片文件并返回 base64 编码

        使用 base64 命令读取图片，避免二进制数据通过文本接口传输的问题

        Args:
            sandbox: 沙箱实例
            image_path: 图片虚拟路径或主机绝对路径

        Returns:
            str: base64 编码的图片数据
        """
        try:
            # 检查文件是否存在
            exists = await sandbox.file_exists(image_path)
            if not exists:
                raise ImageUnderstandingError(f"Image file does not exist: {image_path}")

            # 使用 base64 命令读取图片
            # macOS 的 base64 语法不同，需要使用 -i 指定输入文件
            # Linux 可以直接使用 -w 0 文件路径
            import sys

            if sys.platform == "darwin":
                # macOS: 使用 -i 指定输入文件
                command = f"base64 -i '{image_path}'"
            else:
                # Linux: 使用 -w 0 禁用换行
                command = f"base64 -w 0 '{image_path}'"

            logger.info(f"执行命令: {command}")
            result = await sandbox.execute_command(command=command, timeout=30)

            logger.info(
                f"命令执行结果: success={result.success}, return_code={result.return_code}, stdout长度={len(result.stdout) if result.stdout else 0}, stderr={result.stderr}"
            )

            if not result.success:
                out_len = len(result.stdout) if result.stdout else 0
                raise ImageUnderstandingError(
                    f"Image read command failed: return_code={result.return_code}, stderr={result.stderr}, stdout_bytes={out_len}"
                )

            if not result.stdout or not result.stdout.strip():
                raise ImageUnderstandingError(
                    f"Image read command returned empty data: return_code={result.return_code}, stderr={result.stderr}"
                )

            return result.stdout.strip()

        except ImageUnderstandingError:
            raise
        except Exception as e:
            import traceback

            logger.error(f"从沙箱读取图片失败: {e}\n{traceback.format_exc()}")
            raise ImageUnderstandingError(f"Failed to read image from sandbox: {e}")

    def _resize_image_if_needed(
        self, image_data: bytes, max_resolution: int = 1536
    ) -> bytes:
        """
        调整图片大小，确保长边不超过 max_resolution，并用字节预算兜底

        Args:
            image_data: 图片二进制数据
            max_resolution: 最大边长（默认1536）

        Returns:
            bytes: 调整后的图片数据
        """
        if not PIL_AVAILABLE:
            # 如果 PIL 不可用，直接返回原始数据
            return image_data

        try:
            # 从 bytes 加载图片
            with Image.open(io.BytesIO(image_data)) as img:
                compressed = _compress_image_to_jpeg_bytes_for_llm(
                    img,
                    max_edge=max_resolution,
                )
                logger.info(
                    f"图片压缩: {img.width}x{img.height}, output_bytes={len(compressed)}"
                )
                return compressed

        except Exception as e:
            logger.warning(f"图片压缩失败: {e}，将使用原始图片")
            # 压缩失败时返回原始数据
            return image_data

    def _compress_base64_image_sync(self, base64_data: str, max_resolution: int) -> str:
        """Decode, resize, and re-encode sandbox image data without blocking the event loop."""
        try:
            image_data = base64.b64decode(base64_data)
            compressed_data = self._resize_image_if_needed(image_data, max_resolution)
            return base64.b64encode(compressed_data).decode("utf-8")
        except Exception as e:
            logger.warning(f"图片压缩失败: {e}，使用原始图片")
            return base64_data

    def _encode_remote_image_sync(
        self,
        body: bytes,
        max_resolution: int,
        mime_hint: str,
        image_url: str,
    ) -> tuple[str, str]:
        """Validate/compress/encode downloaded image bytes in a worker thread."""
        if PIL_AVAILABLE:
            try:
                img = Image.open(io.BytesIO(body))
                img.load()
            except Exception as e:
                raise ImageUnderstandingError(
                    f"Downloaded content is not a valid image: {e}"
                ) from e
            try:
                compressed = self._resize_image_if_needed(body, max_resolution)
                b64 = base64.b64encode(compressed).decode("utf-8")
                return b64, "image/jpeg"
            except Exception as e:
                logger.warning(f"远程图片压缩失败: {e}，使用原始数据")
                b64 = base64.b64encode(body).decode("utf-8")
                return b64, mime_hint

        if not mime_hint.startswith("image/"):
            ext = Path(urlparse(image_url).path).suffix.lower()
            if ext not in self.supported_formats:
                raise ImageUnderstandingError(
                    "无法识别为图片：请使用带图片扩展名的 URL，或安装 Pillow"
                )
        b64 = base64.b64encode(body).decode("utf-8")
        return b64, mime_hint

    async def _encode_image_to_base64(
        self, sandbox, image_path: str, max_resolution: int = 512
    ) -> tuple[str, str]:
        """
        将图片文件转换为 base64 编码，并在需要时压缩图片

        Args:
            sandbox: 沙箱实例
            image_path: 图片虚拟路径
            max_resolution: 最大分辨率限制（默认512，即总分辨率不超过512*512）

        Returns:
            tuple: (base64编码的数据, mime类型)
        """
        # 检查文件格式
        file_extension = Path(image_path).suffix.lower()
        if file_extension not in self.supported_formats:
            raise ImageUnderstandingError(
                f"不支持的图片格式: {file_extension}，支持的格式: {', '.join(self.supported_formats)}"
            )

        # 从沙箱读取图片（返回 base64）
        base64_data = await self._read_image_base64_from_sandbox(sandbox, image_path)

        # 如果需要压缩，先 decode -> resize -> encode
        if PIL_AVAILABLE:
            base64_data = await asyncio.to_thread(
                self._compress_base64_image_sync,
                base64_data,
                max_resolution,
            )

        # 压缩后的图片统一使用 JPEG 格式
        mime_type = "image/jpeg"

        return base64_data, mime_type

    def _mime_from_url_or_headers(self, content_type: Optional[str], url: str) -> str:
        """从响应头或 URL 路径推断图片 MIME。"""
        if content_type:
            mime = content_type.split(";")[0].strip().lower()
            if mime.startswith("image/"):
                return mime
        ext = Path(urlparse(url).path).suffix.lower()
        if ext in self.supported_formats:
            return self._get_mime_type(ext)
        return "image/jpeg"

    async def _fetch_url_image_to_base64(
        self, image_url: str, max_resolution: int = 512
    ) -> tuple[str, str]:
        """
        通过 HTTP(S) 拉取图片并转为 base64（与部分仅接受 data URL / base64 的多模态 API 兼容）。
        """
        max_bytes = 20 * 1024 * 1024
        timeout = httpx.Timeout(60.0, connect=15.0)
        try:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=True
            ) as client:
                response = await client.get(image_url)
                response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise ImageUnderstandingError(
                f"Failed to download image: HTTP {e.response.status_code}"
            ) from e
        except httpx.RequestError as e:
            raise ImageUnderstandingError(f"Failed to download image: {e}") from e

        body = response.content
        if len(body) > max_bytes:
            raise ImageUnderstandingError("Image is too large (over 20MB)")
        if not body:
            raise ImageUnderstandingError("Downloaded image is empty")

        mime_hint = self._mime_from_url_or_headers(
            response.headers.get("content-type"), image_url
        )

        return await asyncio.to_thread(
            self._encode_remote_image_sync,
            body,
            max_resolution,
            mime_hint,
            image_url,
        )

    async def _call_llm_with_image(
        self, messages: list, session_id: Optional[str] = None
    ) -> str:
        """
        调用 LLM 进行图片理解

        通过 session_id 获取当前会话的 agent 配置，然后调用模型
        """
        from sagents.session_runtime import (
            get_global_session_manager,
            get_current_session_id,
        )

        # 获取当前 session_id
        current_session_id = session_id or get_current_session_id()
        if not current_session_id:
            raise ImageUnderstandingError("Failed to get current session ID")

        # 获取 session manager 和 session
        session_manager = get_global_session_manager()
        session = session_manager.get(current_session_id)

        if not session:
            raise ImageUnderstandingError(f"Failed to get session: {current_session_id}")

        # 获取 session 的 model 和 model_config
        model = session.model
        model_config = session.model_config.copy()

        if not model:
            raise ImageUnderstandingError("Session model is not initialized")

        # 移除非标准参数
        model_config.pop("max_model_len", None)
        model_config.pop("api_key", None)
        model_config.pop("maxTokens", None)
        model_config.pop("base_url", None)
        model_name = model_config.pop("model", "gpt-3.5-turbo")

        # 调用模型
        try:
            response = await model.chat.completions.create(
                model=model_name, messages=messages, stream=False, **model_config
            )

            # 提取响应内容
            if response.choices and len(response.choices) > 0:
                return response.choices[0].message.content or ""
            else:
                return ""

        except Exception as e:
            error_msg = str(e).lower()
            # 检查是否是模型不支持图片的错误
            if any(
                keyword in error_msg
                for keyword in [
                    "image",
                    "multimodal",
                    "vision",
                    "unsupported",
                    "not supported",
                    "invalid content",
                    "content type",
                    "bad request",
                ]
            ):
                raise ImageUnderstandingError("The current model does not support image understanding")
            else:
                raise e

    def _get_session(self, session_id: Optional[str]):
        """获取当前 live Session。"""
        from sagents.session_runtime import (
            get_global_session_manager,
            get_current_session_id,
        )

        current_session_id = session_id or get_current_session_id()
        if not current_session_id:
            raise ImageUnderstandingError("无法获取当前会话 ID")

        session_manager = get_global_session_manager()
        session = session_manager.get(current_session_id)
        if not session:
            raise ImageUnderstandingError(f"无法获取会话: {current_session_id}")
        return session

    def _get_session_context(self, session):
        """从 Session 包装对象或测试替身中获取 SessionContext。"""
        get_context = getattr(session, "get_context", None)
        if callable(get_context):
            ctx = get_context()
        else:
            ctx = getattr(session, "session_context", None)
        if ctx is None:
            # 兼容旧测试替身，但真实运行时应始终走 Session.get_context()。
            if hasattr(session, "enqueue_user_injection"):
                return session
            raise ImageUnderstandingError("当前会话上下文未初始化")
        return ctx

    def _session_supports_multimodal(self, session) -> bool:
        support = get_multimodal_support(
            client=getattr(session, "model", None),
            model_config=getattr(session, "model_config", None),
        )
        return support is True

    async def _build_native_image_content(
        self, image_path: str, session_id: str
    ) -> tuple[Dict[str, Any], str]:
        """构建注入到下一轮模型请求的 image_url content。"""
        if image_path.startswith(("http://", "https://")):
            return {
                "type": "image_url",
                "image_url": {"url": image_path},
            }, "remote_url"

        sandbox = self._get_sandbox(session_id)
        base64_data, mime_type = await self._encode_image_to_base64(sandbox, image_path)
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{base64_data}"},
        }, mime_type

    def _build_native_prompt(self, image_path: str, prompt: Optional[str]) -> str:
        user_prompt = (
            prompt.strip()
            if prompt and prompt.strip()
            else "请观察这张图片，识别其中的文字和关键视觉信息，并结合当前对话继续完成用户任务。"
        )
        return (
            "【工具注入的图片上下文】\n"
            f"图片来源: {image_path}\n"
            "这是用户要求你查看的图片。请把图片内容作为当前任务的上下文，"
            "在下一步回复中直接基于图片进行理解、描述或推理。\n\n"
            f"用户的图片处理要求: {user_prompt}"
        )

    @tool(
        description_i18n={
            "zh": "将图片加入当前会话的下一轮多模态模型上下文，让 agent 原生观察图片并继续推理；不会额外发起一次模型分析请求。",
            "en": "Attach an image to the next multimodal model turn so the agent can inspect it natively; does not make an extra model analysis call.",
        },
        param_description_i18n={
            "image_path": {
                "zh": "图片文件的虚拟路径（沙箱内路径）或 HTTP/HTTPS URL",
                "en": "Virtual path to the image file (in sandbox) or HTTP/HTTPS URL",
            },
            "session_id": {
                "zh": "当前会话 ID（必填，自动注入）",
                "en": "Current session ID (Required, Auto-injected)",
            },
            "prompt": {
                "zh": "可选的自定义提示词，用于指导下一轮模型如何使用这张图片",
                "en": "Optional custom prompt to guide how the next model turn should use the image",
            },
        },
        param_schema={
            "image_path": {
                "type": "string",
                "description": "Virtual path to the image file or HTTP/HTTPS URL",
            },
            "session_id": {"type": "string", "description": "Session ID"},
            "prompt": {
                "type": "string",
                "description": "Custom prompt for how the next model turn should use the image",
            },
        },
    )
    async def analyze_image(
        self, image_path: str, session_id: str, prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        将图片加入当前会话的下一轮多模态模型上下文。

        Args:
            image_path: 图片文件的虚拟路径（沙箱内路径）或 HTTP/HTTPS URL
            session_id: 当前会话 ID（必填）
            prompt: 可选的自定义提示词

        Returns:
            Dict: 图片上下文注入结果。真正的图片理解由下一轮 agent 模型调用完成。
        """
        logger.info(f"🔍 准备将图片加入多模态上下文: {image_path}")

        try:
            session = self._get_session(session_id)
            if not self._session_supports_multimodal(session):
                return {
                    "status": "error",
                    "message": "当前 agent 模型不支持图片输入，请切换到多模态模型后再分析图片。",
                }

            try:
                image_content, image_format = await self._build_native_image_content(
                    image_path, session_id
                )
            except ImageUnderstandingError as e:
                return {"status": "error", "message": str(e)}

            content = [
                {"type": "text", "text": self._build_native_prompt(image_path, prompt)},
                image_content,
            ]
            session_context = self._get_session_context(session)
            guidance_id = session_context.enqueue_user_injection(
                content,
                extra_metadata={
                    "tool_source": "analyze_image",
                    "image_path": image_path,
                    "image_context_mode": "native_multimodal",
                    "hidden_from_chat": True,
                    "sse_visible": False,
                    "llm_scope": "durable",
                },
            )

            return {
                "status": "success",
                "message": "图片已加入下一轮多模态模型上下文，agent 将直接基于图片继续分析。",
                "data": {
                    "image_path": image_path,
                    "image_format": image_format,
                    "guidance_id": guidance_id,
                    "mode": "native_multimodal_context",
                },
            }

        except Exception as e:
            logger.error(f"图片理解失败: {e}")
            return {"status": "error", "message": f"Image understanding failed: {str(e)}"}
