from __future__ import annotations

from re import A
from typing import Any, Dict

from loguru import logger
from sagents.tool.file_parser.file_parser import FileParser
from models.kdb_doc import KdbDoc


class BaseParser:
    async def clear_old(self, kdbId: str, doc: KdbDoc) -> None:
        logger.info(f"[Parser] clear_old: kdb={kdbId}, doc_id={doc.id}")

    async def process(self, kdbId: str, doc: KdbDoc) -> None:
        logger.info(f"[Parser] process: kdb={kdbId}, doc_id={doc.id}")

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
