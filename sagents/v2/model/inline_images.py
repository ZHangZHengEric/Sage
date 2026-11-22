"""Reuse cheap facts about immutable inline images while a Run is active."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import re
from weakref import ReferenceType, ref

from sagents.v2.contracts.items import ImageBlock

_CHUNK_CHARACTERS = 64 * 1024
_JSON_LITERAL_IMAGE = re.compile(r"data:image/[a-zA-Z0-9.+-]+;base64,[a-zA-Z0-9+/=]+")


@dataclass(slots=True)
class _InlineImage:
    block: ReferenceType[ImageBlock]
    digest: bytes
    json_literal: bool
    fits: tuple[int, int, int | None] | None = None


_images: ContextVar[dict[int, _InlineImage] | None] = ContextVar("inline_images", default=None)


@contextmanager
def reuse_inline_image_checks():
    images = {}
    token = _images.set(images)
    try:
        yield
    finally:
        images.clear()
        _images.reset(token)


def is_large_inline_image(block: ImageBlock) -> bool:
    return len(block.uri) >= _CHUNK_CHARACTERS and block.uri.startswith("data:")


def _cached_image(uri: str) -> _InlineImage | None:
    images = _images.get()
    entry = images.get(id(uri)) if images is not None else None
    block = entry.block() if entry is not None else None
    return entry if block is not None and block.uri is uri else None


def image_uri_digest(block: ImageBlock) -> bytes:
    uri = block.uri
    entry = _cached_image(uri)
    if entry is not None:
        return entry.digest
    hasher = hashlib.sha256()
    for index in range(0, len(uri), _CHUNK_CHARACTERS):
        hasher.update(uri[index:index + _CHUNK_CHARACTERS].encode())
    digest = hasher.digest()
    images = _images.get()
    if images is not None:
        if len(images) >= 32:
            images.pop(next(iter(images)))
        images[id(uri)] = _InlineImage(ref(block), digest, _JSON_LITERAL_IMAGE.fullmatch(uri) is not None)
    return digest


def inline_image_fits(uri: str, bounds: tuple[int, int, int | None]) -> bool:
    entry = _cached_image(uri)
    return entry is not None and entry.fits == bounds


def inline_image_json_characters(uri: str) -> int:
    entry = _cached_image(uri)
    # ASCII Base64 and this media header are emitted verbatim by the JSON serializer.
    return len(uri) if entry is not None and entry.json_literal else 0


def remember_inline_image_fit(uri: str, bounds: tuple[int, int, int | None]) -> None:
    entry = _cached_image(uri)
    if entry is not None:
        entry.fits = bounds
