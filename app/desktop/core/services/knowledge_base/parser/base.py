from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

from loguru import logger
from sagents.utils.file_parser import FileParser

from .... import models

if TYPE_CHECKING:
    from ..knowledge_base import DocumentInput


class BaseParser:
    async def clear_old(self, index_name: str, doc: models.KdbDoc) -> List[str]:
        """
        清理旧文档
        Returns:
            List[str]: 需要删除的文档ID列表
        """
        logger.info(f"[Parser] clear_old: index_name={index_name}, doc_id={doc.id}")
        return []

    async def process(self, index_name: str, doc: models.KdbDoc, file: models.File | None = None) -> List["DocumentInput"]:
        """
        处理文档
        Returns:
            List[DocumentInput]: 解析后的文档列表，由调用方负责插入
        """
        logger.info(f"[Parser] process: index_name={index_name}, doc_id={doc.id}")
        return []

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
