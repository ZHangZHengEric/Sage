from __future__ import annotations


import os
from typing import List, Dict, Any

from .base import BaseParser
from models.file import FileDao, File
from utils.id import gen_id
from models.kdb_doc import KdbDocDao, KdbDoc
from loguru import logger
from core.kdb_client import (
    DocumentInput,
    KnowledgeBaseClient,
)
from core.minio_client import upload_kdb_file


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


class EmlParser(BaseParser):

    async def clear_old(self, kdbId: str, doc: KdbDoc) -> None:
        index_name = f"kdb_{kdbId}"
        ids: List[str] = [doc.id]
        md = doc.meta_data or {}
        atts = md.get("attachments")
        if isinstance(atts, list):
            ids.extend(atts)
        logger.info(f"[EmlParser] 清理旧文档开始：索引={index_name}，ID数量={len(ids)}")
        await KnowledgeBaseClient().delete_documents_by_mcp(index_name, ids)
        logger.info(
            f"[EmlParser] 清理旧文档完成：索引={index_name}，已删除ID数量={len(ids)}"
        )

    async def process(self, kdbId: str, doc: KdbDoc, file: File):
        index_name = f"kdb_{kdbId}"
        file_dao = FileDao()
        logger.info(f"[CommonParser] 处理开始：索引={index_name}, 文档ID={doc.id}")
        text, meta = await self.convert_file_to_text(file.path)
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
        files_to_save: List[File] = []
        attach_meta: Any = meta.get("attachments")
        meta_files: List[Dict[str, Any]] = []
        if isinstance(attach_meta, dict):
            meta_files = attach_meta.get("files") or []
        elif isinstance(attach_meta, list):
            meta_files = attach_meta

        if meta_files:
            logger.info(f"[EmlParser] 发现附件：数量={len(meta_files)}")
            for item in meta_files:
                try:
                    fname = item.get("file_name")
                    ctype = item.get("content_type")
                    att_text = item.get("file_content")
                    data_bytes: bytes = b""
                    if isinstance(att_text, str) and att_text:
                        data_bytes = att_text.encode("utf-8")

                    if not data_bytes:
                        logger.debug(f"[EmlParser] 附件跳过：名称={fname}，原因=无内容")
                        continue
                    ext = os.path.splitext(fname)[1].lower()
                    if ext not in ALLOW_ATTACH_FILE_EXTS:
                        logger.debug(
                            f"[EmlParser] 附件跳过：名称={fname}，原因=不支持的文件类型"
                        )
                        continue
                    path = await upload_kdb_file(fname, data_bytes, ctype)
                    att = File(
                        id=gen_id(),
                        name=fname,
                        path=path,
                        size=len(data_bytes),
                    )
                    files_to_save.append(att)
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
                except Exception as e:
                    logger.debug(
                        f"[EmlParser] 附件上传失败：名称={item.get('file_name') or item.get('fileName')}, 错误={e}"
                    )

        if files_to_save:
            await file_dao.batch_insert(files_to_save)
            doc.meta_data["attachments"] = [f.id for f in files_to_save]
        else:
            doc.meta_data["attachments"] = []
        doc_dao = KdbDocDao()
        await doc_dao.update(doc)
        await KnowledgeBaseClient().insert_documents_by_mcp(index_name, docs)
        logger.info(f"[EmlParser] 处理完成：索引={index_name}，插入文档数={len(docs)}")
