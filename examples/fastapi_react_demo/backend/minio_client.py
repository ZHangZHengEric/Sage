"""
MinIO对象存储客户端
用于替代FTP服务，提供HTTP方式的文件存储和访问
"""

import os
import io
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path

from minio import Minio
from minio.error import S3Error
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class MinIOConfig(BaseModel):
    """MinIO配置模型"""
    enabled: bool = True
    endpoint: str = "localhost:40041"
    external_endpoint: str = "localhost:40041"
    access_key: str = "sage"
    secret_key: str = "sage123456"
    bucket: str = "workspace"
    region: str = "us-east-1"
    secure: bool = False
    console_url: str = "http://localhost:40042"


class FileInfo(BaseModel):
    """文件信息模型"""
    name: str
    size: int
    last_modified: datetime
    etag: str
    content_type: str
    url: Optional[str] = None


class MinIOClient:
    """MinIO客户端封装类"""
    
    def __init__(self, config: MinIOConfig):
        self.config = config
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """初始化MinIO客户端"""
        try:
            self.client = Minio(
                self.config.endpoint,
                access_key=self.config.access_key,
                secret_key=self.config.secret_key,
                secure=self.config.secure,
                region=self.config.region
            )
            
            # 检查连接并自动初始化
            self._ensure_bucket_exists()
            logger.info(f"Connected to MinIO bucket: {self.config.bucket}")
                
        except Exception as e:
            logger.error(f"Failed to initialize MinIO client: {e}")
            self.client = None
    
    def _ensure_bucket_exists(self):
        """确保bucket存在并配置正确"""
        try:
            # 由于workspace目录已经通过volume映射到/data/workspace
            # MinIO启动时会自动将此目录识别为workspace bucket
            # 我们只需要检查bucket是否可访问，如果不存在则创建
            if not self.client.bucket_exists(self.config.bucket):
                logger.info(f"Creating bucket: {self.config.bucket}")
                # 注意：由于使用了目录映射，这里的bucket实际对应 /data/workspace 目录
                self.client.make_bucket(self.config.bucket, location=self.config.region)
                logger.info(f"Created bucket: {self.config.bucket} (mapped to workspace directory)")
                
            # 设置public读取策略，允许通过HTTP直接访问文件
            try:
                policy = {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"AWS": "*"},
                            "Action": ["s3:GetObject"],
                            "Resource": [f"arn:aws:s3:::{self.config.bucket}/*"]
                        }
                    ]
                }
                self.client.set_bucket_policy(self.config.bucket, json.dumps(policy))
                logger.info(f"Set public read policy for bucket: {self.config.bucket}")
            except S3Error as e:
                # 策略设置失败不是致命错误，记录警告即可
                logger.warning(f"Failed to set bucket policy: {e}")
                
        except S3Error as e:
            logger.error(f"Failed to ensure bucket exists: {e}")
            raise
    
    def is_available(self) -> bool:
        """检查MinIO服务是否可用"""
        if not self.client:
            return False
        
        try:
            return self.client.bucket_exists(self.config.bucket)
        except Exception:
            return False
    
    def upload_file(self, local_path: str, object_name: str, content_type: Optional[str] = None) -> bool:
        """上传文件到MinIO"""
        if not self.client:
            logger.error("MinIO client not initialized")
            return False
        
        try:
            # 自动检测content type
            if not content_type:
                if object_name.endswith('.json'):
                    content_type = 'application/json'
                elif object_name.endswith('.txt'):
                    content_type = 'text/plain'
                elif object_name.endswith(('.png', '.jpg', '.jpeg')):
                    content_type = 'image/jpeg'
                else:
                    content_type = 'application/octet-stream'
            
            # 上传文件
            self.client.fput_object(
                self.config.bucket,
                object_name,
                local_path,
                content_type=content_type
            )
            
            logger.info(f"Uploaded file: {local_path} -> {object_name}")
            return True
            
        except S3Error as e:
            logger.error(f"Failed to upload file {local_path}: {e}")
            return False
    
    def upload_data(self, data: bytes, object_name: str, content_type: str = 'application/octet-stream') -> bool:
        """上传数据到MinIO"""
        if not self.client:
            logger.error("MinIO client not initialized")
            return False
        
        try:
            data_stream = io.BytesIO(data)
            self.client.put_object(
                self.config.bucket,
                object_name,
                data_stream,
                length=len(data),
                content_type=content_type
            )
            
            logger.info(f"Uploaded data to: {object_name}")
            return True
            
        except S3Error as e:
            logger.error(f"Failed to upload data to {object_name}: {e}")
            return False
    
    def download_file(self, object_name: str, local_path: str) -> bool:
        """从MinIO下载文件"""
        if not self.client:
            logger.error("MinIO client not initialized")
            return False
        
        try:
            # 创建本地目录
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            # 下载文件
            self.client.fget_object(self.config.bucket, object_name, local_path)
            
            logger.info(f"Downloaded file: {object_name} -> {local_path}")
            return True
            
        except S3Error as e:
            logger.error(f"Failed to download file {object_name}: {e}")
            return False
    
    def download_data(self, object_name: str) -> Optional[bytes]:
        """从MinIO下载数据"""
        if not self.client:
            logger.error("MinIO client not initialized")
            return None
        
        try:
            response = self.client.get_object(self.config.bucket, object_name)
            data = response.read()
            response.close()
            response.release_conn()
            
            logger.info(f"Downloaded data from: {object_name}")
            return data
            
        except S3Error as e:
            logger.error(f"Failed to download data from {object_name}: {e}")
            return None
    
    def delete_file(self, object_name: str) -> bool:
        """删除MinIO中的文件"""
        if not self.client:
            logger.error("MinIO client not initialized")
            return False
        
        try:
            self.client.remove_object(self.config.bucket, object_name)
            logger.info(f"Deleted file: {object_name}")
            return True
            
        except S3Error as e:
            logger.error(f"Failed to delete file {object_name}: {e}")
            return False
    
    def list_files(self, prefix: str = "", recursive: bool = True) -> List[FileInfo]:
        """列出MinIO中的文件"""
        if not self.client:
            logger.error("MinIO client not initialized")
            return []
        
        try:
            files = []
            objects = self.client.list_objects(
                self.config.bucket,
                prefix=prefix,
                recursive=recursive
            )
            
            for obj in objects:
                file_info = FileInfo(
                    name=obj.object_name,
                    size=obj.size,
                    last_modified=obj.last_modified,
                    etag=obj.etag,
                    content_type=obj.content_type or 'application/octet-stream',
                    url=self.get_file_url(obj.object_name)
                )
                files.append(file_info)
            
            return files
            
        except S3Error as e:
            logger.error(f"Failed to list files: {e}")
            return []
    
    def file_exists(self, object_name: str) -> bool:
        """检查文件是否存在"""
        if not self.client:
            return False
        
        try:
            self.client.stat_object(self.config.bucket, object_name)
            return True
        except S3Error:
            return False
    
    def get_file_info(self, object_name: str) -> Optional[FileInfo]:
        """获取文件信息"""
        if not self.client:
            return None
        
        try:
            stat = self.client.stat_object(self.config.bucket, object_name)
            return FileInfo(
                name=object_name,
                size=stat.size,
                last_modified=stat.last_modified,
                etag=stat.etag,
                content_type=stat.content_type or 'application/octet-stream',
                url=self.get_file_url(object_name)
            )
        except S3Error:
            return None
    
    def get_file_url(self, object_name: str, expires: Optional[timedelta] = None) -> str:
        """获取文件访问URL"""
        if expires:
            # 生成临时访问URL
            try:
                return self.client.presigned_get_object(
                    self.config.bucket,
                    object_name,
                    expires=expires
                )
            except S3Error:
                pass
        
        # 生成公共访问URL
        protocol = "https" if self.config.secure else "http"
        return f"{protocol}://{self.config.external_endpoint}/{self.config.bucket}/{object_name}"
    
    def sync_directory(self, local_dir: str, prefix: str = "") -> Tuple[int, int]:
        """同步本地目录到MinIO
        
        注意：由于workspace目录已通过Docker volume映射到MinIO，
        在大多数情况下不需要手动同步。此方法主要用于确保一致性。
        """
        if not self.client:
            logger.error("MinIO client not initialized")
            return 0, 0
        
        uploaded = 0
        failed = 0
        local_path = Path(local_dir)
        
        if not local_path.exists():
            logger.warning(f"Local directory not found: {local_dir}")
            return 0, 0
        
        logger.info(f"Syncing directory: {local_dir} to MinIO bucket: {self.config.bucket}")
        
        # 递归上传文件
        for file_path in local_path.rglob("*"):
            if file_path.is_file():
                # 计算相对路径作为object name
                relative_path = file_path.relative_to(local_path)
                object_name = str(relative_path).replace("\\", "/")
                if prefix:
                    object_name = f"{prefix.rstrip('/')}/{object_name}"
                
                # 检查文件是否已存在且内容相同
                if self._should_upload_file(str(file_path), object_name):
                    if self.upload_file(str(file_path), object_name):
                        uploaded += 1
                        logger.debug(f"Uploaded: {object_name}")
                    else:
                        failed += 1
                        logger.warning(f"Failed to upload: {object_name}")
        
        logger.info(f"Sync completed: {uploaded} uploaded, {failed} failed")
        return uploaded, failed
    
    def sync_workspace_to_minio(self, workspace_path: str) -> bool:
        """将本地workspace同步到MinIO
        
        这是一个便捷方法，专门用于同步workspace目录
        """
        try:
            uploaded, failed = self.sync_directory(workspace_path)
            if failed == 0:
                logger.info(f"Workspace sync successful: {uploaded} files uploaded")
                return True
            else:
                logger.warning(f"Workspace sync partially failed: {uploaded} uploaded, {failed} failed")
                return False
        except Exception as e:
            logger.error(f"Failed to sync workspace: {e}")
            return False
    
    def _should_upload_file(self, local_path: str, object_name: str) -> bool:
        """判断是否需要上传文件（基于修改时间和大小）"""
        try:
            local_stat = os.stat(local_path)
            file_info = self.get_file_info(object_name)
            
            if not file_info:
                return True  # 文件不存在，需要上传
            
            # 比较大小
            if local_stat.st_size != file_info.size:
                return True
            
            # 比较修改时间（考虑时区）
            local_mtime = datetime.fromtimestamp(local_stat.st_mtime)
            if local_mtime > file_info.last_modified.replace(tzinfo=None):
                return True
            
            return False  # 文件相同，不需要上传
            
        except Exception:
            return True  # 出错时选择上传
    
    def create_session_directory(self, session_id: str) -> str:
        """为会话创建目录并返回前缀"""
        prefix = f"sessions/{session_id}/"
        
        # 创建一个空的标记文件来"创建"目录
        marker_name = f"{prefix}.session_marker"
        marker_data = json.dumps({
            "session_id": session_id,
            "created_at": datetime.now().isoformat()
        }).encode()
        
        self.upload_data(marker_data, marker_name, "application/json")
        return prefix
    
    def cleanup_old_sessions(self, days: int = 7):
        """清理旧的会话文件"""
        if not self.client:
            return
        
        cutoff_date = datetime.now() - timedelta(days=days)
        deleted_count = 0
        
        try:
            # 列出所有会话文件
            objects = self.client.list_objects(
                self.config.bucket,
                prefix="sessions/",
                recursive=True
            )
            
            for obj in objects:
                if obj.last_modified.replace(tzinfo=None) < cutoff_date:
                    self.client.remove_object(self.config.bucket, obj.object_name)
                    deleted_count += 1
            
            logger.info(f"Cleaned up {deleted_count} old session files")
            
        except S3Error as e:
            logger.error(f"Failed to cleanup old sessions: {e}")


# 全局MinIO客户端实例
_minio_client: Optional[MinIOClient] = None


def get_minio_client() -> Optional[MinIOClient]:
    """获取全局MinIO客户端实例"""
    return _minio_client


def initialize_minio_client(config: MinIOConfig) -> MinIOClient:
    """初始化全局MinIO客户端"""
    global _minio_client
    _minio_client = MinIOClient(config)
    return _minio_client


def is_minio_enabled() -> bool:
    """检查MinIO是否启用且可用"""
    client = get_minio_client()
    return client is not None and client.is_available() 