"""
Search 领域服务（异步），对齐 Kdb 直搜接口（去除 DTO，使用字段传参）
"""

from __future__ import annotations

from typing import Dict, Any
from loguru import logger


from typing import List


class SearchService:
    async def kdb_search(
        self, kdb_id: str, question: str = "", query_size: int = 20
    ) -> List[Any]:
        # TODO: 预留ES集成，目前返回空集合以保持API契约
        logger.info(f"KDB直搜: kdbId={kdb_id}, question={question}, size={query_size}")
        return []
