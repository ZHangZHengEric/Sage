from __future__ import annotations

from typing import List, Dict

from .base import BaseParser
from core.kdb_client import (
    DocumentInput,
    KnowledgeBaseClient,
)
from models.file import FileDao, File
from models.kdb_doc import KdbDoc
from utils.id import gen_id
from sagents.utils.logger import logger


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
    async def clear_old(self, kdbId: str, doc: KdbDoc) -> None:
        index_name = f"kdb_{kdbId}"
        ids: List[str] = [doc.id]
        md = doc.meta_data or {}
        atts = md.get("attachments")
        if isinstance(atts, list):
            ids.extend(atts)
        logger.info(
            f"[CommonParser] 清理旧文档开始：索引={index_name}，ID数量={len(ids)}"
        )
        await KnowledgeBaseClient().delete_documents_by_mcp(index_name, ids)
        logger.info(
            f"[CommonParser] 清理旧文档完成：索引={index_name}，已删除ID数量={len(ids)}"
        )

    async def process(self, kdbId: str, doc: KdbDoc, file: File):
        index_name = f"kdb_{kdbId}"
        file_dao = FileDao()
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
            attach_map: Dict[str, File] = await file_dao.get_by_ids(attach_ids)
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
        await KnowledgeBaseClient().insert_documents_by_mcp(index_name, docs)
        logger.info(
            f"[CommonParser] 处理完成：索引={index_name}，插入文档数={len(docs)}"
        )
