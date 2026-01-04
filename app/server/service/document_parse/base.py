from __future__ import annotations

from typing import Any, Dict

import models

from sagents.tool.file_parser.file_parser import FileParser
from loguru import logger


class BaseParser:
    async def clear_old(self, index_name: str, doc: models.KdbDoc) -> None:
        logger.info(f"[Parser] clear_old: index_name={index_name}, doc_id={doc.id}")

    async def process(self, index_name: str, doc: models.KdbDoc) -> None:
        logger.info(f"[Parser] process: index_name={index_name}, doc_id={doc.id}")

    async def convert_file_to_text(
        self,
        file_path_or_url: str,
        start_index: int = 0,
        max_length: int = 500000,
        timeout: int = 60,
        enable_text_cleaning: bool = True,
        correct_dict: Dict[str, str] | None = None,
        is_remove_wrap: bool = False,
    ) -> tuple[str, Dict[str, Any]]:
        fp = FileParser()
        res = await fp.extract_text_from_file(
            file_path_or_url,
            start_index=start_index,
            max_length=max_length,
            timeout=timeout,
            enable_text_cleaning=enable_text_cleaning,
            correct_dict=correct_dict or {},
            is_remove_wrap=is_remove_wrap,
        )
        if not res.get("success"):
            raise Exception(res.get("error") or "文件解析失败")
        text = res.get("text") or ""
        return text, res.get("metadata") or {}
