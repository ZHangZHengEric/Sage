"""WeChat Work file handling module.

企业微信文件处理模块
支持文件下载、解密、管理和上传功能

文件存储路径: ~/.sage/files/{user_id}/
"""

import os
import hashlib
import base64
import logging
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


def get_sage_files_dir(
    provider: Optional[str] = None,
    chat_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> Path:
    """获取 Sage 文件存储目录
    
    Args:
        provider: IM 平台类型 (wechat_work, feishu, dingtalk, imessage)
        chat_id: 群聊/频道ID（可选）
        user_id: 用户ID（可选）
        
    Returns:
        Path: 文件存储目录路径
        
    路径结构:
        ~/.sage/files/im/{provider}/{chat_id_or_user_id}/
        
    示例:
        - 企业微信群聊: ~/.sage/files/im/wechat_work/group_xxx/
        - 企业微信单聊: ~/.sage/files/im/wechat_work/user_xxx/
        - 飞书私聊: ~/.sage/files/im/feishu/user_xxx/
    """
    def _sanitize_dir_name(name: Optional[str]) -> Optional[str]:
        """清理目录名，只保留安全字符"""
        if not name:
            return None
        sanitized = "".join(c for c in name if c.isalnum() or c in "-_").strip()
        return sanitized if sanitized else None
    
    # 获取用户主目录
    home_dir = Path.home()
    
    # 构建基础路径: ~/.sage/files/im
    sage_files_dir = home_dir / ".sage" / "files" / "im"
    
    # 添加 provider 层级
    if provider:
        safe_provider = _sanitize_dir_name(provider)
        if safe_provider:
            sage_files_dir = sage_files_dir / safe_provider
    
    # 确定最后层级: 优先使用 chat_id（群聊），否则使用 user_id（单聊）
    target_id = chat_id or user_id
    if target_id:
        safe_target_id = _sanitize_dir_name(target_id)
        if safe_target_id:
            sage_files_dir = sage_files_dir / safe_target_id
    
    # 创建目录
    sage_files_dir.mkdir(parents=True, exist_ok=True)
    
    return sage_files_dir


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
            self._client = httpx.AsyncClient(timeout=self.timeout, trust_env=False)
        return self._client
    
    async def _download_async(
        self, 
        url: str, 
        aes_key: Optional[str] = None,
        filename: Optional[str] = None,
        provider: Optional[str] = None,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> FileInfo:
        """异步下载文件
        
        Args:
            url: 文件下载地址
            aes_key: 解密密钥 (如果文件加密)
            filename: 文件类型标识 (如 "image", "voice", "file" 等)
            provider: IM 平台类型
            chat_id: 群聊/频道ID（可选）
            user_id: 用户ID（可选）
            
        Returns:
            FileInfo: 文件信息
        """
        try:
            logger.info(f"[FileDownloader] 异步下载: {url[:50]}...")

            client = await self._get_client()
            response = await client.get(url)
            response.raise_for_status()

            # 获取原始数据
            raw_data = response.content
            logger.info(f"[FileDownloader] 下载完成: {len(raw_data)} bytes")
            
            # 解密 (如果需要) - 解密是 CPU 操作，不需要事件循环
            if aes_key:
                data = FileDecryptor.decrypt(raw_data, aes_key)
                logger.info(f"[FileDownloader] 文件解密成功")
            else:
                data = raw_data
            
            # 确定扩展名
            file_type = filename or "file"
            extension = self._detect_extension(response, url, data, file_type)
            
            # 保存文件放到线程里，避免阻塞事件循环
            local_path = await asyncio.to_thread(
                self._save_file_sync,
                data,
                file_type,
                extension,
                provider,
                chat_id,
                user_id,
            )
            
            # 构建完整文件名
            full_filename = f"{file_type}.{extension}"
            
            # 检测 MIME 类型
            mime_type = self._detect_mime_type(full_filename, data)
            
            return FileInfo(
                name=full_filename,
                size=len(data),
                mime_type=mime_type,
                local_path=local_path,
                url=url,
                aes_key=aes_key
            )
            
        except httpx.HTTPError as e:
            logger.error(f"[FileDownloader] HTTP 错误: {e}")
            raise
        except Exception as e:
            logger.error(f"[FileDownloader] 下载失败: {e}")
            raise

    def download_sync(
        self, 
        url: str, 
        aes_key: Optional[str] = None,
        filename: Optional[str] = None,
        provider: Optional[str] = None,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> FileInfo:
        """同步下载文件兼容入口。"""
        try:
            return asyncio.run(
                self._download_async(url, aes_key, filename, provider, chat_id, user_id)
            )
        finally:
            if self._client is not None and not self._client.is_closed:
                asyncio.run(self._client.aclose())
    
    async def download(
        self, 
        url: str, 
        aes_key: Optional[str] = None,
        filename: Optional[str] = None,
        provider: Optional[str] = None,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> FileInfo:
        """异步下载文件（主入口）。

        Returns:
            FileInfo: 文件信息
        """
        return await self._download_async(url, aes_key, filename, provider, chat_id, user_id)
    
    def _detect_extension(
        self, 
        response: httpx.Response, 
        url: str, 
        data: bytes,
        file_type: str
    ) -> str:
        """检测文件扩展名（多优先级）
        
        优先级顺序：
        1. HTTP Content-Disposition 头中的文件名
        2. URL 路径中的文件名
        3. 文件内容魔数检测
        4. 根据文件类型使用默认扩展名
        
        Args:
            response: HTTP 响应
            url: 下载 URL
            data: 文件数据
            file_type: 文件类型标识 (image/voice/video/file)
            
        Returns:
            str: 扩展名 (不含点)
        """
        # 1. 尝试从 Content-Disposition 提取扩展名
        content_disposition = response.headers.get('content-disposition', '')
        if 'filename=' in content_disposition:
            parts = content_disposition.split('filename=')
            if len(parts) > 1:
                filename = parts[1].strip('"\'')
                if '.' in filename:
                    return filename.rsplit('.', 1)[1].lower()
        
        # 2. 尝试从 URL 路径提取扩展名
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path
        if path:
            url_filename = os.path.basename(path).split('?')[0]
            if '.' in url_filename:
                return url_filename.rsplit('.', 1)[1].lower()
        
        # 3. 从文件内容魔数检测
        magic_exts = {
            b'\x89PNG': 'png',
            b'\xff\xd8\xff': 'jpg',
            b'GIF87a': 'gif',
            b'GIF89a': 'gif',
            b'%PDF': 'pdf',
            b'PK\x03\x04': 'zip',
            b'\x25\x50\x44\x46': 'pdf',  # PDF
            b'\x50\x4b\x03\x04': 'zip',  # ZIP (docx/xlsx/pptx 都是 zip)
            b'\xd0\xcf\x11\xe0': 'doc',  # MS Office 旧格式
            b'\x7b\x5c\x72\x74\x66': 'rtf',  # RTF
        }
        for magic, ext in magic_exts.items():
            if data.startswith(magic):
                # 对于 ZIP 格式，可能是 docx/xlsx/pptx，需要进一步判断
                if ext == 'zip' and len(data) > 100:
                    # 检查是否包含 [Content_Types].xml
                    try:
                        content_types = b'[Content_Types].xml'
                        if content_types in data[:5000]:
                            # 可能是 Office 2007+ 格式
                            if b'word/' in data[:5000]:
                                return 'docx'
                            elif b'xl/' in data[:5000]:
                                return 'xlsx'
                            elif b'ppt/' in data[:5000]:
                                return 'pptx'
                    except:
                        pass
                return ext
        
        # 4. 根据文件类型使用默认扩展名
        default_exts = {
            'image': 'jpg',
            'voice': 'mp3',
            'video': 'mp4',
            'file': 'bin'
        }
        return default_exts.get(file_type, 'bin')
    
    def _save_file_sync(
        self, 
        data: bytes, 
        file_type: str,
        extension: str,
        provider: Optional[str] = None,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> str:
        """同步保存文件
        
        完全同步的文件保存方法，不依赖任何异步操作。
        
        Args:
            data: 文件数据
            file_type: 文件类型标识
            extension: 文件扩展名
            provider: IM 平台类型
            chat_id: 群聊/频道ID
            user_id: 用户ID
            
        Returns:
            str: 保存后的文件完整路径
        """
        # 获取 Sage 文件目录
        files_dir = get_sage_files_dir(provider, chat_id, user_id)
        
        # 生成时间戳文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_type = self._sanitize_filename(file_type)[:20]
        safe_ext = self._sanitize_filename(extension)[:10]
        unique_name = f"{timestamp}_{safe_type}.{safe_ext}"
        
        file_path = files_dir / unique_name
        
        # 同步文件写入
        file_path.write_bytes(data)
        
        logger.info(f"[FileDownloader] 同步保存: {file_path}")
        return str(file_path)
    
    async def _save_file(
        self, 
        data: bytes, 
        file_type: str,
        extension: str,
        provider: Optional[str] = None,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> str:
        """异步保存文件（包装器）
        
        内部使用同步保存，在后台线程中执行。
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._save_file_sync,
            data, file_type, extension, provider, chat_id, user_id
        )
    
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
    
    def _has_extension(self, filename: str) -> bool:
        """检查文件名是否有扩展名"""
        return '.' in filename and not filename.endswith('.')
    
    def _get_extension(self, filename: str) -> str:
        """获取文件扩展名（包含点）"""
        if '.' in filename:
            return '.' + filename.split('.')[-1]
        return ''
    
    def _detect_mime_type(self, filename: str, data: bytes) -> str:
        """检测 MIME 类型"""
        import mimetypes
        
        # 从扩展名检测
        mime_type, _ = mimetypes.guess_type(filename)
        if mime_type:
            return mime_type
        
        # 从文件内容检测 (简单魔数检测)
        return self._detect_mime_from_content(data)
    
    def _detect_mime_from_content(self, data: bytes) -> str:
        """从文件内容检测 MIME 类型"""
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
    
    def _detect_extension_from_content(self, data: bytes) -> str:
        """从文件内容检测扩展名"""
        magic_exts = {
            b'\x89PNG': 'png',
            b'\xff\xd8\xff': 'jpg',
            b'GIF87a': 'gif',
            b'GIF89a': 'gif',
            b'%PDF': 'pdf',
            b'PK\x03\x04': 'zip',
        }
        
        for magic, ext in magic_exts.items():
            if data.startswith(magic):
                return ext
        
        return 'bin'
    
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
    filename: Optional[str] = None,
    provider: str = "wechat_work",
    chat_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> FileInfo:
    """便捷函数：下载企业微信文件
    
    Args:
        url: 文件下载地址
        aes_key: 解密密钥
        filename: 文件名
        provider: IM 平台类型 (默认: wechat_work)
        chat_id: 群聊/频道ID
        user_id: 用户ID
        
    Returns:
        FileInfo: 文件信息
        
    文件存储路径:
        ~/.sage/files/im/{provider}/{chat_id_or_user_id}/{timestamp}_{filename}
    """
    downloader = get_file_downloader()
    file_info = await downloader.download(url, aes_key, filename, provider, chat_id, user_id)
    
    # 注册到管理器
    manager = get_file_manager()
    manager.register_file(file_info)
    
    return file_info
