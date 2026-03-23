"""DingTalk IM provider."""

import hmac
import hashlib
import base64
import json
import time
import logging
import os
from typing import Optional, Dict, Any

import httpx

from ..base import IMProviderBase

logger = logging.getLogger("DingTalkProvider")


class DingTalkProvider(IMProviderBase):
    """DingTalk IM provider."""

    BASE_URL = "https://oapi.dingtalk.com"
    API_URL = "https://api.dingtalk.com"
    PROVIDER_NAME = "dingtalk"

    def _generate_sign(self, timestamp: str, secret: str) -> str:
        """Generate DingTalk signature."""
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return base64.b64encode(hmac_code).decode("utf-8")

    async def _get_access_token(self) -> Optional[str]:
        """Get DingTalk access token using app_key and app_secret."""
        app_key = self.config.get("app_key") or self.config.get("client_id")
        app_secret = self.config.get("app_secret") or self.config.get("client_secret")

        logger.info(f"[DingTalk] Getting access token: app_key={app_key}, has_secret={bool(app_secret)}")

        if not app_key or not app_secret:
            logger.error("[DingTalk] Missing app_key or app_secret in config")
            return None

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.BASE_URL}/gettoken",
                    params={"appkey": app_key, "appsecret": app_secret},
                )
                data = resp.json()
                logger.info(f"[DingTalk] gettoken response: {data}")
                if data.get("errcode") == 0:
                    return data.get("access_token")
                else:
                    logger.error(f"[DingTalk] gettoken failed: errcode={data.get('errcode')}, errmsg={data.get('errmsg')}")
        except Exception as e:
            logger.error(f"[DingTalk] gettoken exception: {e}", exc_info=True)
        return None

    async def send_message(
        self,
        content: str,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None,
        msg_type: str = "text",
        session_webhook: Optional[str] = None,
        sender_staff_id: Optional[str] = None,
        session_webhook_expired_time: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Send message via DingTalk.
        
        Args:
            content: Message content
            chat_id: Chat/Group ID (optional)
            user_id: User ID (optional)
            msg_type: Message type (text or markdown)
            session_webhook: Webhook URL from incoming message (preferred method)
            sender_staff_id: Sender's staff ID for @ mention
        """
        logger.info(f"[DingTalk] send_message called: chat_id={chat_id}, user_id={user_id}, content_length={len(content)}")
        
        # Use session_webhook if available (simplest method, no access token needed)
        if session_webhook:
            logger.info(f"[DingTalk] Using session_webhook: {session_webhook[:50]}...")
            # Use provided msg_type or default to text
            actual_msg_type = msg_type or "text"
            return await self._send_via_session_webhook(
                session_webhook, content, actual_msg_type, sender_staff_id,
                session_webhook_expired_time=session_webhook_expired_time
            )
        
        # Try configured webhook (legacy mode)
        webhook_url = self.config.get("webhook_url")
        if webhook_url:
            logger.info(f"[DingTalk] Using configured webhook: {webhook_url}")
            return await self._send_webhook(webhook_url, content, msg_type)

        # Otherwise use API (requires access token)
        logger.info("[DingTalk] Using API to send message")
        access_token = await self._get_access_token()
        if not access_token:
            logger.error("[DingTalk] Failed to get access token")
            return {"success": False, "error": "Failed to get access token. Check app_key and app_secret."}
        
        logger.info(f"[DingTalk] Got access token: {access_token[:10]}...")

        # Build message payload
        if msg_type == "text":
            msg = {"msgtype": "text", "text": {"content": content}}
        elif msg_type == "markdown":
            msg = {
                "msgtype": "markdown",
                "markdown": {"title": "Message", "text": content},
            }
        else:
            msg = {"msgtype": "text", "text": {"content": content}}

        # Send to specific user or chat
        if user_id:
            # Send to user via API
            url = f"{self.API_URL}/v1.0/robot/oToMessages/batchSend"
            payload = {
                "robotCode": self.config.get("app_key") or self.config.get("client_id"),
                "userIds": [user_id],
                "msgKey": "sampleText",
                "msgParam": json.dumps(msg["text"]) if msg_type == "text" else json.dumps(msg["markdown"])
            }
        elif chat_id:
            # Send to group chat
            url = f"{self.API_URL}/v1.0/robot/groupMessages/send"
            payload = {
                "robotCode": self.config.get("app_key") or self.config.get("client_id"),
                "openConversationId": chat_id,
                "msgKey": "sampleText",
                "msgParam": json.dumps(msg["text"]) if msg_type == "text" else json.dumps(msg["markdown"])
            }
        else:
            return {"success": False, "error": "No user_id or chat_id provided"}

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers={"x-acs-dingtalk-access-token": access_token},
                json=payload
            )
            data = resp.json()
            logger.info(f"[DingTalk] API response: {data}")
            # Check for success: either code is "0", success is True, or processQueryKey exists
            if data.get("code") == "0" or data.get("success") or data.get("processQueryKey"):
                return {"success": True, "message_id": data.get("processQueryKey")}
            error_msg = data.get("message") or data.get("errmsg") or data.get("error") or str(data)
            logger.error(f"[DingTalk] API error: {error_msg}")
            return {"success": False, "error": error_msg}

    async def _send_via_session_webhook(
        self, 
        session_webhook: str, 
        content: str, 
        msg_type: str,
        sender_staff_id: Optional[str] = None,
        session_webhook_expired_time: Optional[int] = None
    ) -> Dict[str, Any]:
        """Send message via session webhook (from incoming message).
        
        This is the simplest method - no access token needed.
        Note: session_webhook can be used multiple times until expired.
        """
        import time
        
        # Check if webhook is expired
        if session_webhook_expired_time:
            now_ms = int(time.time() * 1000)
            if now_ms >= session_webhook_expired_time:
                logger.warning(f"[DingTalk] session_webhook expired at {session_webhook_expired_time}, now={now_ms}")
                return {"success": False, "error": "Session webhook expired"}
            else:
                remaining_ms = session_webhook_expired_time - now_ms
                logger.info(f"[DingTalk] session_webhook valid, remaining={remaining_ms/1000:.0f}s")
        
        logger.info(f"[DingTalk] Sending via session_webhook, msg_type={msg_type}")
        logger.info(f"[DingTalk] Content preview: {content[:200] if content else 'EMPTY'}...")
        
        if msg_type == "text":
            payload = {
                "msgtype": "text", 
                "text": {"content": content},
            }
        elif msg_type == "markdown":
            payload = {
                "msgtype": "markdown",
                "markdown": {"title": "Message", "text": content},
            }
        elif msg_type == "rich_text":
            # Rich text message - content should be a list of elements
            # Format: [{"type": "text", "text": "..."}, {"type": "image", "path": "..."}]
            rich_text_elements = self._build_rich_text_content(content)
            payload = {
                "msgtype": "richText",
                "content": {
                    "richText": rich_text_elements
                }
            }
        else:
            payload = {
                "msgtype": "text", 
                "text": {"content": content},
            }
        
        # @ the sender if staff_id is available
        if sender_staff_id:
            payload["at"] = {"atUserIds": [sender_staff_id]}
        
        logger.info(f"[DingTalk] Payload: {payload}")
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    session_webhook, 
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )
                data = resp.json()
                logger.info(f"[DingTalk] session_webhook response: {data}")
                
                if data.get("errcode") == 0:
                    return {"success": True}
                return {"success": False, "error": data.get("errmsg", "Unknown error")}
        except Exception as e:
            logger.error(f"[DingTalk] session_webhook failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def _send_webhook(self, webhook_url: str, content: str, msg_type: str) -> Dict[str, Any]:
        """Send message via webhook (legacy mode)."""
        timestamp = str(round(time.time() * 1000))
        secret = self.config.get("app_secret", "")

        if msg_type == "text":
            payload = {"msgtype": "text", "text": {"content": content}}
        elif msg_type == "markdown":
            payload = {
                "msgtype": "markdown",
                "markdown": {"title": "Message", "text": content},
            }
        else:
            payload = {"msgtype": "text", "text": {"content": content}}

        # Add signature
        if secret:
            sign = self._generate_sign(timestamp, secret)
            payload["timestamp"] = timestamp
            payload["sign"] = sign

        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=payload)
            data = resp.json()
            if data.get("errcode") == 0:
                return {"success": True}
            return {"success": False, "error": data.get("errmsg", "Unknown error")}

    async def verify_webhook(self, request_body: bytes, signature: str) -> bool:
        """Verify DingTalk webhook signature."""
        app_secret = self.config.get("app_secret", "")
        if not app_secret:
            return True

        expected_sign = hmac.new(
            app_secret.encode("utf-8"),
            request_body,
            digestmod=hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected_sign, signature)

    def parse_incoming_message(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse DingTalk incoming message."""
        # Handle different message types
        msg_type = data.get("msgtype")
        if not msg_type:
            return None

        content = ""
        if msg_type == "text":
            content = data.get("text", {}).get("content", "")
        elif msg_type == "markdown":
            content = data.get("markdown", {}).get("text", "")

        return {
            "type": "message",
            "content": content,
            "chat_id": data.get("conversationId"),
            "user_id": data.get("senderStaffId"),
            "user_name": data.get("senderNick"),
            "msg_type": msg_type,
            "provider": self.PROVIDER_NAME,
        }

    async def download_file(self, download_code: str, save_dir: str, file_name: Optional[str] = None) -> Dict[str, Any]:
        """Download file from DingTalk using download code.
        
        Args:
            download_code: The download code from file/image message
            save_dir: Directory to save the file
            file_name: Optional file name, if not provided will be extracted from response
            
        Returns:
            Dict with success status and file_path or error
        """
        import os
        from pathlib import Path
        
        logger.info(f"[DingTalk] Downloading file with download_code: {download_code}, file_name: {file_name}")
        
        if not download_code:
            logger.error("[DingTalk] download_code is required but not provided")
            return {"success": False, "error": "download_code is required"}
        
        access_token = await self._get_access_token()
        if not access_token:
            logger.error("[DingTalk] Failed to get access token")
            return {"success": False, "error": "Failed to get access token"}
        
        # Get download URL
        robot_code = self.config.get("app_key") or self.config.get("client_id")
        if not robot_code:
            logger.error("[DingTalk] robot_code (app_key/client_id) not configured")
            return {"success": False, "error": "robot_code not configured"}
        
        url = f"{self.API_URL}/v1.0/robot/messageFiles/download"
        logger.info(f"[DingTalk] Requesting download URL from: {url}, robot_code: {robot_code}")
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Step 1: Get download URL
                resp = await client.post(
                    url,
                    headers={"x-acs-dingtalk-access-token": access_token},
                    json={
                        "robotCode": robot_code,
                        "downloadCode": download_code
                    }
                )
                data = resp.json()
                logger.info(f"[DingTalk] Get download URL response: {data}")
                
                # Check for error -钉钉API返回成功时没有code/errcode字段，直接返回downloadUrl
                code = data.get("code")
                errcode = data.get("errcode")
                if (code is not None and code != "0") or (errcode is not None and errcode != 0):
                    error_msg = data.get("message") or data.get("errmsg") or str(data)
                    logger.error(f"[DingTalk] Failed to get download URL: {error_msg}")
                    return {"success": False, "error": f"Failed to get download URL: {error_msg}"}
                
                download_url = data.get("downloadUrl")
                if not download_url:
                    logger.error(f"[DingTalk] No downloadUrl in response: {data}")
                    return {"success": False, "error": "No download URL in response"}
                
                logger.info(f"[DingTalk] Got download URL: {download_url[:50]}...")
                
                # Step 2: Download file content
                file_resp = await client.get(download_url, timeout=60.0)
                file_resp.raise_for_status()
                
                # Determine file name
                if not file_name:
                    # Try to get from Content-Disposition header
                    content_disp = file_resp.headers.get("Content-Disposition", "")
                    if "filename=" in content_disp:
                        file_name = content_disp.split("filename=")[-1].strip('"')
                    else:
                        # Generate from download code
                        file_name = f"dingtalk_file_{download_code[:8]}"
                
                # Ensure directory exists
                Path(save_dir).mkdir(parents=True, exist_ok=True)
                file_path = os.path.join(save_dir, file_name)
                
                # Save file
                with open(file_path, "wb") as f:
                    f.write(file_resp.content)
                
                file_size = len(file_resp.content)
                logger.info(f"[DingTalk] File saved to {file_path}, size: {file_size} bytes")
                
                return {
                    "success": True,
                    "file_path": file_path,
                    "file_name": file_name,
                    "file_size": file_size
                }
                
        except Exception as e:
            logger.error(f"[DingTalk] Download file failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def _build_rich_text_content(self, content: Any) -> list:
        """Build rich text content from various input formats.
        
        Args:
            content: Can be:
                - str: Plain text
                - list: List of elements [{"type": "text", "text": "..."}, {"type": "image", "path": "..."}]
                - dict: {"text": "...", "images": ["path1", "path2"]}
        
        Returns:
            List of rich text elements for DingTalk API
        """
        elements = []
        
        if isinstance(content, str):
            # Simple text
            if content.strip():
                elements.append({"text": content})
        elif isinstance(content, list):
            # List of elements
            for item in content:
                if isinstance(item, dict):
                    item_type = item.get("type", "text")
                    if item_type == "text":
                        text = item.get("text", "")
                        if text:
                            elements.append({"text": text})
                    elif item_type == "image":
                        # Image element - will be processed later
                        # For now, add placeholder text
                        elements.append({"text": "[图片]"})
        elif isinstance(content, dict):
            # Dict format
            text = content.get("text", "")
            if text:
                elements.append({"text": text})
            images = content.get("images", [])
            for img in images:
                elements.append({"text": "[图片]"})
        
        if not elements:
            elements.append({"text": "[富文本消息]"})
        
        return elements

    async def upload_media(self, file_path: str, file_type: str = "image") -> Dict[str, Any]:
        """Upload media file to DingTalk and get media_id.
        
        Args:
            file_path: Path to the media file
            file_type: Type of media - image, voice, video, file
            
        Returns:
            Dict with success status and media_id or error
        """
        import mimetypes
        
        logger.info(f"[DingTalk] Uploading media: {file_path}, type={file_type}")
        
        if not os.path.exists(file_path):
            return {"success": False, "error": f"File not found: {file_path}"}
        
        access_token = await self._get_access_token()
        if not access_token:
            return {"success": False, "error": "Failed to get access token"}
        
        # Map file_type to DingTalk media type
        media_type_map = {
            "image": "image",
            "photo": "image",
            "voice": "voice",
            "audio": "voice",
            "video": "video",
            "file": "file",
        }
        media_type = media_type_map.get(file_type, "file")
        
        url = f"{self.BASE_URL}/media/upload"
        
        try:
            # Guess mime type
            mime_type, _ = mimetypes.guess_type(file_path)
            if not mime_type:
                mime_type = "application/octet-stream"
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                with open(file_path, "rb") as f:
                    files = {"media": (os.path.basename(file_path), f, mime_type)}
                    resp = await client.post(
                        url,
                        params={"access_token": access_token, "type": media_type},
                        files=files
                    )
                
                data = resp.json()
                logger.info(f"[DingTalk] Media upload response: {data}")
                
                if data.get("errcode") == 0:
                    return {
                        "success": True,
                        "media_id": data.get("media_id"),
                        "type": media_type,
                        "created_at": data.get("created_at")
                    }
                else:
                    error_msg = data.get("errmsg", "Unknown error")
                    logger.error(f"[DingTalk] Media upload failed: {error_msg}")
                    return {"success": False, "error": error_msg}
                    
        except Exception as e:
            logger.error(f"[DingTalk] Media upload failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def send_file(
        self,
        file_path: str,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send file to DingTalk user or group.
        
        Note: DingTalk enterprise robot (Stream mode) does NOT support sending file messages.
        This method sends the file content as a text message instead.
        
        Args:
            file_path: Path to the file to send
            chat_id: Chat/Group ID (optional)
            user_id: User ID (optional)
            
        Returns:
            Dict with success status and message_id or error
        """
        import os
        
        logger.info(f"[DingTalk] send_file called: file={file_path}, chat_id={chat_id}, user_id={user_id}")
        
        if not os.path.exists(file_path):
            return {"success": False, "error": f"File not found: {file_path}"}
        
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        
        # Try to read text file content
        content_preview = ""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                # Limit to 2000 chars for DingTalk message
                if len(content) > 2000:
                    content_preview = content[:2000] + "\n\n[文件已截断，完整内容请在工作区查看]"
                else:
                    content_preview = content
        except Exception:
            content_preview = "[二进制文件，无法预览文本内容]"
        
        # Build message - include file info and content
        text_content = f"📄 {file_name}\n大小: {file_size} 字节\n\n{content_preview}"
        
        return await self.send_message(
            content=text_content,
            chat_id=chat_id,
            user_id=user_id,
            msg_type="text"
        )

    async def send_image(
        self,
        image_path: str,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send image to DingTalk user or group.
        
        Args:
            image_path: Path to the image to send
            chat_id: Chat/Group ID (optional)
            user_id: User ID (optional)
            
        Returns:
            Dict with success status and message_id or error
        """
        logger.info(f"[DingTalk] send_image called: image={image_path}, chat_id={chat_id}, user_id={user_id}")
        
        # Step 1: Upload image to get media_id
        upload_result = await self.upload_media(image_path, file_type="image")
        if not upload_result.get("success"):
            return upload_result
        
        media_id = upload_result.get("media_id")
        logger.info(f"[DingTalk] Image uploaded, media_id: {media_id}")
        
        # Step 2: Send image message using media_id
        access_token = await self._get_access_token()
        if not access_token:
            return {"success": False, "error": "Failed to get access token"}
        
        robot_code = self.config.get("app_key") or self.config.get("client_id")
        
        # Build message payload for image
        # 钉钉图片消息格式: msgKey=sampleImageMsg, msgParam={"photoURL": "xxx"}
        msg_param = {"photoURL": media_id}
        
        if user_id:
            # Send to user via API
            url = f"{self.API_URL}/v1.0/robot/oToMessages/batchSend"
            payload = {
                "robotCode": robot_code,
                "userIds": [user_id],
                "msgKey": "sampleImageMsg",
                "msgParam": json.dumps(msg_param)
            }
        elif chat_id:
            # Send to group chat
            url = f"{self.API_URL}/v1.0/robot/groupMessages/send"
            payload = {
                "robotCode": robot_code,
                "openConversationId": chat_id,
                "msgKey": "sampleImageMsg",
                "msgParam": json.dumps(msg_param)
            }
        else:
            return {"success": False, "error": "No user_id or chat_id provided"}
        
        logger.info(f"[DingTalk] Sending image message: url={url}, payload={payload}")
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    headers={"x-acs-dingtalk-access-token": access_token},
                    json=payload
                )
                data = resp.json()
                logger.info(f"[DingTalk] Send image API response: {data}")
                
                code = data.get("code")
                errcode = data.get("errcode")
                if (code is not None and code != "0") or (errcode is not None and errcode != 0):
                    error_msg = data.get("message") or data.get("errmsg") or str(data)
                    logger.error(f"[DingTalk] Send image failed: {error_msg}")
                    return {"success": False, "error": f"Send image failed: {error_msg}"}
                
                return {"success": True, "message_id": data.get("processQueryKey")}
                
        except Exception as e:
            logger.error(f"[DingTalk] Send image failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
