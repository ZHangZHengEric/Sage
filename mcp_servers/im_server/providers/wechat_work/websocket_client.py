"""WeChat Work WebSocket client for long connection mode.

企业微信智能机器人长连接 WebSocket 客户端
基于官方文档实现: https://developer.work.weixin.qq.com/document/path/101463

特性:
- 长连接模式 (无需公网 IP)
- 双向通信 (接收和发送消息)
- 自动心跳保活 (30秒间隔)
- 自动重连机制 (指数退避)
- 无需消息加解密 (比 Webhook 模式更简单)
"""

import asyncio
import json
import logging
import threading
import time
import uuid
from typing import Callable, Dict, Any, Optional

import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatusCode

logger = logging.getLogger("WeChatWorkWebSocket")


class WeChatWorkWebSocketClient:
    """企业微信 WebSocket 长连接客户端
    
    用于实现企业微信智能机器人的实时消息接收和发送
    """

    # WebSocket 连接地址 (企业微信官方提供)
    WS_URL = "wss://openws.work.weixin.qq.com"
    
    # 心跳配置 (官方推荐 30 秒)
    HEARTBEAT_INTERVAL = 30  # 心跳间隔 (秒)
    HEARTBEAT_TIMEOUT = 60   # 心跳超时时间 (秒)
    
    # 重连配置
    RECONNECT_BASE_DELAY = 5   # 基础重连延迟 (秒)
    RECONNECT_MAX_DELAY = 60   # 最大重连延迟 (秒)
    RECONNECT_MAX_RETRIES = 10 # 最大重连次数

    def __init__(
        self,
        bot_id: str,
        secret: str,
        message_handler: Callable[[Dict[str, Any]], None],
        heartbeat_interval: int = HEARTBEAT_INTERVAL
    ):
        """初始化企业微信 WebSocket 客户端

        Args:
            bot_id: 智能机器人 BotID (从企业微信管理后台获取)
            secret: 长连接专用密钥 (注意: 不是 Token/EncodingAESKey)
            message_handler: 消息处理回调函数
            heartbeat_interval: 心跳间隔 (秒), 默认 30 秒
        """
        self.bot_id = bot_id
        self.secret = secret
        self.message_handler = message_handler
        self.heartbeat_interval = heartbeat_interval

        # WebSocket 连接对象
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        
        # 运行状态
        self.running = False
        self._ws_thread: Optional[threading.Thread] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        
        # 状态追踪
        self._last_message_time: float = 0
        self._reconnect_count = 0
        self._lock = threading.Lock()

        # 保存 req_id 到 chat_info 的映射 (用于后续回复)
        self._req_chat_map: Dict[str, Dict[str, Any]] = {}

    def start(self):
        """启动 WebSocket 客户端 (在后台线程中运行)"""
        if self.running:
            logger.warning("[WeChatWork] 客户端已在运行中")
            return

        self.running = True
        self._reconnect_count = 0
        self._start_ws_thread()
        logger.info("[WeChatWork] WebSocket 客户端已启动")

    def _start_ws_thread(self):
        """启动 WebSocket 连接线程"""
        with self._lock:
            if self._ws_thread and self._ws_thread.is_alive():
                return
            
            self._ws_thread = threading.Thread(target=self._run_client, daemon=True)
            self._ws_thread.start()
            logger.info("[WeChatWork] WebSocket 线程已启动")

    def stop(self):
        """停止 WebSocket 客户端"""
        logger.info("[WeChatWork] 正在停止客户端...")
        self.running = False

        # 取消心跳任务
        if self._heartbeat_task:
            self._heartbeat_task.cancel()

        # 关闭 WebSocket 连接
        if self.websocket:
            try:
                asyncio.get_event_loop().create_task(self.websocket.close())
            except Exception:
                pass

        # 等待线程结束
        if self._ws_thread:
            self._ws_thread.join(timeout=5)

        logger.info("[WeChatWork] 客户端已停止")

    def _run_client(self):
        """运行 WebSocket 客户端主循环 (带自动重连)"""
        while self.running:
            try:
                # 创建新的事件循环
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # 运行连接
                loop.run_until_complete(self._connect_and_run())
                
                # 如果正常关闭且不需要重连
                if not self.running:
                    logger.info("[WeChatWork] 连接正常关闭")
                    break
                    
            except Exception as e:
                logger.error(f"[WeChatWork] 连接错误: {e}")
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

            # 尝试重连
            if self.running:
                self._reconnect_count += 1
                if self._reconnect_count > self.RECONNECT_MAX_RETRIES:
                    logger.error(f"[WeChatWork] 达到最大重连次数 ({self.RECONNECT_MAX_RETRIES}), 放弃重连")
                    self.running = False
                    break

                # 指数退避计算延迟
                delay = min(
                    self.RECONNECT_BASE_DELAY * (2 ** (self._reconnect_count - 1)),
                    self.RECONNECT_MAX_DELAY
                )
                logger.info(f"[WeChatWork] 将在 {delay} 秒后重连 (第 {self._reconnect_count}/{self.RECONNECT_MAX_RETRIES} 次)...")
                time.sleep(delay)

    async def _connect_and_run(self):
        """建立连接并运行消息循环"""
        try:
            logger.info(f"[WeChatWork] 正在连接到 {self.WS_URL}...")
            
            # 建立 WebSocket 连接
            async with websockets.connect(
                self.WS_URL,
                ping_interval=None,  # 禁用心跳 (我们手动处理)
                close_timeout=5
            ) as websocket:
                self.websocket = websocket
                logger.info("[WeChatWork] WebSocket 已连接")

                # 发送订阅请求进行身份认证
                if not await self._subscribe():
                    logger.error("[WeChatWork] 订阅认证失败")
                    return

                logger.info("[WeChatWork] 订阅认证成功, 连接已就绪")
                self._reconnect_count = 0  # 重置重连计数器
                self._last_message_time = time.time()

                # 启动心跳任务
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                # 消息接收循环
                async for message in websocket:
                    self._last_message_time = time.time()
                    await self._handle_message(message)

        except ConnectionClosed as e:
            logger.warning(f"[WeChatWork] 连接已关闭: {e}")
        except InvalidStatusCode as e:
            logger.error(f"[WeChatWork] 无效的状态码: {e}")
        except Exception as e:
            logger.error(f"[WeChatWork] 连接异常: {e}", exc_info=True)
        finally:
            self.websocket = None
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass

    async def _subscribe(self) -> bool:
        """发送订阅请求进行身份认证

        Returns:
            bool: 认证成功返回 True, 否则返回 False
        """
        req_id = str(uuid.uuid4())
        subscribe_msg = {
            "cmd": "aibot_subscribe",
            "headers": {
                "req_id": req_id
            },
            "body": {
                "bot_id": self.bot_id,
                "secret": self.secret
            }
        }

        try:
            logger.info(f"[WeChatWork] 正在发送订阅请求...")
            await self.websocket.send(json.dumps(subscribe_msg))

            # 等待响应 (10秒超时)
            response = await asyncio.wait_for(
                self.websocket.recv(),
                timeout=10
            )
            
            data = json.loads(response)
            logger.debug(f"[WeChatWork] 订阅响应: {data}")

            if data.get("errcode") == 0:
                logger.info("[WeChatWork] 订阅认证成功")
                return True
            else:
                logger.error(f"[WeChatWork] 订阅失败: {data.get('errmsg')}")
                return False

        except asyncio.TimeoutError:
            logger.error("[WeChatWork] 订阅请求超时")
            return False
        except Exception as e:
            logger.error(f"[WeChatWork] 订阅异常: {e}")
            return False

    async def _heartbeat_loop(self):
        """心跳保活循环 (每 30 秒发送一次 ping)"""
        logger.info(f"[WeChatWork] 心跳任务已启动 (间隔: {self.heartbeat_interval}秒)")
        
        while self.running and self.websocket:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                
                if not self.running or not self.websocket:
                    break

                # 检查连接是否健康 (超过 2 倍心跳间隔无消息则警告)
                elapsed = time.time() - self._last_message_time
                if elapsed > self.heartbeat_interval * 2:
                    logger.warning(f"[WeChatWork] 连接可能不健康 (已 {elapsed:.0f} 秒无消息)")

                # 发送 ping
                ping_msg = {
                    "cmd": "ping",
                    "headers": {
                        "req_id": str(uuid.uuid4())
                    }
                }
                
                await self.websocket.send(json.dumps(ping_msg))
                logger.debug("[WeChatWork] 心跳 ping 已发送")

            except asyncio.CancelledError:
                logger.info("[WeChatWork] 心跳任务已取消")
                break
            except Exception as e:
                logger.error(f"[WeChatWork] 心跳异常: {e}")
                break

    async def _handle_message(self, message: str):
        """处理收到的 WebSocket 消息

        Args:
            message: WebSocket 消息内容 (JSON 字符串)
        """
        try:
            data = json.loads(message)
            cmd = data.get("cmd")
            
            logger.debug(f"[WeChatWork] 收到消息: {cmd}")

            if cmd == "aibot_msg_callback":
                # 用户消息回调
                await self._handle_user_message(data)
            elif cmd == "aibot_event_callback":
                # 事件回调 (进入会话、断开连接等)
                await self._handle_event(data)
            elif cmd == "pong":
                # 心跳响应
                logger.debug("[WeChatWork] 收到心跳 pong")
            else:
                logger.debug(f"[WeChatWork] 未知命令: {cmd}, 数据: {data}")

        except json.JSONDecodeError:
            logger.error(f"[WeChatWork] 无效的 JSON: {message[:200]}")
        except Exception as e:
            logger.error(f"[WeChatWork] 处理消息异常: {e}", exc_info=True)

    async def _handle_user_message(self, data: Dict[str, Any]):
        """处理用户消息回调

        Args:
            data: 消息数据, 包含 headers, body 等
        """
        try:
            headers = data.get("headers", {})
            body = data.get("body", {})
            
            req_id = headers.get("req_id")
            msg_id = body.get("msgid")
            chat_id = body.get("chatid")        # 群聊 ID
            chat_type = body.get("chattype")    # 'single' 或 'group'
            user_id = body.get("from", {}).get("userid")
            msg_type = body.get("msgtype")
            
            # 保存 req_id 到 chat_info 的映射 (用于后续回复)
            if req_id:
                self._req_chat_map[req_id] = {
                    "chat_id": chat_id,
                    "chat_type": chat_type,
                    "user_id": user_id
                }

            # 根据消息类型提取内容
            content = ""
            if msg_type == "text":
                # 文本消息
                content = body.get("text", {}).get("content", "")
            elif msg_type == "mixed":
                # 图文混排消息
                mixed_items = body.get("mixed", {}).get("items", [])
                for item in mixed_items:
                    if item.get("type") == "text":
                        content += item.get("content", "")
            elif msg_type in ["image", "voice", "file"]:
                # 媒体消息 (仅单聊支持)
                content = f"[{msg_type.upper()} 消息]"
            else:
                content = str(body)

            # 构建标准化的消息对象
            parsed_message = {
                "type": "message",
                "message_id": msg_id,
                "content": content,
                "chat_id": chat_id,
                "chat_type": chat_type,
                "user_id": user_id,
                "user_name": user_id,  # 企业微信回调中不包含用户姓名
                "msg_type": msg_type,
                "provider": "wechat_work",
                "req_id": req_id,  # 重要: 用于回复关联
                "raw_data": body
            }

            logger.info(f"[WeChatWork] 收到消息 来自 {user_id} ({chat_type}): {content[:50]}...")

            # 调用消息处理器
            self._call_message_handler(parsed_message)

        except Exception as e:
            logger.error(f"[WeChatWork] 解析用户消息异常: {e}", exc_info=True)

    async def _handle_event(self, data: Dict[str, Any]):
        """处理事件回调

        Args:
            data: 事件数据
        """
        try:
            headers = data.get("headers", {})
            body = data.get("body", {})
            
            req_id = headers.get("req_id")
            event_type = body.get("event", {}).get("eventtype")
            
            logger.info(f"[WeChatWork] 收到事件: {event_type}")

            if event_type == "disconnected_event":
                # 连接被断开事件 (有新连接建立时触发)
                logger.warning("[WeChatWork] 收到断开事件 (其他地方建立了新连接)")
                self.running = False  # 停止当前连接
                return
            elif event_type == "enter_chat":
                # 用户进入会话事件
                logger.info(f"[WeChatWork] 用户 {body.get('from', {}).get('userid')} 进入会话")

            # 构建标准化的事件对象
            parsed_event = {
                "type": "event",
                "event_type": event_type,
                "user_id": body.get("from", {}).get("userid"),
                "chat_id": body.get("chatid"),
                "chat_type": body.get("chattype"),
                "provider": "wechat_work",
                "req_id": req_id,
                "raw_data": body
            }

            self._call_message_handler(parsed_event)

        except Exception as e:
            logger.error(f"[WeChatWork] 解析事件异常: {e}", exc_info=True)

    def _call_message_handler(self, message: Dict[str, Any]):
        """调用消息处理回调 (支持同步和异步)
        
        Args:
            message: 标准化后的消息/事件对象
        """
        try:
            result = self.message_handler(message)
            # 如果处理函数返回协程, 需要异步执行
            if asyncio.iscoroutine(result):
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(result)
                    else:
                        loop.run_until_complete(result)
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(result)
                    loop.close()
        except Exception as e:
            logger.error(f"[WeChatWork] 消息处理回调异常: {e}", exc_info=True)

    async def send_message(
        self,
        content: str,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None,
        msg_type: str = "markdown",
        req_id: Optional[str] = None,
        stream_id: Optional[str] = None,
        finish: bool = True
    ) -> Dict[str, Any]:
        """通过 WebSocket 发送消息

        支持回复消息和主动推送两种方式

        Args:
            content: 消息内容
            chat_id: 群聊 ID (从收到的消息中获取)
            user_id: 用户 ID (单聊时使用)
            msg_type: 消息类型: markdown/text/stream
            req_id: 原始消息的 req_id (回复时必须携带以关联上下文)
            stream_id: 流式消息 ID (用于流式回复)
            finish: 是否为流式消息的最后一块

        Returns:
            Dict: 包含 success (bool) 和可选的 error (str)
        """
        if not self.websocket:
            return {"success": False, "error": "WebSocket 未连接"}

        try:
            # 确定目标会话
            target_chat_id = chat_id or user_id
            if not target_chat_id:
                return {"success": False, "error": "未提供 chat_id 或 user_id"}

            # 确定会话类型: 1=单聊, 2=群聊
            chat_type = 2 if chat_id else 1

            # 构建消息体
            body: Dict[str, Any] = {
                "chatid": target_chat_id,
                "chat_type": chat_type,
                "msgtype": msg_type
            }

            # 根据消息类型填充内容
            if msg_type == "markdown":
                body["markdown"] = {"content": content}
            elif msg_type == "text":
                body["text"] = {"content": content}
            elif msg_type == "stream":
                body["stream"] = {
                    "id": stream_id or str(uuid.uuid4()),
                    "content": content,
                    "finish": finish
                }
            else:
                return {"success": False, "error": f"不支持的消息类型: {msg_type}"}

            # 确定命令类型
            # - aibot_respond_msg: 回复消息 (需要 req_id)
            # - aibot_send_msg: 主动推送 (不需要 req_id)
            if req_id:
                cmd = "aibot_respond_msg"
            else:
                cmd = "aibot_send_msg"

            message = {
                "cmd": cmd,
                "headers": {
                    "req_id": req_id or str(uuid.uuid4())
                },
                "body": body
            }

            await self.websocket.send(json.dumps(message))
            
            # 等待响应 (5秒超时)
            try:
                response = await asyncio.wait_for(self.websocket.recv(), timeout=5)
                resp_data = json.loads(response)
                
                if resp_data.get("errcode") == 0:
                    logger.info(f"[WeChatWork] 消息发送成功")
                    return {"success": True}
                else:
                    error_msg = resp_data.get("errmsg", "未知错误")
                    logger.error(f"[WeChatWork] 发送失败: {error_msg}")
                    return {"success": False, "error": error_msg}
                    
            except asyncio.TimeoutError:
                # 超时但消息可能已发送
                logger.warning("[WeChatWork] 发送响应超时, 消息可能已发送")
                return {"success": True, "warning": "响应超时"}

        except Exception as e:
            logger.error(f"[WeChatWork] 发送消息异常: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def is_connected(self) -> bool:
        """检查 WebSocket 是否已连接
        
        Returns:
            bool: 已连接返回 True
        """
        return self.websocket is not None and self.websocket.open

    def get_chat_info_by_req_id(self, req_id: str) -> Optional[Dict[str, Any]]:
        """通过 req_id 获取聊天信息 (用于回复消息时查找上下文)
        
        Args:
            req_id: 请求 ID
            
        Returns:
            Dict: 包含 chat_id, chat_type, user_id 或 None
        """
        return self._req_chat_map.get(req_id)
