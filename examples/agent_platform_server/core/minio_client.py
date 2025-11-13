from __future__ import annotations


from common.exceptions import SageHTTPException
from config.settings import ENV, env_str

MINIO_CLIENT = None


async def upload_kdb_file(base_name: str, data: bytes, content_type: str) -> str:
    client = MINIO_CLIENT
    bucket = env_str(ENV.MINIO_BUCKET_NAME)
    public_base = env_str(ENV.MINIO_PUBLIC_BASE_URL)
    if not client or not bucket or not public_base:
        raise SageHTTPException(status_code=400, detail="MinIO not configured")
    from datetime import datetime
    import io
    from utils.file import split_file_name

    origin, ext = split_file_name(base_name)
    # 文件格式，原文件名后缀前加当前时间20230801120000
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
    except Exception as e:
        raise SageHTTPException(status_code=500, detail=str(e))


async def init_minio_client():
    try:
        from minio import Minio
    except Exception:
        return None

    endpoint = env_str(ENV.MINIO_ENDPOINT)
    ak = env_str(ENV.MINIO_ACCESS_KEY)
    sk = env_str(ENV.MINIO_SECRET_KEY)
    secure = env_str(ENV.MINIO_SECURE) == "true"
    bucket = env_str(ENV.MINIO_BUCKET_NAME)
    public_base = env_str(ENV.MINIO_PUBLIC_BASE_URL)
    if len(endpoint) == 0:
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
