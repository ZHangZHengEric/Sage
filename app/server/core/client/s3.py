from __future__ import annotations

import io
import json
from datetime import datetime
from typing import Optional

from loguru import logger

from ...core import config
from ...core.exceptions import SageHTTPException

S3_CLIENT: Optional["Minio"] = None


def _ensure_bucket(client, bucket: str) -> None:
    """
    确保桶存在，并设置公共读取策略
    """
    try:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": "*"},
                        "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
                        "Resource": f"arn:aws:s3:::{bucket}",
                    },
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": "*"},
                        "Action": "s3:GetObject",
                        "Resource": f"arn:aws:s3:::{bucket}/*",
                    },
                ],
            }
            client.set_bucket_policy(bucket, json.dumps(policy))
    except Exception as e:
        raise SageHTTPException(status_code=500, detail=f"RustFS 桶处理失败: {e}")


async def init_s3_client(
    cfg: Optional[config.StartupConfig] = None,
) -> Optional["Minio"]:
    """
    初始化 RustFS 客户端
    """
    global S3_CLIENT
    try:
        from minio import Minio
    except ImportError:
        logger.warning("RustFS 库未安装，跳过初始化")
        return None

    if cfg is None:
        raise RuntimeError("StartupConfig is required to initialize RustFS client")

    endpoint = cfg.s3_endpoint
    ak = cfg.s3_access_key
    sk = cfg.s3_secret_key
    secure = bool(cfg.s3_secure)
    bucket = cfg.s3_bucket_name
    public_base = cfg.s3_public_base_url

    if not endpoint or not ak or not sk or not bucket:
        logger.warning(
            f"RustFS 参数不足，跳过初始化"
        )
        return None

    # 去掉协议前缀
    if endpoint.startswith("http://"):
        ep = endpoint[7:]
    elif endpoint.startswith("https://"):
        ep = endpoint[8:]
    else:
        ep = endpoint

    client = Minio(ep, access_key=ak, secret_key=sk, secure=secure)

    if not public_base:
        public_base = ("https://" if secure else "http://") + ep + f"/{bucket}"

    _ensure_bucket(client, bucket)
    S3_CLIENT = client
    logger.debug(f"RustFS 客户端初始化成功: {endpoint}, 桶: {bucket}")
    return client


async def upload_file_with_path(
    file_data: bytes, 
    path: str, 
    content_type: str = "application/octet-stream"
) -> str:
    """
    上传文件到指定路径 (bucket/path)
    """
    client = S3_CLIENT
    cfg = config.get_startup_config()
    bucket = "sage" # Force bucket name as requested
    
    # Get public base URL
    if cfg and cfg.s3_public_base_url:
        public_base = cfg.s3_public_base_url
    elif cfg and cfg.s3_endpoint:
        protocol = "https://" if cfg.s3_secure else "http://"
        # Strip protocol if present in endpoint
        ep = cfg.s3_endpoint
        if ep.startswith("http://"): ep = ep[7:]
        elif ep.startswith("https://"): ep = ep[8:]
        public_base = f"{protocol}{ep}/{bucket}"
    else:
        # Fallback if config is missing (should be caught by client check)
        raise SageHTTPException(status_code=500, detail="S3 configuration missing")

    if not client:
        raise SageHTTPException(status_code=500, detail="S3 client not initialized")

    # Ensure bucket exists
    try:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            # Set public policy
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
                        "Resource": [f"arn:aws:s3:::{bucket}"],
                    },
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{bucket}/*"],
                    },
                ],
            }
            client.set_bucket_policy(bucket, json.dumps(policy))
    except Exception as e:
        logger.error(f"Failed to ensure bucket {bucket}: {e}")
        # Continue anyway, maybe it exists or we don't have permission to check/create

    # Upload
    try:
        client.put_object(
            bucket, 
            path, 
            io.BytesIO(file_data), 
            len(file_data), 
            content_type=content_type
        )
    except Exception as e:
        logger.error(f"S3 upload failed: {e}")
        raise SageHTTPException(status_code=500, detail=f"S3 upload failed: {str(e)}")

    url = f"{public_base}/{path}"
    logger.info(f"File uploaded to {bucket}/{path}: {url}")
    return url


async def upload_kdb_file(base_name: str, data: bytes, content_type: str) -> str:
    """
    上传文件到 RustFS 并返回公共 URL
    """
    client = S3_CLIENT
    cfg = config.get_startup_config()
    bucket = cfg.s3_bucket_name if cfg else None
    public_base = cfg.s3_public_base_url if cfg else None

    if not client or not bucket or not public_base:
        raise SageHTTPException(status_code=500, detail="RustFS 未配置或未初始化")

    from ...utils.file import split_file_name

    origin, ext = split_file_name(base_name)
    object_name = f"{origin}_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
    client.put_object(
        bucket, object_name, io.BytesIO(data), len(data), content_type=content_type
    )
    url = f"{public_base}/{object_name}"
    logger.info(f"文件上传成功: {url}")
    return url


async def close_s3_client() -> None:
    """
    清理 RustFS 客户端
    """
    global S3_CLIENT
    S3_CLIENT = None
    logger.info("RustFS 客户端已关闭")
