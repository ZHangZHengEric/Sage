"""WeChat Work file handling module.

企业微信文件处理模块
支持文件下载、解密、管理和上传功能
"""

import os
import hashlib
import base64
import logging
import tempfile
import asyncio
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger("WeChatWorkFileHandler")


@dataclass
class FileInfo:
    """文件信息数据类"""
    name: str
    size: int
    mime_type: str
    local_path: str
    url: Optional[str] = None
    aes_key: Optional[str] = None
    download_time: datetime = field(default_factory=datetime.now)
    
    @property
    def is_encrypted(self) -> bool:
        """文件是否需要解密"""
        return self.aes_key is not None


class FileDecryptor:
    """企业微信文件解密器
    
    使用 AES-256-CBC 算法解密企业微信推送的加密文件
    - 加密方式: AES-256-CBC
    - 填充方式: PKCS#7
    - IV: aeskey 前 16 字节
    - aeskey 格式: Base64 编码的字符串
    """
    
    @staticmethod
    def decrypt(encrypted_data: bytes, aes_key: str) -> bytes:
        """解密文件数据
        
        Args:
            encrypted_data: 加密的文件数据
            aes_key: Base64 编码的解密密钥 (解码后应为 32 字节)
            
        Returns:
            解密后的文件数据
            
        Raises:
            ValueError: 解密失败
        """
        try:
            # 企业微信返回的 aeskey 是 Base64 编码的，需要先解码
            import base64
            
            # 修复可能缺少的 Base64 padding (企业微信有时会省略末尾的 =)
            padding_needed = 4 - (len(aes_key) % 4)
            if padding_needed != 4:
                aes_key = aes_key + ('=' * padding_needed)
            
            key = base64.b64decode(aes_key)
            
            if len(key) != 32:
                raise ValueError(f"AES key must be 32 bytes after Base64 decode, got {len(key)}")
            
            iv = key[:16]  # 取前16字节作为 IV
            
            # 创建 Cipher
            cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
            decryptor = cipher.decryptor()
            
            # 解密数据
            decrypted = decryptor.update(encrypted_data) + decryptor.finalize()
            
            # 去除 PKCS#7 填充
            unpadder = padding.PKCS7(256).unpadder()
            data = unpadder.update(decrypted) + unpadder.finalize()
            
            logger.info(f"[FileDecryptor] Decrypted {len(encrypted_data)} bytes -> {len(data)} bytes")
            return data
            
        except base64.binascii.Error as e:
            logger.error(f"[FileDecryptor] Base64 decode failed: {e}")
            raise ValueError(f"Invalid Base64 aeskey: {e}")
        except Exception as e:
            logger.error(f"[FileDecryptor] Decryption failed: {e}")
            raise ValueError(f"Failed to decrypt file: {e}")


class FileDownloader:
    """文件下载器"""
    
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client
    
    async def download(
        self, 
        url: str, 
        aes_key: Optional[str] = None,
        filename: Optional[str] = None
    ) -> FileInfo:
        """下载并解密文件
        
        Args:
            url: 文件下载地址
            aes_key: 解密密钥 (如果文件加密)
            filename: 文件名 (如果未提供，从URL或Content-Disposition获取)
            
        Returns:
            FileInfo: 文件信息
        """
        client = await self._get_client()
        
        try:
            logger.info(f"[FileDownloader] Downloading from {url[:50]}...")
            
            response = await client.get(url)
            response.raise_for_status()
            
            # 获取文件名
            if not filename:
                filename = self._extract_filename(response, url)
            
            # 获取原始数据
            raw_data = response.content
            logger.info(f"[FileDownloader] Downloaded {len(raw_data)} bytes")
            
            # 解密 (如果需要)
            if aes_key:
                data = FileDecryptor.decrypt(raw_data, aes_key)
                logger.info(f"[FileDownloader] File decrypted successfully")
            else:
                data = raw_data
            
            # 保存到临时目录
            local_path = await self._save_to_temp(data, filename)
            
            # 检测 MIME 类型
            mime_type = self._detect_mime_type(filename, data)
            
            return FileInfo(
                name=filename,
                size=len(data),
                mime_type=mime_type,
                local_path=local_path,
                url=url,
                aes_key=aes_key
            )
            
        except httpx.HTTPError as e:
            logger.error(f"[FileDownloader] HTTP error: {e}")
            raise
        except Exception as e:
            logger.error(f"[FileDownloader] Download failed: {e}")
            raise
    
    def _extract_filename(self, response: httpx.Response, url: str) -> str:
        """从响应头或URL提取文件名"""
        # 尝试从 Content-Disposition 获取
        content_disposition = response.headers.get('content-disposition', '')
        if 'filename=' in content_disposition:
            parts = content_disposition.split('filename=')
            if len(parts) > 1:
                filename = parts[1].strip('"\'')
                return filename
        
        # 从 URL 路径获取
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path
        if path:
            filename = os.path.basename(path)
            if filename:
                return filename
        
        # 默认文件名
        return f"unknown_file_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    async def _save_to_temp(self, data: bytes, filename: str) -> str:
        """保存数据到临时文件"""
        # 创建专用目录
        temp_dir = Path(tempfile.gettempdir()) / "wechat_work_files"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成安全文件名
        safe_filename = self._sanitize_filename(filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_name = f"{timestamp}_{safe_filename}"
        
        file_path = temp_dir / unique_name
        
        # 异步写入
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, file_path.write_bytes, data)
        
        logger.info(f"[FileDownloader] Saved to {file_path}")
        return str(file_path)
    
    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名，移除不安全字符"""
        import re
        # 保留字母数字、中文、常见符号
        safe = re.sub(r'[^\w\-\.\u4e00-\u9fff]', '_', filename)
        # 限制长度
        if len(safe) > 100:
            name, ext = os.path.splitext(safe)
            safe = name[:96] + ext
        return safe
    
    def _detect_mime_type(self, filename: str, data: bytes) -> str:
        """检测 MIME 类型"""
        import mimetypes
        
        # 从扩展名检测
        mime_type, _ = mimetypes.guess_type(filename)
        if mime_type:
            return mime_type
        
        # 从文件内容检测 (简单魔数检测)
        magic_mimes = {
            b'\x89PNG': 'image/png',
            b'\xff\xd8\xff': 'image/jpeg',
            b'GIF87a': 'image/gif',
            b'GIF89a': 'image/gif',
            b'%PDF': 'application/pdf',
            b'PK\x03\x04': 'application/zip',
        }
        
        for magic, mime in magic_mimes.items():
            if data.startswith(magic):
                return mime
        
        return 'application/octet-stream'
    
    async def close(self):
        """关闭客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


class FileManager:
    """文件管理器
    
    管理下载的文件，包括缓存、清理等功能
    """
    
    def __init__(self, max_age_hours: int = 24):
        self.max_age_hours = max_age_hours
        self._files: Dict[str, FileInfo] = {}  # local_path -> FileInfo
        self._cleanup_task: Optional[asyncio.Task] = None
    
    def register_file(self, file_info: FileInfo) -> str:
        """注册文件到管理器"""
        file_id = hashlib.md5(file_info.local_path.encode()).hexdigest()[:12]
        self._files[file_id] = file_info
        logger.info(f"[FileManager] Registered file {file_id}: {file_info.name}")
        return file_id
    
    def get_file(self, file_id: str) -> Optional[FileInfo]:
        """获取文件信息"""
        return self._files.get(file_id)
    
    def get_file_by_path(self, local_path: str) -> Optional[FileInfo]:
        """通过路径获取文件信息"""
        for file_info in self._files.values():
            if file_info.local_path == local_path:
                return file_info
        return None
    
    async def start_cleanup_task(self):
        """启动定期清理任务"""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    async def stop_cleanup_task(self):
        """停止清理任务"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
    
    async def _cleanup_loop(self):
        """定期清理过期文件"""
        while True:
            try:
                await asyncio.sleep(3600)  # 每小时检查一次
                await self.cleanup_expired_files()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[FileManager] Cleanup error: {e}")
    
    async def cleanup_expired_files(self):
        """清理过期文件"""
        expired_time = datetime.now() - timedelta(hours=self.max_age_hours)
        expired_ids = []
        
        for file_id, file_info in self._files.items():
            if file_info.download_time < expired_time:
                expired_ids.append(file_id)
        
        for file_id in expired_ids:
            file_info = self._files.pop(file_id, None)
            if file_info and os.path.exists(file_info.local_path):
                try:
                    os.remove(file_info.local_path)
                    logger.info(f"[FileManager] Cleaned up expired file: {file_info.name}")
                except Exception as e:
                    logger.warning(f"[FileManager] Failed to remove file: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取文件统计信息"""
        total_size = sum(f.size for f in self._files.values())
        return {
            "total_files": len(self._files),
            "total_size_bytes": total_size,
            "max_age_hours": self.max_age_hours
        }


# 全局文件管理器实例
_file_manager: Optional[FileManager] = None
_file_downloader: Optional[FileDownloader] = None


def get_file_manager() -> FileManager:
    """获取全局文件管理器"""
    global _file_manager
    if _file_manager is None:
        _file_manager = FileManager()
    return _file_manager


def get_file_downloader() -> FileDownloader:
    """获取全局文件下载器"""
    global _file_downloader
    if _file_downloader is None:
        _file_downloader = FileDownloader()
    return _file_downloader


async def download_wechat_file(
    url: str, 
    aes_key: Optional[str] = None,
    filename: Optional[str] = None
) -> FileInfo:
    """便捷函数：下载企业微信文件
    
    Args:
        url: 文件下载地址
        aes_key: 解密密钥
        filename: 文件名
        
    Returns:
        FileInfo: 文件信息
    """
    downloader = get_file_downloader()
    file_info = await downloader.download(url, aes_key, filename)
    
    # 注册到管理器
    manager = get_file_manager()
    manager.register_file(file_info)
    
    return file_info
