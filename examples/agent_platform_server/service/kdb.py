"""
KDB 领域服务，实现知识库与文档相关业务逻辑（异步）

去除 DTO，使用简单字段参数与字典结果以简化调用。
"""

from __future__ import annotations

from typing import List, Dict, Any, Tuple, Optional

from sagents.utils.logger import logger

from models.kdb import Kdb, KdbDao
from models.kdb_doc import KdbDoc, KdbDocDao, KdbDocStatus
from models.file import File, FileDao
from common.exceptions import SageHTTPException
from utils.id import gen_id
from fastapi import UploadFile
from core.minio_client import upload_kdb_file
from core.kdb_client import KnowledgeBaseClient, DocumentRetrieveOutput


class KdbService:
    def __init__(self):
        self.kdb_dao = KdbDao()
        self.kdb_doc_dao = KdbDocDao()
        self.file_dao = FileDao()

    async def add(
        self, name: str, type: str, intro: str = "", language: str = ""
    ) -> str:
        kdb_id = gen_id()
        obj = Kdb(
            id=kdb_id,
            name=name,
            intro=intro or "",
            setting={"kdbAttach": {"language": language or "zh-cn"}},
            data_type=type,
            user_id="",
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

    async def info(self, kdb_id: str) -> Optional[Kdb]:
        obj = await self.kdb_dao.get_by_id(kdb_id)
        return obj

    async def list(
        self,
        query_name: str = "",
        type: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Kdb], int]:
        items, total = await self.kdb_dao.get_list(
            kdb_ids=None,
            data_type=type,
            query_name=query_name,
            page=page,
            page_size=page_size,
        )
        return items, total

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
            [d.id for d in docs], KdbDocStatus.PENDING
        )
        logger.info(f"重做KDB所有文档: {kdb_id}")

    async def retrieve(
        self, kdb_id: str, query: str, top_k: int = 5
    ) -> List[DocumentRetrieveOutput]:
        kdb = await self.kdb_dao.get_by_id(kdb_id)
        if not kdb:
            raise SageHTTPException(status_code=400, detail="KDB not found")
        index_name = f"kdb_{kdb_id}"
        kdb_client = KnowledgeBaseClient()
        result = await kdb_client.search_documents_by_mcp(index_name, query, top_k)
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
    ) -> Tuple[List[KdbDoc], int]:
        docs, total = await self.kdb_doc_dao.get_list(
            kdb_id,
            query_name,
            query_status or [],
            task_id,
            page_no,
            page_size,
        )
        return docs, total

    async def doc_info(self, doc_id: str) -> Optional[KdbDoc]:
        d = await self.kdb_doc_dao.get_by_id(doc_id)
        return d

    async def doc_add_by_upload_files(
        self, kdb_id: str, files: List[UploadFile], override: bool = False
    ) -> str:
        kdb = await self.kdb_dao.get_by_id(kdb_id)
        if not kdb:
            raise SageHTTPException(status_code=400, detail="KDB not found")
        save_files: List[File] = []
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
        docs = await self.kdb_doc_dao.get_list(kdb_id, "", [], task_id, 1, 10000)
        doc_list = docs[0]
        total = len(doc_list)
        success = sum(1 for d in doc_list if d.status == KdbDocStatus.SUCCESS)
        fail = sum(1 for d in doc_list if d.status == KdbDocStatus.FAILED)
        in_progress = sum(1 for d in doc_list if d.status == KdbDocStatus.PROCESSING)
        waiting = sum(1 for d in doc_list if d.status == KdbDocStatus.PENDING)
        task_process = int((success / total) * 100) if total else 0
        return success, fail, in_progress, waiting, total, task_process

    async def task_redo(self, kdb_id: str, task_id: str) -> None:
        docs, _ = await self.kdb_doc_dao.get_list(kdb_id, "", [], task_id, 1, 10000)
        await self.kdb_doc_dao.batch_update_status(
            [d.id for d in docs], KdbDocStatus.PENDING
        )
        logger.info(f"任务重做: {task_id}")

    async def doc_delete(self, doc_id: str) -> None:
        kdb_client = KnowledgeBaseClient()
        await kdb_client.delete_documents_by_mcp(f"kdb_{kdb_id}", [doc_id])
        await self.kdb_doc_dao.delete_by_ids([doc_id])
        logger.info(f"删除doc: {doc_id}")

    async def doc_redo(self, doc_id: str) -> None:
        await self.kdb_doc_dao.batch_update_status([doc_id], KdbDocStatus.PENDING)
        logger.info(f"文档重做: {doc_id}")

    async def _add_doc_by_files(
        self, kdb: Kdb, files: List[File], attach_map: Dict[str, List[File]]
    ) -> str:
        task_id = gen_id()
        docs: List[KdbDoc] = []
        for f in files:
            ds = "file"
            if f.name.lower().endswith("eml"):
                ds = "eml"
            metadata: Dict[str, Any] = {}
            if attach_map:
                attaches = attach_map.get(f.name) or []
                if attaches:
                    metadata = {"attachments": [a.id for a in attaches]}
            d = KdbDoc(
                id=gen_id(),
                kdb_id=kdb.id,
                task_id=task_id,
                doc_name=f.name,
                data_source=ds,
                source_id=f.id,
                status=KdbDocStatus.PENDING,
                meta_data=metadata,
            )
            docs.append(d)
        await self.kdb_doc_dao.batch_insert(docs)
        logger.info(f"新增任务: {task_id}, 条数={len(files)}")
        return task_id

    async def _upload_by_upload_file(self, uf: UploadFile) -> File:
        import mimetypes

        data = await uf.read()
        content_type = (
            uf.content_type
            or mimetypes.guess_type(uf.filename)[0]
            or "application/octet-stream"
        )
        file_id = gen_id()
        path = await upload_kdb_file(uf.filename, data, content_type)
        f = File(
            id=file_id,
            name=uf.filename,
            path=path,
            size=len(data),
        )
        await self.file_dao.insert(f)
        return f
