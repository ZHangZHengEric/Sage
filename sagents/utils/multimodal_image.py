"""
多模态图片处理工具：将消息 content 中的本地/远端 image_url 统一压缩并转 base64。

从 AgentBase 抽取，便于复用与单测。所有函数无状态，依赖只有 PIL 与项目内 logger。
"""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse

from PIL import Image

from sagents.utils.logger import logger


_MIME_TYPES: Dict[str, str] = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.bmp': 'image/bmp',
    '.svg': 'image/svg+xml',
}

# 压缩到的最大边长（保持比例）
_MAX_IMAGE_EDGE = 512
# JPEG 质量
_JPEG_QUALITY = 85


def get_mime_type(file_extension: str) -> str:
    """根据文件扩展名获取 MIME 类型，未知类型回落到 image/jpeg。"""
    return _MIME_TYPES.get(file_extension, 'image/jpeg')


def resolve_local_sage_url(url: str) -> Optional[str]:
    """把桌面端 sidecar 的本地 sage 文件 URL 反解为本地文件路径。

    desktop 端图片 URL 形如 ``http://127.0.0.1:<port>/api/oss/file/<agent_id>/<filename>``，
    远程 LLM 访问不到 localhost，因此映射回 ``~/.sage/agents/<agent_id>/upload_files/<filename>``，
    交由调用方走"本地图片 → base64"分支。
    若不是本地 sage 文件 URL，返回 None。
    """
    try:
        parsed = urlparse(url)
        if parsed.hostname not in ("127.0.0.1", "localhost", "0.0.0.0"):
            return None

        path = unquote(parsed.path or "")
        prefix = "/api/oss/file/"
        if not path.startswith(prefix):
            return None
        rest = path[len(prefix):]
        parts = rest.split("/", 1)
        if len(parts) != 2:
            return None
        agent_id, filename = parts[0], parts[1]
        if not agent_id or not filename or "/" in filename or "\\" in filename:
            return None

        user_home = Path.home()
        if agent_id == "_default":
            base_dir = user_home / ".sage" / "files"
        else:
            base_dir = user_home / ".sage" / "agents" / agent_id / "upload_files"
        file_path = (base_dir / filename).resolve()
        try:
            file_path.relative_to(base_dir.resolve())
        except ValueError:
            return None
        if not file_path.exists() or not file_path.is_file():
            return None
        return str(file_path)
    except Exception as exc:
        logger.warning(f"Failed to resolve local sage url: {url}, error: {exc}")
        return None


def _compress_image_to_jpeg_bytes(img: Image.Image) -> bytes:
    """RGB 化、缩放至最大边长、保存为 JPEG bytes。"""
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')
    img.thumbnail((_MAX_IMAGE_EDGE, _MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    img.save(output, format='JPEG', quality=_JPEG_QUALITY)
    return output.getvalue()


def _compress_base64_data_url(data_url: str) -> Optional[str]:
    """对已是 base64 的 data URL 解码、压缩、再编码，失败返回 None。"""
    try:
        _, base64_str = data_url.split(',', 1)
        raw = base64.b64decode(base64_str)
        with Image.open(io.BytesIO(raw)) as img:
            compressed = _compress_image_to_jpeg_bytes(img)
        encoded = base64.b64encode(compressed).decode('utf-8')
        logger.debug(f"Compressed base64 image from {len(raw)} to {len(compressed)} bytes")
        return f"data:image/jpeg;base64,{encoded}"
    except Exception as exc:
        logger.error(f"Failed to compress base64 image: {exc}")
        return None


def _file_to_base64_data_url(file_path: Path) -> Optional[str]:
    """把本地图片文件压缩并编码为 data URL。"""
    try:
        with Image.open(file_path) as img:
            compressed = _compress_image_to_jpeg_bytes(img)
        encoded = base64.b64encode(compressed).decode('utf-8')
        logger.debug(
            f"Converted and compressed local image to base64: {file_path}, size: {len(compressed)} bytes"
        )
        return f"data:image/jpeg;base64,{encoded}"
    except Exception as exc:
        logger.error(f"Failed to convert image to base64: {file_path}, error: {exc}")
        return None


async def process_multimodal_content(msg: Dict[str, Any]) -> Dict[str, Any]:
    """处理多模态消息内容，将本地图片路径转换为 base64，远程 URL 保持不变。

    - ``data:image/...`` 已是 base64 → 解码后压缩重编码；
    - ``file://`` 与裸路径 → 读本地文件压缩后编码；
    - ``http(s)://127.0.0.1...`` 桌面端 sidecar URL → 反解为本地路径再走本地分支；
    - 其他 ``http(s)://`` → 视为远端，原样保留。

    无 list content 的消息原样返回。
    """
    content = msg.get('content')
    if not isinstance(content, list):
        return msg

    new_content = []
    for item in content:
        if not isinstance(item, dict):
            new_content.append(item)
            continue

        item_type = item.get('type')
        if item_type == 'text':
            new_content.append(item)
            continue
        if item_type != 'image_url':
            new_content.append(item)
            continue

        image_url_data = item.get('image_url', {})
        url = image_url_data.get('url', '') if isinstance(image_url_data, dict) else str(image_url_data)
        if not url:
            new_content.append(item)
            continue

        # 已是 base64 data URL：解码-压缩-编码
        if url.startswith('data:image/'):
            compressed = _compress_base64_data_url(url)
            if compressed is None:
                new_content.append(item)
            else:
                new_content.append({'type': 'image_url', 'image_url': {'url': compressed}})
            continue

        # 解析为本地路径
        if url.startswith('file://'):
            file_path_str = url[7:]
        elif url.startswith('http://') or url.startswith('https://'):
            local_path = resolve_local_sage_url(url)
            if local_path is None:
                # 真正的远端 URL 原样保留
                new_content.append(item)
                continue
            file_path_str = local_path
        else:
            file_path_str = url

        path_obj = Path(file_path_str)
        if not path_obj.exists():
            logger.warning(f"Image file not found: {file_path_str}")
            new_content.append(item)
            continue

        data_url = _file_to_base64_data_url(path_obj)
        if data_url is None:
            new_content.append(item)
        else:
            new_content.append({'type': 'image_url', 'image_url': {'url': data_url}})

    msg['content'] = new_content
    return msg
