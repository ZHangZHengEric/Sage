"""基于向量存储的用户记忆驱动实现示例

展示如何实现IMemoryDriver接口以接入Vector Store。
此实现利用sagents.retrieve_engine中的VectorStore接口，
支持语义搜索和持久化存储。

"""

import uuid
from typing import List, Optional, Any, Dict
from datetime import datetime
from sagents.utils.logger import logger
from ..interfaces import IMemoryDriver
from ..schemas import MemoryEntry, MemoryType
from sagents.retrieve_engine.interface.vector_store import VectorStore
from sagents.retrieve_engine.interface.embedding import EmbeddingModel
from sagents.retrieve_engine.schema import Document, Chunk

class VectorMemoryDriver(IMemoryDriver):
    """基于向量数据库的记忆驱动实现
    
    该驱动将记忆作为文档存储在向量数据库中，支持语义检索。
    """

    def __init__(self, vector_store: VectorStore, embedding_model: EmbeddingModel, collection_name: str = "user_memories"):
        """
        Args:
            vector_store: 向量存储实例
            embedding_model: Embedding模型实例
            collection_name: 集合名称
        """
        self.vector_store = vector_store
        self.embedding_model = embedding_model
        self.collection_name = collection_name
        self._available = True
        
        # 尝试初始化集合
        # 注意：这里应该是异步操作，但在__init__中无法await。
        # 实际使用时，应该有一个异步的 initialize 方法，或者由外部确保集合已创建。
        logger.info(f"VectorMemoryDriver initialized with collection: {collection_name}")

    def is_available(self) -> bool:
        return self._available

    async def remember(self, user_id: str, memory_key: str, content: str, memory_type: str, tags: str, session_id: Optional[str] = None, session_context: Optional[Any] = None) -> str:
        try:
            # 构造唯一文档ID
            doc_id = f"{user_id}_{memory_key}"
            
            # 处理标签
            tag_list = [t.strip() for t in tags.split(',') if t.strip()] if isinstance(tags, str) else tags
            
            # 构造元数据
            metadata = {
                "user_id": user_id,
                "memory_key": memory_key,
                "memory_type": memory_type,
                "tags": tag_list,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "session_id": session_id or ""
            }

            # 创建文档对象
            # 实际场景中，content可能需要通过TextSplitter切分，这里简化为单文档
            document = Document(
                id=doc_id,
                content=content,
                metadata=metadata
            )
            
            # 存入向量库
            # 假设 vector_store 实现会自动调用 embedding_model 生成向量，或者我们需要手动生成
            # 这里为了通用性，我们手动生成并赋值给 Chunk (如果 Document 结构支持预设 Chunk)
            # 这是一个简化示例，具体取决于 VectorStore 实现细节
            await self.vector_store.add_documents(self.collection_name, [document])
            
            return f"已记住: {memory_key}"

        except Exception as e:
            logger.error(f"VectorMemoryDriver remember failed: {e}")
            return f"记住记忆失败: {str(e)}"

    async def recall(self, user_id: str, query: str, limit: int, session_id: Optional[str] = None, session_context: Optional[Any] = None) -> List[MemoryEntry]:
        try:
            # 生成查询向量
            query_embedding = await self.embedding_model.embed_query(query)
            
            # 语义搜索
            # 为了过滤 user_id，我们需要获取更多的候选结果
            chunks = await self.vector_store.search(
                collection_name=self.collection_name,
                query=query,
                embedding=query_embedding,
                top_k=limit * 3 
            )
            
            memories = []
            for chunk in chunks:
                # 客户端过滤 user_id (如果 VectorStore 不支持元数据过滤)
                if chunk.metadata.get("user_id") != user_id:
                    continue
                    
                entry = self._chunk_to_memory_entry(chunk)
                if entry:
                    memories.append(entry)
                
                if len(memories) >= limit:
                    break
                    
            return memories

        except Exception as e:
            logger.error(f"VectorMemoryDriver recall failed: {e}")
            return []

    async def recall_by_type(self, user_id: str, memory_type: str, query: str, limit: int, session_id: Optional[str] = None, session_context: Optional[Any] = None) -> List[MemoryEntry]:
        try:
            # 如果没有 query，这可能是一个全量扫描或基于元数据的过滤
            # VectorStore 接口目前只定义了 search (基于向量)。
            # 如果 VectorStore 支持 metadata filtering，应该在这里使用。
            # 这里我们复用 recall 并进行内存过滤
            
            query_text = query if query else memory_type # 如果没有query，用类型名作为语义搜索的query
            
            memories = await self.recall(user_id, query_text, limit=limit * 5, session_id=session_id, session_context=session_context)
            
            filtered = []
            for m in memories:
                # 检查 memory_type 匹配
                # 注意：m.memory_type 是 Enum 或 str
                current_type = m.memory_type.value if hasattr(m.memory_type, 'value') else str(m.memory_type)
                if current_type == memory_type:
                    filtered.append(m)
                    
            return filtered[:limit]

        except Exception as e:
            logger.error(f"VectorMemoryDriver recall_by_type failed: {e}")
            return []

    async def forget(self, user_id: str, memory_key: str, session_id: Optional[str] = None, session_context: Optional[Any] = None) -> str:
        try:
            doc_id = f"{user_id}_{memory_key}"
            await self.vector_store.delete_documents(self.collection_name, [doc_id])
            return f"已忘记: {memory_key}"
        except Exception as e:
            logger.error(f"VectorMemoryDriver forget failed: {e}")
            return f"忘记记忆失败: {str(e)}"

    def _chunk_to_memory_entry(self, chunk: Chunk) -> Optional[MemoryEntry]:
        """将Chunk转换为MemoryEntry"""
        try:
            meta = chunk.metadata
            
            # 尝试转换 memory_type
            mem_type_str = meta.get("memory_type", "experience")
            try:
                mem_type = MemoryType(mem_type_str)
            except ValueError:
                mem_type = MemoryType.EXPERIENCE
                
            return MemoryEntry(
                key=meta.get("memory_key", chunk.id),
                content=chunk.content,
                memory_type=mem_type,
                created_at=datetime.fromisoformat(meta.get("created_at", datetime.now().isoformat())),
                updated_at=datetime.fromisoformat(meta.get("updated_at", datetime.now().isoformat())),
                tags=meta.get("tags", []),
                importance=meta.get("importance", 0.5)
            )
        except Exception as e:
            logger.warning(f"Failed to convert chunk to memory entry: {e}")
            return None
