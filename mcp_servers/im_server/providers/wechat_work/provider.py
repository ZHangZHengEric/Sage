"""WeChat Work (企业微信) provider implementation using long connection (WebSocket).

企业微信智能机器人 Provider 实现
使用 WebSocket 长连接模式实现双向消息通信
"""

import logging
from typing import Dict, Any, Optional

from ..base import IMProviderBase
from .websocket_client import WeChatWorkWebSocketClient

logger = logging.getLogger("WeChatWorkProvider")


class WeChatWorkProvider(IMProviderBase):
    """企业微信 Provider 实现
    
    基于 WebSocket 长连接模式, 支持:
    - 接收用户消息 (文本/图片/文件等)
    - 发送消息给用户 (Markdown/文本/流式)
    - 自动心跳保活和断线重连
    
    配置参数:
        - bot_id: 智能机器人 BotID
        - secret: 长连接专用密钥
        - enabled: 是否启用
    """

    PROVIDER_NAME = "wechat_work"

    def __init__(self, config: Dict[str, Any]):
        """初始化企业微信 Provider
        
        Args:
            config: 配置字典, 包含 bot_id, secret, enabled 等
        """
        super().__init__(config)
        
        # 从配置中提取参数
        self.bot_id = config.get("bot_id") or config.get("client_id")  # 兼容两种命名
        self.secret = config.get("secret") or config.get("client_secret")  # 兼容两种命名
        self.enabled = config.get("enabled", False)
        
        # WebSocket 客户端实例
        self._client: Optional[WeChatWorkWebSocketClient] = None
        
        # 保存最近使用的 req_id 到 chat_info 的映射
        # 用于 send_message 时查找上下文
        self._last_chat_info: Dict[str, Any] = {}

    async def send_message(
        self,
        content: str,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None,
        msg_type: str = "markdown",
        **kwargs
    ) -> Dict[str, Any]:
        """发送消息给企业微信用户
        
        企业微信长连接模式下，发送消息需要通过 WebSocket 连接。
        如果当前 Provider 没有活跃的 WebSocket 连接，会尝试创建临时连接发送。
        
        Args:
            content: 消息内容
            chat_id: 群聊 ID (可选)
            user_id: 用户 ID (可选, 单聊时使用)
            msg_type: 消息类型: markdown/text
            **kwargs: 额外参数
                
        Returns:
            Dict: {"success": bool, "error": str (可选)}
        """
        logger.info(f"[WeChatWork] send_message 被调用: chat_id={chat_id}, user_id={user_id}, msg_type={msg_type}")
        
        # 检查凭证
        if not self.bot_id or not self.secret:
            logger.error("[WeChatWork] 缺少必要的配置: bot_id 或 secret")
            return {"success": False, "error": "缺少必要的配置: bot_id 或 secret"}

        try:
            # 确定目标 chatid
            target_chat_id = chat_id or user_id
            if not target_chat_id:
                return {"success": False, "error": "未提供 chat_id 或 user_id"}
            
            # 确定 chat_type: 1=单聊, 2=群聊
            chat_type = 2 if chat_id else 1
            
            # 构建消息体
            import uuid
            body = {
                "chatid": target_chat_id,
                "chat_type": chat_type,
                "msgtype": msg_type
            }
            
            if msg_type == "markdown":
                body["markdown"] = {"content": content}
            elif msg_type == "text":
                body["text"] = {"content": content}
            else:
                return {"success": False, "error": f"不支持的消息类型: {msg_type}"}
            
            # 构建主动推送消息命令
            message = {
                "cmd": "aibot_send_msg",
                "headers": {
                    "req_id": str(uuid.uuid4())
                },
                "body": body
            }
            
            # 如果当前有 WebSocket 连接，直接使用
            if self._client and self._client.is_connected():
                logger.info("[WeChatWork] 使用现有 WebSocket 连接发送消息")
                result = await self._client.send_message(
                    content=content,
                    chat_id=chat_id,
                    user_id=user_id,
                    msg_type=msg_type
                )
                return result
            
            # 否则创建临时 WebSocket 连接发送
            logger.info("[WeChatWork] 创建临时 WebSocket 连接发送消息")
            return await self._send_via_temporary_ws(message)

        except Exception as e:
            logger.error(f"[WeChatWork] 发送消息异常: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def _send_via_temporary_ws(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """通过临时 WebSocket 连接发送消息
        
        用于当前没有活跃 WebSocket 连接时，创建临时连接发送消息
        """
        import asyncio
        import websockets
        import json
        import uuid
        
        ws_url = "wss://openws.work.weixin.qq.com"
        
        try:
            async with websockets.connect(ws_url, ping_interval=None) as ws:
                # 1. 发送订阅请求
                subscribe_msg = {
                    "cmd": "aibot_subscribe",
                    "headers": {"req_id": str(uuid.uuid4())},
                    "body": {
                        "bot_id": self.bot_id,
                        "secret": self.secret
                    }
                }
                await ws.send(json.dumps(subscribe_msg))
                
                # 等待订阅响应
                sub_response = await asyncio.wait_for(ws.recv(), timeout=10)
                sub_data = json.loads(sub_response)
                
                if sub_data.get("errcode") != 0:
                    return {"success": False, "error": f"订阅失败: {sub_data.get('errmsg')}"}
                
                logger.info("[WeChatWork] 临时连接订阅成功")
                
                # 2. 发送消息
                await ws.send(json.dumps(message))
                
                # 等待发送响应
                send_response = await asyncio.wait_for(ws.recv(), timeout=5)
                send_data = json.loads(send_response)
                
                if send_data.get("errcode") == 0:
                    logger.info("[WeChatWork] 消息通过临时连接发送成功")
                    return {"success": True}
                else:
                    return {"success": False, "error": send_data.get("errmsg", "未知错误")}
                    
        except asyncio.TimeoutError:
            logger.error("[WeChatWork] 临时连接发送超时")
            return {"success": False, "error": "连接超时"}
        except Exception as e:
            logger.error(f"[WeChatWork] 临时连接发送失败: {e}")
            return {"success": False, "error": str(e)}

    async def verify_webhook(self, request_body: bytes, signature: str) -> bool:
        """验证 Webhook 签名
        
        注意: 长连接模式下不使用 Webhook, 此方法仅用于接口兼容
        
        Args:
            request_body: 请求体
            signature: 签名
            
        Returns:
            bool: 始终返回 False (长连接模式不需要验证)
        """
        # 长连接模式下不使用 Webhook, 无需验证
        return False

    def parse_incoming_message(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """解析入站消息
        
        将企业微信的消息格式转换为标准格式
        
        Args:
            data: 原始消息数据
            
        Returns:
            Dict: 标准化的消息对象, 包含:
                - type: "message" 或 "event"
                - user_id: 用户 ID
                - chat_id: 群聊 ID (可选)
                - content: 消息内容
                - provider: "wechat_work"
                - req_id: 请求 ID (用于回复)
        """
        try:
            cmd = data.get("cmd")
            
            if cmd == "aibot_msg_callback":
                # 用户消息
                headers = data.get("headers", {})
                body = data.get("body", {})
                
                msg_type = body.get("msgtype")
                content = ""
                
                # 提取消息内容
                if msg_type == "text":
                    content = body.get("text", {}).get("content", "")
                elif msg_type == "mixed":
                    mixed_items = body.get("mixed", {}).get("items", [])
                    for item in mixed_items:
                        if item.get("type") == "text":
                            content += item.get("content", "")
                else:
                    content = f"[{msg_type}]"
                
                return {
                    "type": "message",
                    "message_id": body.get("msgid"),
                    "content": content,
                    "chat_id": body.get("chatid"),
                    "chat_type": body.get("chattype"),
                    "user_id": body.get("from", {}).get("userid"),
                    "user_name": body.get("from", {}).get("userid"),  # 企业微信不提供昵称
                    "msg_type": msg_type,
                    "provider": self.PROVIDER_NAME,
                    "req_id": headers.get("req_id"),
                    "raw_data": body
                }
                
            elif cmd == "aibot_event_callback":
                # 事件回调
                headers = data.get("headers", {})
                body = data.get("body", {})
                
                return {
                    "type": "event",
                    "event_type": body.get("event", {}).get("eventtype"),
                    "user_id": body.get("from", {}).get("userid"),
                    "chat_id": body.get("chatid"),
                    "chat_type": body.get("chattype"),
                    "provider": self.PROVIDER_NAME,
                    "req_id": headers.get("req_id"),
                    "raw_data": body
                }
            
            return None
            
        except Exception as e:
            logger.error(f"[WeChatWork] 解析消息异常: {e}")
            return None

    def start_client(self, message_handler: callable) -> bool:
        """启动 WebSocket 客户端
        
        Args:
            message_handler: 消息处理回调函数
            
        Returns:
            bool: 启动成功返回 True
        """
        try:
            if not self.bot_id or not self.secret:
                logger.error("[WeChatWork] 缺少必要的配置: bot_id 或 secret")
                return False
            
            # 注意: enabled 检查在 ServiceManager 层面已完成
            # 这里只检查必要的凭证
            
            # 创建 WebSocket 客户端
            self._client = WeChatWorkWebSocketClient(
                bot_id=self.bot_id,
                secret=self.secret,
                message_handler=message_handler
            )
            
            # 启动客户端
            self._client.start()
            
            logger.info(f"[WeChatWork] WebSocket 客户端已启动 (bot_id: {self.bot_id[:10]}...)")
            return True
            
        except Exception as e:
            logger.error(f"[WeChatWork] 启动客户端失败: {e}", exc_info=True)
            return False

    def stop_client(self):
        """停止 WebSocket 客户端"""
        if self._client:
            self._client.stop()
            self._client = None
            logger.info("[WeChatWork] WebSocket 客户端已停止")

    def is_connected(self) -> bool:
        """检查连接状态
        
        Returns:
            bool: 已连接返回 True
        """
        return self._client is not None and self._client.is_connected()

    def health_check(self) -> Dict[str, Any]:
        """健康检查
        
        Returns:
            Dict: 包含状态信息
        """
        connected = self.is_connected()
        
        return {
            "status": "connected" if connected else "disconnected",
            "enabled": self.enabled,
            "has_credentials": bool(self.bot_id and self.secret),
            "provider": self.PROVIDER_NAME
        }
