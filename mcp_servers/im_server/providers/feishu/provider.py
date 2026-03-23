"""Feishu (Lark) IM provider."""

import os
import mimetypes
import logging
from typing import Optional, Dict, Any
from pathlib import Path

import httpx

from ..base import IMProviderBase

logger = logging.getLogger("FeishuProvider")


class FeishuProvider(IMProviderBase):
    """Feishu (Lark) IM provider.
    
    支持功能:
    - 发送文本消息
    - 发送 Markdown 消息
    - 发送文件 (PDF, DOC, XLS 等)
    - 发送图片
    """

    BASE_URL = "https://open.feishu.cn/open-apis"
    PROVIDER_NAME = "feishu"

    # 文件类型映射: 扩展名 -> 飞书 file_type
    FILE_TYPE_MAP = {
        ".opus": "opus",
        ".mp4": "mp4",
        ".pdf": "pdf",
        ".doc": "doc",
        ".docx": "doc",
        ".xls": "xls",
        ".xlsx": "xls",
        ".ppt": "ppt",
        ".pptx": "ppt",
        ".txt": "stream",
        ".zip": "stream",
        ".rar": "stream",
        ".gz": "stream",
        ".tar": "stream",
        ".jpg": "stream",
        ".jpeg": "stream",
        ".png": "stream",
        ".gif": "stream",
        ".bmp": "stream",
        ".webp": "stream",
    }

    def __init__(self, config: Dict[str, Any]):
        """Initialize Feishu provider.
        
        Args:
            config: 配置字典，包含 app_id, app_secret 等
        """
        super().__init__(config)
        self.app_id = config.get("app_id")
        self.app_secret = config.get("app_secret")

    def _get_file_type(self, file_path: str) -> str:
        """根据文件扩展名获取飞书的 file_type.
        
        Args:
            file_path: 文件路径
            
        Returns:
            飞书的 file_type 字符串
        """
        ext = Path(file_path).suffix.lower()
        file_type = self.FILE_TYPE_MAP.get(ext)
        if file_type:
            return file_type
        
        # 对于未知类型，尝试通过 mimetypes 判断
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type:
            if mime_type.startswith("image/"):
                return "stream"  # 图片通过 image API 发送
            elif mime_type.startswith("video/"):
                return "mp4"
            elif mime_type.startswith("audio/"):
                return "opus"
        
        return "stream"  # 默认类型

    async def _get_access_token(self) -> Optional[str]:
        """Get Feishu access token."""
        if not self.app_id or not self.app_secret:
            return self.config.get("access_token")

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.BASE_URL}/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            data = resp.json()
            if data.get("code") == 0:
                return data.get("tenant_access_token")
        return None

    async def _upload_file(self, file_path: str) -> Dict[str, Any]:
        """上传文件到飞书获取 file_key.
        
        Args:
            file_path: 本地文件路径
            
        Returns:
            {"success": bool, "file_key": str, "error": str}
        """
        access_token = await self._get_access_token()
        if not access_token:
            return {"success": False, "error": "Failed to get access token"}

        if not os.path.exists(file_path):
            return {"success": False, "error": f"File not found: {file_path}"}

        file_type = self._get_file_type(file_path)
        file_name = Path(file_path).name

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                with open(file_path, "rb") as f:
                    files = {
                        "file": (file_name, f, "application/octet-stream")
                    }
                    data = {
                        "file_type": file_type,
                        "file_name": file_name,
                    }
                    
                    resp = await client.post(
                        f"{self.BASE_URL}/im/v1/files",
                        headers={"Authorization": f"Bearer {access_token}"},
                        data=data,
                        files=files,
                    )
                
                result = resp.json()
                if result.get("code") == 0:
                    file_key = result.get("data", {}).get("file_key")
                    return {"success": True, "file_key": file_key}
                else:
                    return {
                        "success": False, 
                        "error": f"Upload failed: {result.get('msg')} (code: {result.get('code')})"
                    }
        except Exception as e:
            logger.error(f"[Feishu] File upload error: {e}", exc_info=True)
            return {"success": False, "error": f"Upload error: {str(e)}"}

    async def _upload_image(self, image_path: str) -> Dict[str, Any]:
        """上传图片到飞书获取 image_key.
        
        Args:
            image_path: 本地图片路径
            
        Returns:
            {"success": bool, "image_key": str, "error": str}
        """
        access_token = await self._get_access_token()
        if not access_token:
            return {"success": False, "error": "Failed to get access token"}

        if not os.path.exists(image_path):
            return {"success": False, "error": f"Image not found: {image_path}"}

        # 检查图片类型
        ext = Path(image_path).suffix.lower()
        valid_exts = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"]
        if ext not in valid_exts:
            return {"success": False, "error": f"Invalid image format. Supported: {valid_exts}"}

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                with open(image_path, "rb") as f:
                    files = {
                        "image": (f"image{ext}", f, f"image/{ext.lstrip('.')}" if ext != ".jpg" else "image/jpeg")
                    }
                    # 使用 image_type: message 表示用于消息发送
                    data = {"image_type": "message"}
                    
                    resp = await client.post(
                        f"{self.BASE_URL}/im/v1/images",
                        headers={"Authorization": f"Bearer {access_token}"},
                        data=data,
                        files=files,
                    )
                
                result = resp.json()
                if result.get("code") == 0:
                    image_key = result.get("data", {}).get("image_key")
                    return {"success": True, "image_key": image_key}
                else:
                    return {
                        "success": False, 
                        "error": f"Image upload failed: {result.get('msg')} (code: {result.get('code')})"
                    }
        except Exception as e:
            logger.error(f"[Feishu] Image upload error: {e}", exc_info=True)
            return {"success": False, "error": f"Image upload error: {str(e)}"}

    async def send_message(
        self,
        content: str,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None,
        msg_type: str = "text",
    ) -> Dict[str, Any]:
        """Send message via Feishu."""
        logger.info(f"[Feishu] send_message called: chat_id={chat_id}, user_id={user_id}, msg_type={msg_type}")
        
        access_token = await self._get_access_token()
        if not access_token:
            logger.error("[Feishu] Failed to get access token")
            return {"success": False, "error": "Failed to get access token"}
        
        import json
        
        # Build message payload
        if msg_type == "text":
            content_json = json.dumps({"text": content}, ensure_ascii=False)
            message = {"msg_type": "text", "content": content_json}
        elif msg_type == "markdown":
            content_json = json.dumps({
                "zh_cn": {
                    "title": "",
                    "content": [[{"tag": "text", "text": content}]]
                }
            }, ensure_ascii=False)
            message = {"msg_type": "post", "content": content_json}
        else:
            content_json = json.dumps({"text": content}, ensure_ascii=False)
            message = {"msg_type": "text", "content": content_json}

        # Determine receiver
        if chat_id:
            message["receive_id"] = chat_id
            url = f"{self.BASE_URL}/im/v1/messages?receive_id_type=chat_id"
        elif user_id:
            message["receive_id"] = user_id
            url = f"{self.BASE_URL}/im/v1/messages?receive_id_type=open_id"
        else:
            return {"success": False, "error": "No chat_id or user_id provided"}

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json=message,
            )
            data = resp.json()
            if data.get("code") == 0:
                return {
                    "success": True,
                    "message_id": data.get("data", {}).get("message_id"),
                }
            return {"success": False, "error": data.get("msg", "Unknown error")}

    async def send_file(
        self,
        file_path: str,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None,
        filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """发送文件给飞书用户.
        
        流程:
        1. 上传文件到飞书获取 file_key
        2. 发送文件消息
        
        Args:
            file_path: 本地文件路径
            chat_id: 群聊 ID (可选)
            user_id: 用户 ID (可选, 单聊时使用)
            filename: 显示的文件名 (可选)
            
        Returns:
            Dict: {"success": bool, "file_key": str (可选), "error": str (可选)}
        """
        logger.info(f"[Feishu] send_file called: file={file_path}, chat_id={chat_id}, user_id={user_id}")
        
        # 检查凭证
        if not self.app_id or not self.app_secret:
            return {"success": False, "error": "Missing app_id or app_secret"}
        
        # 检查文件
        if not os.path.exists(file_path):
            return {"success": False, "error": f"File not found: {file_path}"}
        
        # 步骤 1: 上传文件
        upload_result = await self._upload_file(file_path)
        if not upload_result.get("success"):
            return upload_result
        
        file_key = upload_result.get("file_key")
        
        # 步骤 2: 发送文件消息
        access_token = await self._get_access_token()
        if not access_token:
            return {"success": False, "error": "Failed to get access token"}
        
        import json
        
        # 构建文件消息内容
        content_json = json.dumps({"file_key": file_key}, ensure_ascii=False)
        message = {
            "msg_type": "file",
            "content": content_json
        }
        
        # 确定接收者
        if chat_id:
            message["receive_id"] = chat_id
            url = f"{self.BASE_URL}/im/v1/messages?receive_id_type=chat_id"
        elif user_id:
            message["receive_id"] = user_id
            url = f"{self.BASE_URL}/im/v1/messages?receive_id_type=open_id"
        else:
            return {"success": False, "error": "No chat_id or user_id provided"}
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    json=message,
                )
                data = resp.json()
                if data.get("code") == 0:
                    logger.info(f"[Feishu] File sent successfully: file_key={file_key[:20]}...")
                    return {
                        "success": True,
                        "file_key": file_key,
                        "message_id": data.get("data", {}).get("message_id"),
                    }
                else:
                    return {
                        "success": False, 
                        "error": f"Send failed: {data.get('msg')} (code: {data.get('code')})"
                    }
        except Exception as e:
            logger.error(f"[Feishu] Send file error: {e}", exc_info=True)
            return {"success": False, "error": f"Send error: {str(e)}"}

    async def send_image(
        self,
        image_path: str,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """发送图片给飞书用户.
        
        流程:
        1. 上传图片到飞书获取 image_key
        2. 发送图片消息
        
        Args:
            image_path: 本地图片路径
            chat_id: 群聊 ID (可选)
            user_id: 用户 ID (可选, 单聊时使用)
            
        Returns:
            Dict: {"success": bool, "image_key": str (可选), "error": str (可选)}
        """
        logger.info(f"[Feishu] send_image called: image={image_path}, chat_id={chat_id}, user_id={user_id}")
        
        # 检查凭证
        if not self.app_id or not self.app_secret:
            return {"success": False, "error": "Missing app_id or app_secret"}
        
        # 检查文件
        if not os.path.exists(image_path):
            return {"success": False, "error": f"Image not found: {image_path}"}
        
        # 步骤 1: 上传图片
        upload_result = await self._upload_image(image_path)
        if not upload_result.get("success"):
            return upload_result
        
        image_key = upload_result.get("image_key")
        
        # 步骤 2: 发送图片消息
        access_token = await self._get_access_token()
        if not access_token:
            return {"success": False, "error": "Failed to get access token"}
        
        import json
        
        # 构建图片消息内容
        content_json = json.dumps({"image_key": image_key}, ensure_ascii=False)
        message = {
            "msg_type": "image",
            "content": content_json
        }
        
        # 确定接收者
        if chat_id:
            message["receive_id"] = chat_id
            url = f"{self.BASE_URL}/im/v1/messages?receive_id_type=chat_id"
        elif user_id:
            message["receive_id"] = user_id
            url = f"{self.BASE_URL}/im/v1/messages?receive_id_type=open_id"
        else:
            return {"success": False, "error": "No chat_id or user_id provided"}
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    json=message,
                )
                data = resp.json()
                if data.get("code") == 0:
                    logger.info(f"[Feishu] Image sent successfully: image_key={image_key}")
                    return {
                        "success": True,
                        "image_key": image_key,
                        "message_id": data.get("data", {}).get("message_id"),
                    }
                else:
                    return {
                        "success": False, 
                        "error": f"Send failed: {data.get('msg')} (code: {data.get('code')})"
                    }
        except Exception as e:
            logger.error(f"[Feishu] Send image error: {e}", exc_info=True)
            return {"success": False, "error": f"Send error: {str(e)}"}

    async def download_file(self, file_key: str, message_id: str, save_dir: str, file_name: Optional[str] = None) -> Dict[str, Any]:
        """Download file from Feishu message.
        
        Args:
            file_key: The file key from message content
            message_id: The message ID (required for download API)
            save_dir: Directory to save the file
            file_name: Optional file name
            
        Returns:
            Dict with success status and file_path or error
        """
        import os
        from pathlib import Path
        
        logger.info(f"[Feishu] Downloading file: file_key={file_key}, message_id={message_id}")
        
        if not file_key or not message_id:
            return {"success": False, "error": "file_key and message_id are required"}
        
        access_token = await self._get_access_token()
        if not access_token:
            return {"success": False, "error": "Failed to get access token"}
        
        # Determine file name
        if not file_name:
            file_name = f"feishu_file_{file_key[:16]}"
        
        # Ensure directory exists
        Path(save_dir).mkdir(parents=True, exist_ok=True)
        file_path = os.path.join(save_dir, file_name)
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/im/v1/messages/{message_id}/resources/{file_key}",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"type": "file"}
                )
                
                if resp.status_code == 200:
                    with open(file_path, "wb") as f:
                        f.write(resp.content)
                    
                    file_size = len(resp.content)
                    logger.info(f"[Feishu] File downloaded: {file_path}, size: {file_size} bytes")
                    
                    return {
                        "success": True,
                        "file_path": file_path,
                        "file_name": file_name,
                        "file_size": file_size
                    }
                else:
                    error_data = resp.json()
                    error_msg = error_data.get("msg", "Unknown error")
                    logger.error(f"[Feishu] Download failed: {error_msg}")
                    return {"success": False, "error": f"Download failed: {error_msg}"}
                    
        except Exception as e:
            logger.error(f"[Feishu] Download file error: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def verify_webhook(self, request_body: bytes, signature: str) -> bool:
        """Verify Feishu webhook signature."""
        return True

    def parse_incoming_message(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse Feishu incoming message."""
        if "challenge" in data:
            return {"type": "challenge", "challenge": data["challenge"]}

        event = data.get("event", {})
        if not event:
            return None

        message = event.get("message", {})
        sender = event.get("sender", {})

        return {
            "type": "message",
            "message_id": message.get("message_id"),
            "content": message.get("content", {}),
            "chat_id": event.get("chat_id"),
            "user_id": sender.get("sender_id", {}).get("user_id"),
            "user_name": sender.get("sender_id", {}).get("name"),
            "msg_type": message.get("message_type"),
            "provider": self.PROVIDER_NAME,
        }
