"""
图片理解工具 - 使用多模态大模型分析图片内容
"""

import asyncio
import base64
from pathlib import Path
from typing import Dict, Any, Optional
import os
import io
from urllib.parse import urlparse

import httpx

from ..tool_base import tool
from sagents.utils.logger import logger
from sagents.utils.multimodal_image import get_mime_type as _get_mime_type_util
from sagents.utils.agent_session_helper import get_session_sandbox as _get_session_sandbox_util

# 尝试导入 PIL，如果不可用则给出警告
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("PIL (Pillow) 未安装，图片压缩功能将不可用。请安装: pip install Pillow")


class ImageUnderstandingError(Exception):
    """图片理解异常"""
    pass


class ImageUnderstandingTool:
    """图片理解工具 - 分析图片内容并返回详细描述"""

    def __init__(self):
        self.supported_formats = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}

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
                raise ImageUnderstandingError(f"图片文件不存在: {image_path}")

            # 使用 base64 命令读取图片
            # macOS 的 base64 语法不同，需要使用 -i 指定输入文件
            # Linux 可以直接使用 -w 0 文件路径
            import sys
            if sys.platform == 'darwin':
                # macOS: 使用 -i 指定输入文件
                command = f"base64 -i '{image_path}'"
            else:
                # Linux: 使用 -w 0 禁用换行
                command = f"base64 -w 0 '{image_path}'"

            logger.info(f"执行命令: {command}")
            result = await sandbox.execute_command(
                command=command,
                timeout=30
            )

            logger.info(f"命令执行结果: success={result.success}, return_code={result.return_code}, stdout长度={len(result.stdout) if result.stdout else 0}, stderr={result.stderr}")

            if not result.success:
                raise ImageUnderstandingError(f"读取图片命令失败: return_code={result.return_code}, stderr={result.stderr}, stdout={result.stdout[:200] if result.stdout else 'empty'}")

            if not result.stdout or not result.stdout.strip():
                raise ImageUnderstandingError(f"读取图片命令返回空数据: return_code={result.return_code}, stderr={result.stderr}")

            return result.stdout.strip()

        except ImageUnderstandingError:
            raise
        except Exception as e:
            import traceback
            logger.error(f"从沙箱读取图片失败: {e}\n{traceback.format_exc()}")
            raise ImageUnderstandingError(f"从沙箱读取图片失败: {e}")

    def _resize_image_if_needed(self, image_data: bytes, max_resolution: int = 512) -> bytes:
        """
        调整图片大小，确保总分辨率不超过 max_resolution * max_resolution

        Args:
            image_data: 图片二进制数据
            max_resolution: 最大分辨率（默认512，即总分辨率不超过512*512）

        Returns:
            bytes: 调整后的图片数据
        """
        if not PIL_AVAILABLE:
            # 如果 PIL 不可用，直接返回原始数据
            return image_data

        try:
            # 从 bytes 加载图片
            img = Image.open(io.BytesIO(image_data))

            # 转换为 RGB 模式（处理 RGBA 等模式）
            if img.mode in ('RGBA', 'LA', 'P'):
                # 创建白色背景
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if img.mode in ('RGBA', 'LA'):
                    background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = background
                else:
                    img = img.convert('RGB')
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # 计算当前总分辨率
            current_resolution = img.width * img.height
            max_total_resolution = max_resolution * max_resolution

            # 如果当前分辨率已经小于等于最大允许分辨率，直接返回
            if current_resolution <= max_total_resolution:
                logger.info(f"图片分辨率 {img.width}x{img.height} ({current_resolution}) 在限制范围内，无需压缩")
                buffer = io.BytesIO()
                # 保存为 JPEG 格式，质量85%
                img.save(buffer, format='JPEG', quality=85, optimize=True)
                return buffer.getvalue()

            # 计算缩放比例
            scale_factor = (max_total_resolution / current_resolution) ** 0.5
            new_width = int(img.width * scale_factor)
            new_height = int(img.height * scale_factor)

            logger.info(f"图片压缩: {img.width}x{img.height} ({current_resolution}) -> {new_width}x{new_height} ({new_width * new_height})")

            # 调整图片大小
            resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # 保存到内存
            buffer = io.BytesIO()
            resized_img.save(buffer, format='JPEG', quality=85, optimize=True)
            return buffer.getvalue()

        except Exception as e:
            logger.warning(f"图片压缩失败: {e}，将使用原始图片")
            # 压缩失败时返回原始数据
            return image_data

    def _compress_base64_image_sync(self, base64_data: str, max_resolution: int) -> str:
        """Decode, resize, and re-encode sandbox image data without blocking the event loop."""
        try:
            image_data = base64.b64decode(base64_data)
            compressed_data = self._resize_image_if_needed(image_data, max_resolution)
            return base64.b64encode(compressed_data).decode('utf-8')
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
                raise ImageUnderstandingError(f"下载内容不是有效图片: {e}") from e
            try:
                compressed = self._resize_image_if_needed(body, max_resolution)
                b64 = base64.b64encode(compressed).decode('utf-8')
                return b64, 'image/jpeg'
            except Exception as e:
                logger.warning(f"远程图片压缩失败: {e}，使用原始数据")
                b64 = base64.b64encode(body).decode('utf-8')
                return b64, mime_hint

        if not mime_hint.startswith('image/'):
            ext = Path(urlparse(image_url).path).suffix.lower()
            if ext not in self.supported_formats:
                raise ImageUnderstandingError(
                    "无法识别为图片：请使用带图片扩展名的 URL，或安装 Pillow"
                )
        b64 = base64.b64encode(body).decode('utf-8')
        return b64, mime_hint

    async def _encode_image_to_base64(self, sandbox, image_path: str, max_resolution: int = 512) -> tuple[str, str]:
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
            raise ImageUnderstandingError(f"不支持的图片格式: {file_extension}，支持的格式: {', '.join(self.supported_formats)}")

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
        mime_type = 'image/jpeg'

        return base64_data, mime_type

    def _mime_from_url_or_headers(self, content_type: Optional[str], url: str) -> str:
        """从响应头或 URL 路径推断图片 MIME。"""
        if content_type:
            mime = content_type.split(';')[0].strip().lower()
            if mime.startswith('image/'):
                return mime
        ext = Path(urlparse(url).path).suffix.lower()
        if ext in self.supported_formats:
            return self._get_mime_type(ext)
        return 'image/jpeg'

    async def _fetch_url_image_to_base64(self, image_url: str, max_resolution: int = 512) -> tuple[str, str]:
        """
        通过 HTTP(S) 拉取图片并转为 base64（与部分仅接受 data URL / base64 的多模态 API 兼容）。
        """
        max_bytes = 20 * 1024 * 1024
        timeout = httpx.Timeout(60.0, connect=15.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get(image_url)
                response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise ImageUnderstandingError(f"无法下载图片: HTTP {e.response.status_code}") from e
        except httpx.RequestError as e:
            raise ImageUnderstandingError(f"无法下载图片: {e}") from e

        body = response.content
        if len(body) > max_bytes:
            raise ImageUnderstandingError("图片过大（超过 20MB）")
        if not body:
            raise ImageUnderstandingError("下载的图片为空")

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

    async def _call_llm_with_image(self, messages: list, session_id: Optional[str] = None) -> str:
        """
        调用 LLM 进行图片理解

        通过 session_id 获取当前会话的 agent 配置，然后调用模型
        """
        from sagents.session_runtime import get_global_session_manager, get_current_session_id

        # 获取当前 session_id
        current_session_id = session_id or get_current_session_id()
        if not current_session_id:
            raise ImageUnderstandingError("无法获取当前会话 ID")

        # 获取 session manager 和 session
        session_manager = get_global_session_manager()
        session = session_manager.get(current_session_id)

        if not session:
            raise ImageUnderstandingError(f"无法获取会话: {current_session_id}")

        # 获取 session 的 model 和 model_config
        model = session.model
        model_config = session.model_config.copy()

        if not model:
            raise ImageUnderstandingError("会话模型未初始化")

        # 移除非标准参数
        model_config.pop('max_model_len', None)
        model_config.pop('api_key', None)
        model_config.pop('maxTokens', None)
        model_config.pop('base_url', None)
        model_name = model_config.pop('model', 'gpt-3.5-turbo')

        # 调用模型
        try:
            response = await model.chat.completions.create(
                model=model_name,
                messages=messages,
                stream=False,
                **model_config
            )

            # 提取响应内容
            if response.choices and len(response.choices) > 0:
                return response.choices[0].message.content or ""
            else:
                return ""

        except Exception as e:
            error_msg = str(e).lower()
            # 检查是否是模型不支持图片的错误
            if any(keyword in error_msg for keyword in [
                "image", "multimodal", "vision", "unsupported",
                "not supported", "invalid content", "content type", "bad request"
            ]):
                raise ImageUnderstandingError("当前模型不支持图片理解")
            else:
                raise e

    @tool(
        description_i18n={
            "zh": "分析图片内容，返回图片的详细描述以及图片上的文字。使用当前会话的多模态大模型进行理解。",
            "en": "Analyze image content and return detailed description and text on the image. Uses the current session's multimodal model.",
        },
        param_description_i18n={
            "image_path": {"zh": "图片文件的虚拟路径（沙箱内路径）或 HTTP/HTTPS URL", "en": "Virtual path to the image file (in sandbox) or HTTP/HTTPS URL"},
            "session_id": {"zh": "当前会话 ID（必填，自动注入）", "en": "Current session ID (Required, Auto-injected)"},
            "prompt": {"zh": "可选的自定义提示词，用于指导模型如何分析图片", "en": "Optional custom prompt to guide how the model analyzes the image"},
        },
        param_schema={
            "image_path": {"type": "string", "description": "Virtual path to the image file or HTTP/HTTPS URL"},
            "session_id": {"type": "string", "description": "Session ID"},
            "prompt": {"type": "string", "description": "Custom prompt for image analysis"},
        }
    )
    async def analyze_image(self, image_path: str, session_id: str, prompt: Optional[str] = None) -> Dict[str, Any]:
        """
        分析图片内容，使用当前会话的多模态大模型

        Args:
            image_path: 图片文件的虚拟路径（沙箱内路径）或 HTTP/HTTPS URL
            session_id: 当前会话 ID（必填）
            prompt: 可选的自定义提示词

        Returns:
            Dict: 包含图片详细描述和文字识别结果
        """
        logger.info(f"🔍 开始分析图片: {image_path}")

        try:
            # 1. 检查是否为 HTTP/HTTPS URL
            is_url = image_path.startswith(('http://', 'https://'))

            # 2. 构建默认提示词
            default_prompt = """请详细分析这张图片，并提供以下信息：

1. 图片整体描述：描述图片的主要内容、场景、风格等
2. 图片上的文字：识别并转录图片中出现的所有文字内容
3. 细节描述：描述图片中的重要细节、物体、人物、颜色等

请以结构化的方式返回分析结果。"""

            user_prompt = prompt if prompt else default_prompt

            # 3. 构建消息格式（OpenAI 多模态格式）
            mime_type = "image/jpeg"  # 默认值
            if is_url:
                # 远程图片先下载再 base64，兼容不接受直链的多模态网关（如部分阿里云接口）
                logger.info(f"拉取 URL 图片并转为 base64: {image_path}")
                try:
                    base64_data, mime_type = await self._fetch_url_image_to_base64(image_path)
                except ImageUnderstandingError as e:
                    return {
                        "status": "error",
                        "message": str(e),
                    }
                image_content = {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{base64_data}",
                    },
                }
            else:
                # 对于沙箱内的本地图片，通过沙箱读取并转换为 base64
                try:
                    sandbox = self._get_sandbox(session_id)
                    base64_data, mime_type = await self._encode_image_to_base64(sandbox, image_path)
                    image_content = {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_data}"
                        }
                    }
                except ImageUnderstandingError as e:
                    return {
                        "status": "error",
                        "message": str(e)
                    }

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        image_content
                    ]
                }
            ]

            # 4. 调用 LLM 进行图片理解
            try:
                analysis_result = await self._call_llm_with_image(messages, session_id)

                return {
                    "status": "success",
                    "message": "图片分析完成",
                    "data": {
                        "description": analysis_result,
                        "image_path": image_path,
                        "mime_type": mime_type
                    }
                }

            except ImageUnderstandingError as e:
                return {
                    "status": "error",
                    "message": f"当前模型不支持图片理解，请使用多模态模型（如 GPT-4V、Claude 3、Qwen-VL 等）"
                }

        except Exception as e:
            logger.error(f"图片理解失败: {e}")
            return {
                "status": "error",
                "message": f"图片理解失败: {str(e)}"
            }
