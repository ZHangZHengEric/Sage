from __future__ import annotations

from common.exceptions import SageHTTPException
import config
from sagents.utils.logger import logger

MINIO_CLIENT = None


async def upload_kdb_file(base_name: str, data: bytes, content_type: str) -> str:
    client = MINIO_CLIENT
    cfg = config.get_startup_config()
    bucket = cfg.minio_bucket_name if cfg else None
    public_base = cfg.minio_public_base_url if cfg else None
    if not client or not bucket or not public_base:
        raise SageHTTPException(status_code=400, detail="MinIO not configured")
    from datetime import datetime
    import io
    from utils.file import split_file_name

    origin, ext = split_file_name(base_name)
    object_name = f"{origin}_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
    client.put_object(
        bucket, object_name, io.BytesIO(data), len(data), content_type=content_type
    )
    return f"{public_base}/{object_name}"


def _minio_ensure_bucket(client, bucket: str) -> None:
    try:
        found = client.bucket_exists(bucket)
        if not found:
            client.make_bucket(bucket)
            import json

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
        raise SageHTTPException(status_code=500, detail=str(e))


async def init_minio_client(cfg: config.StartupConfig | None = None):
    try:
        from minio import Minio
    except Exception:
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
    if endpoint.startswith("http://"):
        ep = endpoint[7:]
    elif endpoint.startswith("https://"):
        ep = endpoint[8:]
    else:
        ep = endpoint
    client = Minio(ep, access_key=ak, secret_key=sk, secure=secure)
    if len(public_base) == 0:
        public_base = ("https://" if secure else "http://") + ep + f"/{bucket}"
    _minio_ensure_bucket(client, bucket)
    global MINIO_CLIENT
    MINIO_CLIENT = client
    return client


async def close_minio_client() -> None:
    global MINIO_CLIENT
    MINIO_CLIENT = None
