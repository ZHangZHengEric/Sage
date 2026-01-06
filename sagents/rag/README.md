# RAG (Retrieval-Augmented Generation) 模块

该模块实现了一个完整的 RAG 系统基础架构，支持文档切分、向量化、存储、检索以及结果重排序（RRF Fusion）等功能。设计上采用了分层架构和依赖注入，易于扩展和维护。

## 目录结构

```
sagents/rag/
├── interface/           # 接口定义 (ABC)
│   ├── embedding.py     # Embedding 模型抽象基类
│   ├── splitter.py      # 文档切分器抽象基类
│   └── vector_store.py  # 向量存储抽象基类
├── manager.py           # 核心管理类 (KnowledgeManager)，协调各个组件
├── post_process.py      # 检索结果后处理（RRF 融合排序、重叠合并）
├── schema.py            # 数据模型定义 (Document, Chunk, SearchResult)
├── splitter.py          # 文档切分默认实现 (DefaultSplitter)
└── text_splitter.py     # 具体的中/英文文本切分逻辑实现
```

## 核心组件

1.  **KnowledgeManager**: RAG 系统的控制中心，负责串联文档处理流程。
2.  **BaseSplitter (Interface) / DefaultSplitter**: 定义如何将长文档切分为小的 Chunk。
3.  **VectorStore (Interface)**: 向量数据库的抽象接口。你需要实现具体的子类。
4.  **EmbeddingModel (Interface)**: 文本向量化模型的抽象接口。你需要适配具体的模型服务。
5.  **SearchResultPostProcessTool**: 提供 RRF (Reciprocal Rank Fusion) 融合排序和重叠文本块合并功能。

## 使用方法

### 1. 实现基础组件

首先，你需要实现 `VectorStore` 和 `EmbeddingModel` 的具体子类。

```python
from typing import List
from sagents.rag.interface.vector_store import VectorStore
from sagents.rag.interface.embedding import EmbeddingModel
from sagents.rag.schema import Document, Chunk

class MyVectorStore(VectorStore):
    async def create_collection(self, collection_name: str):
        # 实现创建集合逻辑
        pass
        
    async def add_documents(self, collection_name: str, documents: List[Document]):
        # 实现文档入库逻辑
        pass
        
    async def search(self, collection_name: str, query: str, embedding: List[float], top_k: int = 5) -> List[Chunk]:
        # 实现向量检索逻辑
        return []
    
    # ... 实现其他抽象方法
    async def delete_documents(self, collection_name: str, document_ids: List[str]):
        pass

    async def clear_collection(self, collection_name: str):
        pass

    async def get_documents_by_ids(self, collection_name: str, document_ids: List[str]) -> List[Document]:
        pass

class MyEmbeddingModel(EmbeddingModel):
    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        # 调用 embedding API
        return [[0.1] * 768 for _ in texts]

    async def embed_query(self, text: str) -> List[float]:
        return [0.1] * 768
```

### 2. 初始化 KnowledgeManager

```python
import asyncio
from sagents.rag.manager import KnowledgeManager
from sagents.rag.splitter import DefaultSplitter

async def main():
    # 1. 初始化组件
    vector_store = MyVectorStore()
    embedding_model = MyEmbeddingModel()
    splitter = DefaultSplitter() # 可选，默认即为 DefaultSplitter

    # 2. 创建 Manager
    manager = KnowledgeManager(
        vector_store=vector_store,
        embedding_model=embedding_model,
        splitter=splitter
    )

    # 3. 添加文档
    doc = Document(
        id="doc_001",
        content="这是一个关于人工智能的文档。它包含了很多有趣的信息。",
        metadata={"author": "Sage"}
    )
    await manager.add_documents("my_collection", [doc])

    # 4. 执行检索
    results = await manager.search("my_collection", "人工智能", top_k=3)
    
    for chunk in results:
        print(f"Found: {chunk.content} (Score: {chunk.score})")

if __name__ == "__main__":
    asyncio.run(main())
```

### 3. 使用高级后处理 (RRF & Merge)

如果你有多个检索源（例如同时使用了向量检索和关键词检索），可以使用 `SearchResultPostProcessTool` 进行结果融合。

```python
from sagents.rag.post_process import SearchResultPostProcessTool
from sagents.rag.schema import SearchResult

# 假设你有两组检索结果
results_vector = [...] # List[SearchResult] from vector search
results_keyword = [...] # List[SearchResult] from keyword search

tool = SearchResultPostProcessTool()

# 1. RRF 融合排序
all_results = results_vector + results_keyword
fused_results = tool.rrf_fusion_for_search_chunks(all_results, rrf_k=60)

# 2. 合并重叠的 Chunk (可选，用于生成更连贯的上下文)
final_results = tool.merge_overlap_chunk(fused_results)
```

## 扩展性

*   **自定义切分器**: 继承 `BaseSplitter` 并实现 `split_text` 方法，然后在 `KnowledgeManager` 初始化时注入。
*   **更换向量库**: 只需实现新的 `VectorStore` 子类，无需修改业务逻辑。


## 具体实现
可以参照 app/server/service/knowledge_base 目录下的实现。