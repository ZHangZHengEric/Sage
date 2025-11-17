"""
后台任务服务：定期处理知识库文档（基础版）

"""

from __future__ import annotations

from typing import List
from sagents.utils.logger import logger
from models.kdb_doc import KdbDoc, KdbDocDao, KdbDocStatus
from models.kdb import KdbDao
from models.file import FileDao
from core.document_parse import get_document_parser


DEFAULT_BATCH_SIZE = 5


class JobService:
    def __init__(self):
        self.kdb_doc_dao = KdbDocDao()
        self.kdb_dao = KdbDao()
        self.file_dao = FileDao()

    async def build_waiting_doc(self):
        docs: List[KdbDoc] = await self.kdb_doc_dao.get_list_by_status_and_data_source(
            KdbDocStatus.PENDING, "file", DEFAULT_BATCH_SIZE
        )
        if not docs:
            return
        logger.info(f"开始 处理等待文档, 文档数量: {len(docs)}")
        for d in docs:
            await self._process_document(d)
        logger.info(f"完成 处理等待文档, 文档数量: {len(docs)}")

    async def build_failed_doc(self):
        docs: List[KdbDoc] = await self.kdb_doc_dao.get_failed_list(
            "file", DEFAULT_BATCH_SIZE
        )
        if not docs:
            return
        logger.info(f"开始 重新处理失败文档, 文档数量: {len(docs)}")
        for d in docs:
            await self._process_document(d)
        logger.info(f"完成 重新处理失败文档, 文档数量: {len(docs)}")

    async def _process_document(self, doc: KdbDoc):
        await self.kdb_doc_dao.update_status(doc.id, KdbDocStatus.PROCESSING)
        try:
            # 1. 判断知识库是否存在
            kdb = await self.kdb_dao.get_by_id(doc.kdb_id)
            if not kdb:
                await self.kdb_doc_dao.update_status_and_retry(
                    doc.id, KdbDocStatus.FAILED
                )
                logger.error(f"知识库不存在 - KdbId: {doc.kdb_id}")
                return
            # 2. 判断文件是否存在
            file = await self.file_dao.get_by_id(doc.source_id)
            if not file:
                await self.kdb_doc_dao.update_status_and_retry(
                    doc.id, KdbDocStatus.FAILED
                )
                logger.error(f"文件不存在 - FileId: {doc.source_id}")
                return
            parser = get_document_parser(doc.data_source)
            if parser is None:
                await self.kdb_doc_dao.update_status_and_retry(
                    doc.id, KdbDocStatus.FAILED
                )
                logger.error(f"不支持的文档类型: {doc.data_source}")
                return
            await parser.clear_old(kdb.get_index_name(), doc)
            # 3. 调用文档解析器处理文档
            await parser.process(kdb.get_index_name(), doc, file)
            # 调用知识库入库接口，
            await self.kdb_doc_dao.update_status(doc.id, KdbDocStatus.SUCCESS)
            logger.info(f"处理文档成功 - DocId: {doc.id}, docName: {doc.doc_name}")
        except Exception as e:
            await self.kdb_doc_dao.update_status_and_retry(doc.id, KdbDocStatus.FAILED)
            logger.error(
                f"处理文档失败 - DocId: {doc.id}, docName: {doc.doc_name}, err={e}"
            )
