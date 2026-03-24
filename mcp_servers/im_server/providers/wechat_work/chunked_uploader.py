"""WeChat Work chunked file uploader.

企业微信分片上传模块
支持大文件分片上传到企业微信临时素材库

上传流程:
1. 初始化上传 (init_upload) -> 获取 upload_id
2. 分片上传 (upload_chunk) -> 每片 ≤ 512KB, Base64编码
3. 完成上传 (finish_upload) -> 获取 media_id (3天有效)

限制:
- 单个分片 ≤ 512KB (Base64编码前)
- 最多 100 个分片
- 上传会话 30 分钟有效期
"""

import os
import json
import base64
import logging
import asyncio
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass
from pathlib import Path

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger("WeChatWorkUploader")


@dataclass
class UploadResult:
    """上传结果"""
    success: bool
    media_id: Optional[str] = None
    error: Optional[str] = None
    upload_id: Optional[str] = None


class ChunkedUploader:
    """企业微信分片上传器
    
    使用 WebSocket 连接进行分片上传
    """
    
    # 分片配置
    CHUNK_SIZE = 512 * 1024  # 512KB per chunk (Base64编码前)
    MAX_CHUNKS = 100
    UPLOAD_TIMEOUT = 30  # 单个分片超时时间
    
    def __init__(self, bot_id: str, secret: str):
        self.bot_id = bot_id
        self.secret = secret
        self.ws_url = "wss://openws.work.weixin.qq.com"
    
    async def upload_file(
        self, 
        file_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> UploadResult:
        """上传文件到企业微信临时素材库
        
        Args:
            file_path: 本地文件路径
            progress_callback: 进度回调函数 (current_chunk, total_chunks)
            
        Returns:
            UploadResult: 上传结果，包含 media_id
        """
        try:
            # 检查文件
            if not os.path.exists(file_path):
                return UploadResult(success=False, error=f"File not found: {file_path}")
            
            file_size = os.path.getsize(file_path)
            file_name = os.path.basename(file_path)
            
            logger.info(f"[ChunkedUploader] Starting upload: {file_name} ({file_size} bytes)")
            
            # 建立 WebSocket 连接
            async with websockets.connect(
                self.ws_url,
                ping_interval=None,
                close_timeout=5
            ) as websocket:
                
                # 1. 先订阅 WebSocket（必需步骤）
                subscribed = await self._subscribe(websocket)
                if not subscribed:
                    return UploadResult(success=False, error="WebSocket subscription failed")
                
                logger.info("[ChunkedUploader] WebSocket subscribed")
                
                # 2. 初始化上传
                upload_id = await self._init_upload(websocket, file_path, file_name)
                if not upload_id:
                    return UploadResult(success=False, error="Failed to initialize upload")
                
                logger.info(f"[ChunkedUploader] Upload initialized: {upload_id}")
                
                # 2. 分片上传
                total_chunks = self._calculate_chunks(file_size)
                logger.info(f"[ChunkedUploader] Total chunks: {total_chunks}")
                
                success = await self._upload_chunks(
                    websocket, 
                    upload_id, 
                    file_path, 
                    total_chunks,
                    progress_callback
                )
                
                if not success:
                    return UploadResult(
                        success=False, 
                        error="Failed to upload chunks",
                        upload_id=upload_id
                    )
                
                # 3. 完成上传
                media_id = await self._finish_upload(websocket, upload_id, file_name)
                
                if media_id:
                    logger.info(f"[ChunkedUploader] Upload successful: media_id={media_id[:20]}...")
                    return UploadResult(
                        success=True, 
                        media_id=media_id,
                        upload_id=upload_id
                    )
                else:
                    return UploadResult(
                        success=False, 
                        error="Failed to finish upload",
                        upload_id=upload_id
                    )
                    
        except Exception as e:
            logger.error(f"[ChunkedUploader] Upload failed: {e}", exc_info=True)
            return UploadResult(success=False, error=str(e))
    
    def _calculate_chunks(self, file_size: int) -> int:
        """计算需要的分片数量"""
        chunks = (file_size + self.CHUNK_SIZE - 1) // self.CHUNK_SIZE
        return min(chunks, self.MAX_CHUNKS)
    
    async def _subscribe(self, websocket) -> bool:
        """
        发送订阅请求进行身份认证（必需步骤）
        
        Args:
            websocket: WebSocket 连接
            
        Returns:
            bool: 认证成功返回 True, 否则返回 False
        """
        try:
            subscribe_msg = {
                "cmd": "aibot_subscribe",
                "headers": {
                    "req_id": self._generate_req_id()
                },
                "body": {
                    "bot_id": self.bot_id,
                    "secret": self.secret
                }
            }
            
            logger.info("[ChunkedUploader] Sending subscription request...")
            await websocket.send(json.dumps(subscribe_msg))
            
            # 等待响应
            response = await asyncio.wait_for(
                websocket.recv(),
                timeout=10
            )
            
            data = json.loads(response)
            logger.debug(f"[ChunkedUploader] Subscribe response: {data}")
            
            if data.get("errcode") == 0:
                logger.info("[ChunkedUploader] Subscription successful")
                return True
            else:
                logger.error(f"[ChunkedUploader] Subscription failed: {data.get('errmsg')}")
                return False
                
        except asyncio.TimeoutError:
            logger.error("[ChunkedUploader] Subscription timeout")
            return False
        except Exception as e:
            logger.error(f"[ChunkedUploader] Subscription error: {e}")
            return False
    
    async def _init_upload(
        self, 
        websocket, 
        file_path: str,
        file_name: str
    ) -> Optional[str]:
        """初始化上传会话
        
        Args:
            websocket: WebSocket 连接
            file_path: 文件路径
            file_name: 文件名
            
        Returns:
            upload_id 或 None
        """
        try:
            file_size = os.path.getsize(file_path)
            
            # 计算 MD5
            import hashlib
            md5_hash = hashlib.md5()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    md5_hash.update(chunk)
            file_md5 = md5_hash.hexdigest()
            
            init_msg = {
                "cmd": "aibot_upload_media_init",
                "headers": {
                    "req_id": self._generate_req_id()
                },
                "body": {
                    "bot_id": self.bot_id,
                    "secret": self.secret,
                    "type": "file",
                    "filename": file_name,
                    "filesize": file_size,
                    "total_size": file_size,
                    "filemd5": file_md5,
                    "total_chunks": self._calculate_chunks(file_size)
                }
            }
            
            logger.info(f"[ChunkedUploader] Initializing upload for {file_name}")
            
            await websocket.send(json.dumps(init_msg))
            
            # 等待响应
            response = await asyncio.wait_for(
                websocket.recv(),
                timeout=self.UPLOAD_TIMEOUT
            )
            
            data = json.loads(response)
            
            if data.get("errcode") == 0:
                upload_id = data.get("body", {}).get("upload_id")
                logger.info(f"[ChunkedUploader] Upload initialized: {upload_id}")
                return upload_id
            else:
                logger.error(f"[ChunkedUploader] Init failed: {data.get('errmsg')}")
                return None
                
        except asyncio.TimeoutError:
            logger.error("[ChunkedUploader] Init upload timeout")
            return None
        except Exception as e:
            logger.error(f"[ChunkedUploader] Init upload error: {e}")
            return None
    
    async def _upload_chunks(
        self,
        websocket,
        upload_id: str,
        file_path: str,
        total_chunks: int,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> bool:
        """上传所有分片
        
        Args:
            websocket: WebSocket 连接
            upload_id: 上传会话ID
            file_path: 文件路径
            total_chunks: 总分片数
            progress_callback: 进度回调
            
        Returns:
            是否全部上传成功
        """
        try:
            with open(file_path, 'rb') as f:
                for chunk_index in range(total_chunks):
                    # 读取分片
                    chunk_data = f.read(self.CHUNK_SIZE)
                    if not chunk_data:
                        break
                    
                    # Base64 编码
                    chunk_base64 = base64.b64encode(chunk_data).decode('utf-8')
                    
                    # 上传分片
                    chunk_msg = {
                        "cmd": "aibot_upload_media_chunk",
                        "headers": {
                            "req_id": self._generate_req_id()
                        },
                        "body": {
                            "upload_id": upload_id,
                            "chunk_index": chunk_index,
                            "base64_data": chunk_base64
                        }
                    }
                    
                    await websocket.send(json.dumps(chunk_msg))
                    
                    # 等待响应
                    response = await asyncio.wait_for(
                        websocket.recv(),
                        timeout=self.UPLOAD_TIMEOUT
                    )
                    
                    data = json.loads(response)
                    
                    if data.get("errcode") != 0:
                        logger.error(f"[ChunkedUploader] Chunk {chunk_index} failed: {data.get('errmsg')}")
                        return False
                    
                    logger.debug(f"[ChunkedUploader] Chunk {chunk_index}/{total_chunks} uploaded")
                    
                    # 回调进度
                    if progress_callback:
                        progress_callback(chunk_index + 1, total_chunks)
                    
                    # 小延迟避免频率限制
                    if chunk_index < total_chunks - 1:
                        await asyncio.sleep(0.1)
            
            logger.info(f"[ChunkedUploader] All {total_chunks} chunks uploaded")
            return True
            
        except asyncio.TimeoutError:
            logger.error("[ChunkedUploader] Chunk upload timeout")
            return False
        except Exception as e:
            logger.error(f"[ChunkedUploader] Chunk upload error: {e}")
            return False
    
    async def _finish_upload(
        self, 
        websocket, 
        upload_id: str,
        file_name: str
    ) -> Optional[str]:
        """完成上传并获取 media_id
        
        Args:
            websocket: WebSocket 连接
            upload_id: 上传会话ID
            file_name: 文件名
            
        Returns:
            media_id 或 None
        """
        try:
            finish_msg = {
                "cmd": "aibot_upload_media_finish",
                "headers": {
                    "req_id": self._generate_req_id()
                },
                "body": {
                    "upload_id": upload_id
                }
            }
            
            logger.info(f"[ChunkedUploader] Finishing upload: {upload_id}")
            
            await websocket.send(json.dumps(finish_msg))
            
            # 等待响应
            response = await asyncio.wait_for(
                websocket.recv(),
                timeout=self.UPLOAD_TIMEOUT
            )
            
            data = json.loads(response)
            
            if data.get("errcode") == 0:
                media_id = data.get("body", {}).get("media_id")
                logger.info(f"[ChunkedUploader] Upload finished: media_id={media_id}")
                return media_id
            else:
                logger.error(f"[ChunkedUploader] Finish failed: {data.get('errmsg')}")
                return None
                
        except asyncio.TimeoutError:
            logger.error("[ChunkedUploader] Finish upload timeout")
            return None
        except Exception as e:
            logger.error(f"[ChunkedUploader] Finish upload error: {e}")
            return None
    
    def _generate_req_id(self) -> str:
        """生成请求 ID"""
        import uuid
        return str(uuid.uuid4())


# 便捷函数
async def upload_file_to_wechat(
    file_path: str,
    bot_id: str,
    secret: str,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> UploadResult:
    """便捷函数：上传文件到企业微信
    
    Args:
        file_path: 本地文件路径
        bot_id: 智能机器人 BotID
        secret: 长连接密钥
        progress_callback: 进度回调
        
    Returns:
        UploadResult: 上传结果
        
    Example:
        result = await upload_file_to_wechat(
            "/path/to/file.pdf",
            "bot_id_here",
            "secret_here",
            lambda c, t: print(f"Progress: {c}/{t}")
        )
        if result.success:
            print(f"Media ID: {result.media_id}")
    """
    uploader = ChunkedUploader(bot_id, secret)
    return await uploader.upload_file(file_path, progress_callback)
