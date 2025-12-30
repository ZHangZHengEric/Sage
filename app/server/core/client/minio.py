from __future__ import annotations
from typing import Optional
from datetime import datetime
import io
import json

from core import config
from core.exceptions import SageHTTPException
from sagents.utils.logger import logger

MINIO_CLIENT: Optional["Minio"] = None


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
            logger.info(f"MinIO 桶创建并设置策略成功: {bucket}")
    except Exception as e:
        raise SageHTTPException(status_code=500, detail=f"MinIO 桶处理失败: {e}")


async def init_minio_client(
    cfg: Optional[config.StartupConfig] = None,
) -> Optional["Minio"]:
    """
    初始化 MinIO 客户端
    """
    global MINIO_CLIENT
    try:
        from minio import Minio
    except ImportError:
        logger.warning("MinIO 库未安装，跳过初始化")
        return None

    if cfg is None:
        raise RuntimeError("StartupConfig is required to initialize MinIO client")

    endpoint = cfg.minio_endpoint
    ak = cfg.minio_access_key
    sk = cfg.minio_secret_key
    secure = bool(cfg.minio_secure)
    bucket = cfg.minio_bucket_name
    public_base = cfg.minio_public_base_url

    if not endpoint or not ak or not sk or not bucket:
        logger.warning(
            f"MinIO 参数不足，未初始化 endpoint={endpoint}, bucket={bucket}, access_key={ak}, secret_key={sk}"
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
    MINIO_CLIENT = client
    logger.info(f"MinIO 客户端初始化成功: {endpoint}, 桶: {bucket}")
    return client


async def upload_kdb_file(base_name: str, data: bytes, content_type: str) -> str:
    """
    上传文件到 MinIO 并返回公共 URL
    """
    client = MINIO_CLIENT
    cfg = config.get_startup_config()
    bucket = cfg.minio_bucket_name if cfg else None
    public_base = cfg.minio_public_base_url if cfg else None

    if not client or not bucket or not public_base:
        raise SageHTTPException(status_code=400, detail="MinIO 未配置或未初始化")

    from utils.file import split_file_name

    origin, ext = split_file_name(base_name)
    object_name = f"{origin}_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
    client.put_object(
        bucket, object_name, io.BytesIO(data), len(data), content_type=content_type
    )
    url = f"{public_base}/{object_name}"
    logger.info(f"文件上传成功: {url}")
    return url


async def close_minio_client() -> None:
    """
    清理 MinIO 客户端
    """
    global MINIO_CLIENT
    MINIO_CLIENT = None
    logger.info("MinIO 客户端已关闭")
