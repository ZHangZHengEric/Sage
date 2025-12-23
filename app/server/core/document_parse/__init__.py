"""

当前实现为占位版本：仅完成注册与选择，不执行业务解析。
"""

from __future__ import annotations

from typing import Dict, Optional, Type

from .base import BaseParser
from .common_parser import CommonParser
from .eml_parser import EmlParser

_parsers: Dict[str, Type[BaseParser]] = {
    "file": CommonParser,
    "eml": EmlParser,
}


def get_document_parser(data_source: str) -> Optional[BaseParser]:
    cls = _parsers.get(data_source)
    return cls() if cls else None
