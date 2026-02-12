from __future__ import annotations

import csv
import io
import traceback
from typing import TYPE_CHECKING, List

import httpx
from loguru import logger
import openpyxl

from .... import models
from ....core import config
from ....utils.id import gen_id
from .base import BaseParser

if TYPE_CHECKING:
    from ..knowledge_base import DocumentInput


class QAParser(BaseParser):
    async def process(self, index_name: str, doc: models.KdbDoc, file: models.File) -> List["DocumentInput"]:
        # Lazy import to avoid circular dependency at runtime
        from ..knowledge_base import DocumentInput

        logger.info(f"[QAParser] 处理开始：索引={index_name}, 文档ID={doc.id}, 文件={file.name}")

        if not file.path:
            logger.error(f"[QAParser] 文件路径为空: {file.id}")
            return []

        # Download content
        content_bytes = b""
        try:
            file_path = file.path
            
            # 尝试解决 S3 内部访问问题
            cfg = config.get_startup_config()
            if cfg.s3_public_base_url and file_path.startswith(cfg.s3_public_base_url) and cfg.s3_endpoint and cfg.s3_bucket_name:
                # 提取对象名称
                object_name = file_path[len(cfg.s3_public_base_url):].lstrip("/")
                # 构建内部访问 URL
                scheme = "https" if cfg.s3_secure else "http"
                # 处理 s3_endpoint 可能包含 http 前缀的情况
                endpoint = cfg.s3_endpoint
                if endpoint.startswith("http://"):
                    endpoint = endpoint[7:]
                elif endpoint.startswith("https://"):
                    endpoint = endpoint[8:]
                    
                internal_url = f"{scheme}://{endpoint}/{cfg.s3_bucket_name}/{object_name}"
                logger.info(f"[QAParser] 转换 S3 URL: {file_path} -> {internal_url}")
                file_path = internal_url

            # Check if it looks like a URL
            if file_path.startswith("http://") or file_path.startswith("https://"):
                async with httpx.AsyncClient() as client:
                    resp = await client.get(file_path, timeout=60.0)
                    resp.raise_for_status()
                    content_bytes = resp.content
            else:
                # Assume local file path
                with open(file_path, "rb") as f:
                    content_bytes = f.read()
        except Exception as e:
            logger.error(f"[QAParser] 读取文件失败: {file.path}, error: {e}, trace: {traceback.format_exc()}")
            raise e

        # Parse content based on file extension
        rows = []
        filename = file.name.lower() if file.name else ""
        
        if filename.endswith(('.xlsx', '.xls')):
            try:
                # Load workbook from bytes
                wb = openpyxl.load_workbook(filename=io.BytesIO(content_bytes), read_only=True, data_only=True)
                ws = wb.active
                if ws:
                    for row in ws.iter_rows(values_only=True):
                        # Convert all cell values to string and filter out None
                        cleaned_row = [str(cell) if cell is not None else "" for cell in row]
                        # Skip empty rows
                        if any(cleaned_row):
                            rows.append(cleaned_row)
            except Exception as e:
                logger.error(f"[QAParser] Excel解析失败: {e}")
                return []
        else:
            # Default to CSV parsing
            try:
                # Attempt to decode as utf-8
                content_str = content_bytes.decode('utf-8')
                f_io = io.StringIO(content_str)
                reader = csv.reader(f_io)
                rows = list(reader)
            except UnicodeDecodeError:
                # Try gb18030 for Chinese support if utf-8 fails
                try:
                    content_str = content_bytes.decode('gb18030')
                    f_io = io.StringIO(content_str)
                    reader = csv.reader(f_io)
                    rows = list(reader)
                except Exception as e:
                    logger.error(f"[QAParser] CSV解码失败: {e}")
                    return []
            except Exception as e:
                logger.error(f"[QAParser] CSV解析失败: {e}")
                return []

        if not rows:
            logger.warning("[QAParser] 内容为空")
            return []

        doc_inputs: List[DocumentInput] = []
        metadata = doc.meta_data or {}
        
        count = 0
        for i, row in enumerate(rows):
            # Skip empty rows
            if not row:
                continue
            
            # Validate column count (loose check here, strict check in upload)
            if len(row) < 2:
                continue
            
            question = str(row[0]).strip()
            answer = str(row[1]).strip()
            
            if not question or not answer:
                continue
                
            # Construct content for embedding/search
            # Format: 
            # Question: ...
            # Answer: ...
            doc_content = f"Question: {question}\nAnswer: {answer}"
            
            item_meta = metadata.copy()
            item_meta.update({
                "question": question,
                "answer": answer,
                "row_index": i
            })
            
            doc_inputs.append(
                DocumentInput(
                    main_doc_id=doc.id,
                    doc_id=gen_id(),
                    doc_content=doc_content,
                    origin_content=doc_content,
                    path=file.path,
                    title=question[:100], # Use question as title
                    metadata=item_meta,
                )
            )
            count += 1

        logger.info(f"[QAParser] 处理完成：索引={index_name}，生成文档数={count}")
        return doc_inputs
