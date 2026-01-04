from __future__ import annotations

from typing import Dict, List

import models

from service.kb.knowledge_base import DocumentInput, DocumentService
from loguru import logger

from .base import BaseParser

ALLOW_ATTACH_FILE_EXTS = {
    ".doc",
    ".docx",
    ".pdf",
    ".txt",
    ".json",
    ".eml",
    ".ppt",
    ".pptx",
    ".xlsx",
    ".xls",
    ".csv",
    ".md",
}


class CommonParser(BaseParser):
    async def clear_old(self, index_name: str, doc: models.KdbDoc) -> None:
        ids: List[str] = [doc.id]
        md = doc.meta_data or {}
        atts = md.get("attachments")
        if isinstance(atts, list):
            ids.extend(atts)
        logger.info(
            f"[CommonParser] 清理旧文档开始：索引={index_name}，ID数量={len(ids)}"
        )
        await DocumentService().doc_document_delete(index_name, ids)
        logger.info(
            f"[CommonParser] 清理旧文档完成：索引={index_name}，已删除ID数量={len(ids)}"
        )

    async def process(self, index_name: str, doc: models.KdbDoc, file: models.File):
        file_dao = models.FileDao()
        logger.info(f"[CommonParser] 处理开始：索引={index_name}, 文档ID={doc.id}")
        text, _ = await self.convert_file_to_text(file.path)
        docs: List[DocumentInput] = []
        metadata: Dict = doc.meta_data or {}
        docs.append(
            DocumentInput(
                main_doc_id=doc.id,
                doc_id=doc.id,
                doc_content=text,
                origin_content=text,
                path=file.path,
                title=doc.doc_name or file.name,
                metadata=metadata,
            )
        )
        md = metadata
        attach_ids: List[str] = (
            md.get("attachments", []) if isinstance(md.get("attachments"), list) else []
        )
        if attach_ids:
            attach_map: Dict[str, models.File] = await file_dao.get_by_ids(attach_ids)
            logger.info(f"[CommonParser] 发现附件：数量={len(attach_map)}")
            for att in attach_map.values():
                if att.extension not in ALLOW_ATTACH_FILE_EXTS:
                    logger.debug(
                        f"[CommonParser] 附件跳过：id={att.id}，扩展名={att.extension}"
                    )
                    continue
                att_text, _ = await self.convert_file_to_text(att.path)
                docs.append(
                    DocumentInput(
                        main_doc_id=doc.id,
                        doc_id=att.id,
                        doc_content=att_text,
                        origin_content=att_text,
                        path=att.path,
                        title=att.name or att.origin_name,
                        metadata=metadata,
                    )
                )
        await DocumentService().doc_document_insert(index_name, docs)
        logger.info(
            f"[CommonParser] 处理完成：索引={index_name}，插入文档数={len(docs)}"
        )
