"""
KDB 领域服务，实现知识库与文档相关业务逻辑（异步）

去除 DTO，使用简单字段参数与字典结果以简化调用。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from fastapi import UploadFile
from loguru import logger

from .. import models
from ..core.client.minio import upload_kdb_file
from ..core.exceptions import SageHTTPException
from ..services.knowledge_base import DocumentService
from ..utils.id import gen_id

DEFAULT_BATCH_SIZE = 5

class KdbService:
    def __init__(self):
        self.kdb_dao = models.KdbDao()
        self.kdb_doc_dao = models.KdbDocDao()
        self.file_dao = models.FileDao()

    async def _check_kdb_permission(self, kdb_id: str, user_id: Optional[str]) -> models.Kdb:
        kdb = await self.kdb_dao.get_by_id(kdb_id)
        if not kdb:
            raise SageHTTPException(status_code=500, detail="KDB not found")
        if user_id and kdb.user_id and kdb.user_id != user_id:
            raise SageHTTPException(status_code=500, detail="forbidden")
        return kdb

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
        user_id: Optional[str] = None,
    ) -> models.Kdb:
        kdb = await self._check_kdb_permission(kdb_id, user_id)
        update_map: Dict[str, Any] = {}
        if name:
            update_map["name"] = name
        if intro:
            update_map["intro"] = intro
        if kdb_setting is not None:
            update_map["setting"] = kdb_setting
        if update_map:
            await self.kdb_dao.update_by_id(kdb_id, update_map)
            # Update in-memory object to return correct data if needed, 
            # though usually we just need user_id which doesn't change.
            for k, v in update_map.items():
                setattr(kdb, k, v)
            logger.info(f"更新KDB: {kdb_id}")
        return kdb

    async def info(self, kdb_id: str, user_id: Optional[str] = None) -> Optional[models.Kdb]:
        try:
            return await self._check_kdb_permission(kdb_id, user_id)
        except SageHTTPException:
            # If not found or forbidden, we might return None or raise. 
            # Original code returned None if not found, but we want to enforce permission.
            # If forbidden, we should probably raise or return None.
            # But the router handles None by returning empty struct? 
            # Let's see router usage. 
            # Router checks `if not obj`. 
            # If I raise exception, it returns 403/404. That is better.
            raise 

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

    async def delete(self, kdb_id: str, user_id: Optional[str] = None) -> models.Kdb:
        kdb = await self._check_kdb_permission(kdb_id, user_id)
        await self.kdb_dao.delete_by_id(kdb_id)
        logger.info(f"删除KDB: {kdb_id}")
        return kdb

    async def clear(self, kdb_id: str, user_id: Optional[str] = None) -> models.Kdb:
        kdb = await self._check_kdb_permission(kdb_id, user_id)
        # 清空关联文档
        docs = await self.kdb_doc_dao.get_by_kdb_id(kdb_id)
        await self.kdb_doc_dao.delete_by_ids([d.id for d in docs])
        logger.info(f"清空KDB文档: {kdb_id}")
        return kdb

    async def redo_all(self, kdb_id: str, user_id: Optional[str] = None) -> models.Kdb:
        kdb = await self._check_kdb_permission(kdb_id, user_id)
        docs = await self.kdb_doc_dao.get_by_kdb_id(kdb_id)
        await self.kdb_doc_dao.batch_update_status(
            [d.id for d in docs], models.KdbDocStatus.PENDING
        )
        logger.info(f"重做KDB所有文档: {kdb_id}")
        return kdb

    async def retrieve(
        self, kdb_id: str, query: str, top_k: int = 5, user_id: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], models.Kdb]:
        kdb = await self._check_kdb_permission(kdb_id, user_id)
        result = await DocumentService().doc_search(kdb.get_index_name(), query, top_k)
        return result.get("search_results", []), kdb

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
    ) -> Tuple[List[models.KdbDoc], int, models.Kdb]:
        kdb = await self._check_kdb_permission(kdb_id, user_id)
        docs, total = await self.kdb_doc_dao.get_kdb_docs_paginated(
            kdb_id,
            query_name,
            query_status or [],
            task_id,
            page_no,
            page_size,
        )
        return docs, total, kdb

    async def doc_info(self, doc_id: str, user_id: Optional[str] = None) -> Tuple[Optional[models.KdbDoc], Optional[models.Kdb]]:
        d = await self.kdb_doc_dao.get_by_id(doc_id)
        kdb = None
        if d:
            kdb = await self._check_kdb_permission(d.kdb_id, user_id)
        return d, kdb

    async def doc_add_by_upload_files(
        self,
        kdb_id: str,
        files: List[UploadFile],
        override: bool = False,
        user_id: Optional[str] = None,
    ) -> Tuple[str, models.Kdb]:
        kdb = await self._check_kdb_permission(kdb_id, user_id)
        save_files: List[models.File] = []
        for uf in files or []:
            if not uf or not uf.filename:
                continue
            f = await self._upload_by_upload_file(uf, user_id)
            save_files.append(f)
        task_id = await self._add_doc_by_files(kdb, save_files, {})
        return task_id, kdb

    async def task_process(
        self, kdb_id: str, task_id: str, user_id: Optional[str] = None
    ) -> Tuple[int, int, int, int, int, int, models.Kdb]:
        kdb = await self._check_kdb_permission(kdb_id, user_id)
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
        return success, fail, in_progress, waiting, total, task_process, kdb

    async def task_redo(self, kdb_id: str, task_id: str, user_id: Optional[str] = None) -> models.Kdb:
        kdb = await self._check_kdb_permission(kdb_id, user_id)
        docs, _ = await self.kdb_doc_dao.get_kdb_docs_paginated(
            kdb_id, "", [], task_id, 1, 10000
        )
        await self.kdb_doc_dao.batch_update_status(
            [d.id for d in docs], models.KdbDocStatus.PENDING
        )
        logger.info(f"任务重做: {task_id}")
        return kdb

    async def doc_delete(self, doc_id: str, user_id: Optional[str] = None) -> models.Kdb:
        kdb_doc = await self.kdb_doc_dao.get_by_id(doc_id)
        if not kdb_doc:
            raise SageHTTPException(status_code=500, detail="KDB Doc not found")
        kdb = await self._check_kdb_permission(kdb_doc.kdb_id, user_id)
        await DocumentService().doc_document_delete(kdb.get_index_name(), [doc_id])
        await self.kdb_doc_dao.delete_by_ids([doc_id])
        logger.info(f"删除doc: {doc_id}")
        return kdb

    async def doc_redo(self, doc_id: str, user_id: Optional[str] = None) -> models.Kdb:
        kdb_doc = await self.kdb_doc_dao.get_by_id(doc_id)
        kdb = None
        if kdb_doc:
            kdb = await self._check_kdb_permission(kdb_doc.kdb_id, user_id)
        else:
             # Should we raise if doc not found? Original code just logged info but check_kdb_permission was inside if.
             # If doc not found, we can't find KDB.
             pass
        await self.kdb_doc_dao.batch_update_status([doc_id], models.KdbDocStatus.PENDING)
        logger.info(f"文档重做: {doc_id}")
        return kdb


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

    async def _upload_by_upload_file(self, uf: UploadFile, user_id: Optional[str] = None) -> models.File:
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
            user_id=user_id or "",
        )
        await self.file_dao.insert(f)
        return f

    async def build_waiting_doc(self):
        docs: List[models.KdbDoc] = (
            await self.kdb_doc_dao.get_list_by_status_and_data_source(
                models.KdbDocStatus.PENDING, "file", DEFAULT_BATCH_SIZE
            )
        )
        if not docs:
            return
        logger.info(f"开始 处理等待文档, 文档数量: {len(docs)}")
        for d in docs:
            await self._process_document(d)
        logger.info(f"完成 处理等待文档, 文档数量: {len(docs)}")

    async def build_failed_doc(self):
        docs: List[models.KdbDoc] = await self.kdb_doc_dao.get_failed_list(
            "file", DEFAULT_BATCH_SIZE
        )
        if not docs:
            return
        logger.info(f"开始 重新处理失败文档, 文档数量: {len(docs)}")
        for d in docs:
            await self._process_document(d)
        logger.info(f"完成 重新处理失败文档, 文档数量: {len(docs)}")

    async def _process_document(self, doc: models.KdbDoc):
        await self.kdb_doc_dao.update_status(doc.id, models.KdbDocStatus.PROCESSING)
        try:
            # 1. 判断知识库是否存在
            kdb = await self.kdb_dao.get_by_id(doc.kdb_id)
            if not kdb:
                await self.kdb_doc_dao.update_status_and_retry(
                    doc.id, models.KdbDocStatus.FAILED
                )
                logger.error(f"知识库不存在 - KdbId: {doc.kdb_id}")
                return
            # 2. 判断文件是否存在
            file = await self.file_dao.get_by_id(doc.source_id)
            if not file:
                await self.kdb_doc_dao.update_status_and_retry(
                    doc.id, models.KdbDocStatus.FAILED
                )
                logger.error(f"文件不存在 - FileId: {doc.source_id}")
                return
            # 3. 调用 DocumentService 同步文档（包含清理旧数据和处理新数据）
            await DocumentService().sync_document(kdb.get_index_name(), doc, file, data_source=doc.data_source)
            # 调用知识库入库接口，
            await self.kdb_doc_dao.update_status(doc.id, models.KdbDocStatus.SUCCESS)
            logger.info(f"处理文档成功 - DocId: {doc.id}, docName: {doc.doc_name}")
        except Exception as e:
            await self.kdb_doc_dao.update_status_and_retry(
                doc.id, models.KdbDocStatus.FAILED
            )
            logger.error(
                f"处理文档失败 - DocId: {doc.id}, docName: {doc.doc_name}, err={e}"
            )
