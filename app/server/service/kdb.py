"""
KDB 领域服务，实现知识库与文档相关业务逻辑（异步）

去除 DTO，使用简单字段参数与字典结果以简化调用。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import models
from common.exceptions import SageHTTPException
from core.client.minio import upload_kdb_file
from core.kb.knowledge_base import DocumentService
from fastapi import UploadFile
from utils.id import gen_id

from sagents.utils.logger import logger


class KdbService:
    def __init__(self):
        self.kdb_dao = models.KdbDao()
        self.kdb_doc_dao = models.KdbDocDao()
        self.file_dao = models.FileDao()

    async def add(
        self,
        name: str,
        type: str,
        intro: str = "",
        language: str = "",
        user_id: str = "",
    ) -> str:
        kdb_id = gen_id()
        obj = models.Kdb(
            id=kdb_id,
            name=name,
            intro=intro or "",
            setting={"kdbAttach": {"language": language or "zh-cn"}},
            data_type=type,
            user_id=user_id or "",
        )
        await self.kdb_dao.insert(obj)
        logger.info(f"创建KDB: {kdb_id} - {name}")
        return kdb_id

    async def update(
        self,
        kdb_id: str,
        name: str = "",
        intro: str = "",
        kdb_setting: Dict[str, Any] | None = None,
    ) -> None:
        update_map: Dict[str, Any] = {}
        if name:
            update_map["name"] = name
        if intro:
            update_map["intro"] = intro
        if kdb_setting is not None:
            update_map["setting"] = kdb_setting
        if update_map:
            await self.kdb_dao.update_by_id(kdb_id, update_map)
            logger.info(f"更新KDB: {kdb_id}")

    async def info(self, kdb_id: str) -> Optional[models.Kdb]:
        obj = await self.kdb_dao.get_by_id(kdb_id)
        return obj

    async def list(
        self,
        query_name: str = "",
        type: str = "",
        page: int = 1,
        page_size: int = 20,
        user_id: Optional[str] = None,
    ) -> Tuple[List[models.Kdb], int, Dict[str, int]]:
        items, total = await self.kdb_dao.get_kdbs_paginated(
            kdb_ids=None,
            data_type=type,
            query_name=query_name,
            page=page,
            page_size=page_size,
            user_id=user_id,
        )
        counts = await self.kdb_doc_dao.get_counts_by_kdb_ids([k.id for k in items])
        return items, total, counts

    async def delete(self, kdb_id: str) -> None:
        await self.kdb_dao.delete_by_id(kdb_id)
        logger.info(f"删除KDB: {kdb_id}")

    async def clear(self, kdb_id: str) -> None:
        # 清空关联文档
        docs = await self.kdb_doc_dao.get_by_kdb_id(kdb_id)
        await self.kdb_doc_dao.delete_by_ids([d.id for d in docs])
        logger.info(f"清空KDB文档: {kdb_id}")

    async def redo_all(self, kdb_id: str) -> None:
        docs = await self.kdb_doc_dao.get_by_kdb_id(kdb_id)
        await self.kdb_doc_dao.batch_update_status(
            [d.id for d in docs], models.KdbDocStatus.PENDING
        )
        logger.info(f"重做KDB所有文档: {kdb_id}")

    async def retrieve(
        self, kdb_id: str, query: str, top_k: int = 5, user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        kdb = await self.kdb_dao.get_by_id(kdb_id)
        if not kdb:
            raise SageHTTPException(status_code=400, detail="KDB not found")
        if user_id and kdb.user_id and kdb.user_id != user_id:
            raise SageHTTPException(status_code=403, detail="forbidden")
        result = await DocumentService().doc_search(kdb.get_index_name(), query, top_k)
        return result

    # ==== 文档相关 ====
    async def doc_list(
        self,
        kdb_id: str,
        query_name: str = "",
        query_status: List[int] | None = None,
        task_id: str = "",
        page_no: int = 1,
        page_size: int = 20,
        user_id: Optional[str] = None,
    ) -> Tuple[List[models.KdbDoc], int]:
        if user_id:
            kdb = await self.kdb_dao.get_by_id(kdb_id)
            if not kdb:
                raise SageHTTPException(status_code=404, detail="KDB not found")
            if kdb.user_id and kdb.user_id != user_id:
                raise SageHTTPException(status_code=403, detail="forbidden")
        docs, total = await self.kdb_doc_dao.get_kdb_docs_paginated(
            kdb_id,
            query_name,
            query_status or [],
            task_id,
            page_no,
            page_size,
        )
        return docs, total

    async def doc_info(self, doc_id: str) -> Optional[models.KdbDoc]:
        d = await self.kdb_doc_dao.get_by_id(doc_id)
        return d

    async def doc_add_by_upload_files(
        self,
        kdb_id: str,
        files: List[UploadFile],
        override: bool = False,
        user_id: Optional[str] = None,
    ) -> str:
        kdb = await self.kdb_dao.get_by_id(kdb_id)
        if not kdb:
            raise SageHTTPException(status_code=400, detail="KDB not found")
        if user_id and kdb.user_id and kdb.user_id != user_id:
            raise SageHTTPException(status_code=403, detail="forbidden")
        save_files: List[models.File] = []
        for uf in files or []:
            if not uf or not uf.filename:
                continue
            f = await self._upload_by_upload_file(uf)
            save_files.append(f)
        task_id = await self._add_doc_by_files(kdb, save_files, {})
        return task_id

    async def task_process(
        self, kdb_id: str, task_id: str
    ) -> Tuple[int, int, int, int, int, int]:
        docs = await self.kdb_doc_dao.get_kdb_docs_paginated(
            kdb_id, "", [], task_id, 1, 10000
        )
        doc_list = docs[0]
        total = len(doc_list)
        success = sum(1 for d in doc_list if d.status == models.KdbDocStatus.SUCCESS)
        fail = sum(1 for d in doc_list if d.status == models.KdbDocStatus.FAILED)
        in_progress = sum(1 for d in doc_list if d.status == models.KdbDocStatus.PROCESSING)
        waiting = sum(1 for d in doc_list if d.status == models.KdbDocStatus.PENDING)
        task_process = int((success / total) * 100) if total else 0
        return success, fail, in_progress, waiting, total, task_process

    async def task_redo(self, kdb_id: str, task_id: str) -> None:
        docs, _ = await self.kdb_doc_dao.get_kdb_docs_paginated(
            kdb_id, "", [], task_id, 1, 10000
        )
        await self.kdb_doc_dao.batch_update_status(
            [d.id for d in docs], models.KdbDocStatus.PENDING
        )
        logger.info(f"任务重做: {task_id}")

    async def doc_delete(self, doc_id: str) -> None:
        kdb_doc = await self.kdb_doc_dao.get_by_id(doc_id)
        if not kdb_doc:
            raise SageHTTPException(status_code=400, detail="KDB Doc not found")
        kdb = await self.kdb_dao.get_by_id(kdb_doc.kdb_id)
        if not kdb:
            raise SageHTTPException(status_code=400, detail="KDB not found")
        await DocumentService().doc_document_delete(kdb.get_index_name(), [doc_id])
        await self.kdb_doc_dao.delete_by_ids([doc_id])
        logger.info(f"删除doc: {doc_id}")

    async def doc_redo(self, doc_id: str) -> None:
        await self.kdb_doc_dao.batch_update_status([doc_id], models.KdbDocStatus.PENDING)
        logger.info(f"文档重做: {doc_id}")

    async def _add_doc_by_files(
        self, kdb: models.Kdb, files: List[models.File], attach_map: Dict[str, List[models.File]]
    ) -> str:
        task_id = gen_id()
        docs: List[models.KdbDoc] = []
        for f in files:
            ds = "file"
            if f.name.lower().endswith("eml"):
                ds = "eml"
            metadata: Dict[str, Any] = {}
            if attach_map:
                attaches = attach_map.get(f.name) or []
                if attaches:
                    metadata = {"attachments": [a.id for a in attaches]}
            d = models.KdbDoc(
                id=gen_id(),
                kdb_id=kdb.id,
                task_id=task_id,
                doc_name=f.name,
                data_source=ds,
                source_id=f.id,
                status=models.KdbDocStatus.PENDING,
                meta_data=metadata,
            )
            docs.append(d)
        await self.kdb_doc_dao.batch_insert(docs)
        logger.info(f"新增任务: {task_id}, 条数={len(files)}")
        return task_id

    async def _upload_by_upload_file(self, uf: UploadFile) -> models.File:
        import mimetypes

        data = await uf.read()
        content_type = (
            uf.content_type
            or mimetypes.guess_type(uf.filename)[0]
            or "application/octet-stream"
        )
        file_id = gen_id()
        path = await upload_kdb_file(uf.filename, data, content_type)
        f = models.File(
            id=file_id,
            name=uf.filename,
            path=path,
            size=len(data),
        )
        await self.file_dao.insert(f)
        return f
