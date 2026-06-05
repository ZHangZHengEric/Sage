import asyncio
import base64
import math
import mimetypes
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Optional, cast
from uuid import uuid4

import httpx
from loguru import logger
from PIL import Image, ImageOps, UnidentifiedImageError

from common.core.client.s3 import upload_kdb_file
from common.core.exceptions import SageHTTPException

DOUBAO_IMAGE_MAX_BYTES = 5 * 1024 * 1024
_JPEG_QUALITY_STEPS = (88, 82, 76, 70, 64, 58)
_IMAGE_MODULE: Any = Image
_RESAMPLE_LANCZOS = (
    _IMAGE_MODULE.Resampling.LANCZOS
    if hasattr(_IMAGE_MODULE, "Resampling")
    else _IMAGE_MODULE.LANCZOS
)
_HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_DATA_IMAGE_PATTERN = re.compile(
    r"^data:(image/[a-zA-Z0-9.+-]+);base64,(?P<data>.+)$",
    re.DOTALL,
)


async def _upload_image_bytes_to_oss(
    image_bytes: bytes,
    *,
    file_type: str,
    filename_prefix: str,
) -> str:
    normalized_type = file_type.strip().lower().lstrip(".")
    extension, content_type = _resolve_image_file_type(normalized_type)

    base_name = f"{filename_prefix}{int(time.time() * 1000)}_{uuid4().hex}.{extension}"
    return await upload_kdb_file(base_name, image_bytes, content_type)


def _resolve_image_file_type(file_type: str) -> tuple[str, str]:
    normalized_type = file_type.strip().lower().lstrip(".")
    if normalized_type in {"jpg", "jpeg"}:
        return "jpg", "image/jpeg"
    if normalized_type == "png":
        return "png", "image/png"
    extension = normalized_type or "bin"
    content_type = f"image/{extension}" if extension else "application/octet-stream"
    return extension, content_type


def _encode_image_bytes_as_data_url(image_bytes: bytes, content_type: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _is_s3_unconfigured_error(exc: SageHTTPException) -> bool:
    detail = str(getattr(exc, "detail", "") or "")
    return any(
        marker in detail
        for marker in (
            "RustFS 未配置",
            "RustFS 参数不足",
            "S3 configuration missing",
            "S3 client not initialized",
            "not initialized",
            "configuration missing",
        )
    )


async def _upload_image_bytes_to_oss_or_data_url(
    image_bytes: bytes,
    *,
    file_type: str,
    filename_prefix: str,
) -> str:
    normalized_type = file_type.strip().lower().lstrip(".")
    _, content_type = _resolve_image_file_type(normalized_type)
    try:
        return await _upload_image_bytes_to_oss(
            image_bytes,
            file_type=file_type,
            filename_prefix=filename_prefix,
        )
    except SageHTTPException as exc:
        if not _is_s3_unconfigured_error(exc):
            raise
        logger.warning(
            "S3/RustFS 未配置，使用压缩后的 base64 图片替换: bytes={} content_type={}",
            len(image_bytes),
            content_type,
        )
        return _encode_image_bytes_as_data_url(image_bytes, content_type)


def _is_remote_url(path: str) -> bool:
    return path.startswith("http://") or path.startswith("https://")


def _decode_data_image_url(source: str) -> Optional[tuple[bytes, str]]:
    match = _DATA_IMAGE_PATTERN.match(source)
    if not match:
        return None
    encoded = re.sub(r"\s+", "", match.group("data"))
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("无法解码 base64 图片") from exc
    return image_bytes, match.group(1)


def _parse_content_length(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        size = int(value)
    except (TypeError, ValueError):
        return None
    return size if size >= 0 else None


async def _fetch_remote_content_length(image_url: str) -> Optional[int]:
    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT, follow_redirects=True
        ) as client:
            response = await client.head(image_url)
    except Exception:
        return None

    if response.status_code >= 400:
        return None
    return _parse_content_length(response.headers.get("Content-Length"))


async def load_image_source_bytes(source: str) -> tuple[bytes, str]:
    normalized_source = str(source or "").strip()
    if not normalized_source:
        raise ValueError("图片地址为空")

    if _is_remote_url(normalized_source):
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT, follow_redirects=True
        ) as client:
            response = await client.get(normalized_source)
            response.raise_for_status()
            mime_type = (
                response.headers.get("Content-Type", "application/octet-stream")
                .split(";")[0]
                .strip()
            )
            return response.content, mime_type or "application/octet-stream"

    file_path = Path(normalized_source)
    if not file_path.exists():
        raise FileNotFoundError(f"图片文件不存在: {normalized_source}")

    image_bytes = await asyncio.to_thread(file_path.read_bytes)
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return image_bytes, mime_type


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    if image.mode in ("RGB", "L"):
        return image.convert("RGB")

    rgba_image = image.convert("RGBA")
    background = cast(
        Image.Image,
        _IMAGE_MODULE.new("RGBA", rgba_image.size, (255, 255, 255, 255)),
    )
    return Image.alpha_composite(background, rgba_image).convert("RGB")


def _compress_image_bytes_to_limit(
    image_bytes: bytes, max_bytes: int = DOUBAO_IMAGE_MAX_BYTES
) -> bytes:
    try:
        with Image.open(BytesIO(image_bytes)) as source_image:
            source_image = cast(Image.Image, ImageOps.exif_transpose(source_image))
            source_image.load()
            original_width, original_height = source_image.size
            if original_width <= 0 or original_height <= 0:
                raise ValueError("图片尺寸无效")

            scale = min(
                1.0, math.sqrt(max_bytes / float(max(len(image_bytes), 1))) * 0.95
            )

            for attempt in range(10):
                target_scale = min(1.0, scale * (0.82**attempt))
                target_width = max(1, int(original_width * target_scale))
                target_height = max(1, int(original_height * target_scale))

                candidate_image = source_image.copy()
                if target_width < original_width or target_height < original_height:
                    candidate_image.thumbnail(
                        (target_width, target_height), _RESAMPLE_LANCZOS
                    )

                candidate_image = _flatten_to_rgb(candidate_image)
                for quality in _JPEG_QUALITY_STEPS:
                    buffer = BytesIO()
                    try:
                        candidate_image.save(
                            buffer,
                            format="JPEG",
                            quality=quality,
                            progressive=True,
                            optimize=True,
                        )
                    except OSError:
                        candidate_image.save(
                            buffer,
                            format="JPEG",
                            quality=quality,
                            progressive=True,
                        )
                    if buffer.tell() <= max_bytes:
                        return buffer.getvalue()

            raise ValueError("图片压缩后仍超过大小限制")
    except UnidentifiedImageError as exc:
        raise ValueError("无法识别图片格式") from exc


async def ensure_image_url_within_size_limit(
    image_url: str,
    max_bytes: int = DOUBAO_IMAGE_MAX_BYTES,
) -> str:
    source = str(image_url or "").strip()
    if not source:
        return source

    data_image = _decode_data_image_url(source)
    if data_image is not None:
        image_bytes, mime_type = data_image
        original_bytes = len(image_bytes)
        if original_bytes <= max_bytes:
            return source

        compressed_bytes = await asyncio.to_thread(
            _compress_image_bytes_to_limit,
            image_bytes,
            max_bytes,
        )
        guarded_url = await _upload_image_bytes_to_oss_or_data_url(
            compressed_bytes,
            file_type="jpeg",
            filename_prefix="doubao_guard_base64_",
        )
        logger.info(
            "base64 图片超限，已等比压缩并重新上传: mime_type={} new={} original_bytes={} compressed_bytes={} limit={}",
            mime_type,
            guarded_url,
            original_bytes,
            len(compressed_bytes),
            max_bytes,
        )
        return guarded_url

    if source.startswith("data:"):
        return source

    if _is_remote_url(source):
        content_length = await _fetch_remote_content_length(source)
        if content_length is not None and content_length <= max_bytes:
            return source
    else:
        file_path = Path(source)
        if not file_path.exists():
            return source
        if file_path.stat().st_size <= max_bytes:
            return source

    image_bytes, _ = await load_image_source_bytes(source)
    original_bytes = len(image_bytes)
    if original_bytes <= max_bytes and _is_remote_url(source):
        return source

    compressed_bytes = await asyncio.to_thread(
        _compress_image_bytes_to_limit,
        image_bytes,
        max_bytes,
    )

    guarded_url = await _upload_image_bytes_to_oss_or_data_url(
        compressed_bytes,
        file_type="jpeg",
        filename_prefix="doubao_guard_",
    )

    logger.info(
        "图片超限，已等比压缩并重新上传: source={}, new={} original_bytes={} compressed_bytes={} limit={}",
        source,
        guarded_url,
        original_bytes,
        len(compressed_bytes),
        max_bytes,
    )
    return guarded_url
