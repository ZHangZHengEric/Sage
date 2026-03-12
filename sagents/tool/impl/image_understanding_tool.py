"""
图片理解工具 - 使用多模态大模型分析图片内容
"""

import base64
from pathlib import Path
from typing import Dict, Any, Optional
import os

from ..tool_base import tool
from sagents.utils.logger import logger


class ImageUnderstandingError(Exception):
    """图片理解异常"""
    pass


class ImageUnderstandingTool:
    """图片理解工具 - 分析图片内容并返回详细描述"""

    def __init__(self):
        self.supported_formats = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}

    def _get_mime_type(self, file_extension: str) -> str:
        """根据文件扩展名获取 MIME 类型"""
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.bmp': 'image/bmp',
        }
        return mime_types.get(file_extension.lower(), 'image/jpeg')

    def _encode_image_to_base64(self, image_path: str) -> tuple[str, str]:
        """
        将图片文件转换为 base64 编码

        Args:
            image_path: 图片文件路径

        Returns:
            tuple: (base64编码的数据, mime类型)
        """
        path_obj = Path(image_path)

        if not path_obj.exists():
            raise ImageUnderstandingError(f"图片文件不存在: {image_path}")

        # 检查文件格式
        file_extension = path_obj.suffix.lower()
        if file_extension not in self.supported_formats:
            raise ImageUnderstandingError(f"不支持的图片格式: {file_extension}，支持的格式: {', '.join(self.supported_formats)}")

        # 读取文件并转换为 base64
        try:
            with open(path_obj, 'rb') as f:
                image_data = f.read()
            base64_data = base64.b64encode(image_data).decode('utf-8')
            mime_type = self._get_mime_type(file_extension)
            return base64_data, mime_type
        except Exception as e:
            raise ImageUnderstandingError(f"读取图片文件失败: {e}")

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
            "image_path": {"zh": "图片文件的绝对路径", "en": "Absolute path to the image file"},
            "session_id": {"zh": "当前会话 ID", "en": "Current session ID"},
            "prompt": {"zh": "可选的自定义提示词，用于指导模型如何分析图片", "en": "Optional custom prompt to guide how the model analyzes the image"},
        }
    )
    async def analyze_image(self, image_path: str, session_id:str, prompt: Optional[str] = None) -> Dict[str, Any]:
        """
        分析图片内容，使用当前会话的多模态大模型

        Args:
            image_path: 图片文件的绝对路径
            session_id: 当前会话 ID
            prompt: 可选的自定义提示词

        Returns:
            Dict: 包含图片详细描述和文字识别结果
        """
        logger.info(f"🔍 开始分析图片: {image_path}")

        try:
            # 1. 验证图片文件
            if not os.path.isabs(image_path):
                return {
                    "status": "error",
                    "message": f"请提供图片的绝对路径，当前路径: {image_path}"
                }

            # 2. 将图片转换为 base64
            try:
                base64_data, mime_type = self._encode_image_to_base64(image_path)
            except ImageUnderstandingError as e:
                return {
                    "status": "error",
                    "message": str(e)
                }

            # 3. 构建默认提示词
            default_prompt = """请详细分析这张图片，并提供以下信息：

1. 图片整体描述：描述图片的主要内容、场景、风格等
2. 图片上的文字：识别并转录图片中出现的所有文字内容
3. 细节描述：描述图片中的重要细节、物体、人物、颜色等

请以结构化的方式返回分析结果。"""

            user_prompt = prompt if prompt else default_prompt

            # 4. 构建消息格式（OpenAI 多模态格式）
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{base64_data}"
                            }
                        }
                    ]
                }
            ]

            # 5. 调用 LLM 进行图片理解
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
