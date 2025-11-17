from typing import Any, Dict, Optional, List
from elasticsearch import AsyncElasticsearch, helpers
from config.settings import StartupConfig
from core.client.llm import EMBEDDING_DIMS
from sagents.utils.logger import logger

ES_CLIENT: Optional[AsyncElasticsearch] = None


def get_es_client() -> AsyncElasticsearch:
    global ES_CLIENT
    if ES_CLIENT is None:
        raise RuntimeError("ES 客户端未初始化，请先调用 init_es_client()")
    return ES_CLIENT


async def init_es_client(cfg: StartupConfig | None = None) -> AsyncElasticsearch:
    global ES_CLIENT
    if ES_CLIENT is not None:
        return ES_CLIENT
    if cfg is None:
        raise RuntimeError("StartupConfig is required to initialize ES client")
    base = cfg.es_url
    api_key = cfg.es_api_key
    username = cfg.es_username
    password = cfg.es_password
    if not base:
        logger.warning(
            f"Elasticsearch 参数不足，未初始化 base={base}, api_key={api_key}, username={username}, password={password}"
        )
        return None
    if api_key:
        ES_CLIENT = AsyncElasticsearch(base, api_key=api_key)
    elif username and password:
        ES_CLIENT = AsyncElasticsearch(base, basic_auth=(username, password))
    else:
        ES_CLIENT = AsyncElasticsearch(base)
    return ES_CLIENT


async def close_es_client() -> None:
    global ES_CLIENT
    try:
        if ES_CLIENT is not None:
            await ES_CLIENT.close()
    finally:
        ES_CLIENT = None


def dims() -> int:
    return EMBEDDING_DIMS


async def _index_exists(client: AsyncElasticsearch, index_name: str) -> bool:
    try:
        return await client.indices.exists(index=index_name, ignore=[404, 400])
    except Exception:
        return False


def _common_settings() -> Dict[str, Any]:
    return {
        "similarity": {"my_similarity": {"type": "BM25", "b": "0.5", "k1": "2"}},
        "analysis": {
            "filter": {
                "jieba_stop": {
                    "type": "stop",
                    "stopwords_path": "stopwords/stopwords.txt",
                }
            },
            "analyzer": {
                "my_ana": {
                    "filter": ["lowercase", "jieba_stop"],
                    "tokenizer": "ik_max_word",
                }
            },
        },
    }


async def index_create(index_name: str, mapping: Dict[str, Dict[str, Any]]) -> None:
    es_client = get_es_client()
    body = {"settings": _common_settings(), "mappings": mapping}
    await es_client.indices.create(index=index_name, body=body)


async def index_exists(index_name: str) -> bool:
    es_client = get_es_client()
    return await _index_exists(es_client, index_name)


async def index_delete(index_name: str) -> None:
    es_client = get_es_client()
    await es_client.indices.delete(index=index_name, ignore=[404])


async def index_clear(index_name: str) -> None:
    es_client = get_es_client()
    await es_client.delete_by_query(
        index=index_name, body={"query": {"match_all": {}}}, refresh=True
    )


async def document_insert(index_name: str, docs: List[Dict[str, Any]]) -> None:
    if not docs:
        return
    es_client = get_es_client()
    chunk_size = 1000
    for i in range(0, len(docs), chunk_size):
        chunk = docs[i : i + chunk_size]
        actions = [{"_index": index_name, "_source": doc} for doc in chunk]
        await helpers.async_bulk(es_client, actions)


async def document_delete(index_name: str, query: Dict[str, Any]) -> None:
    es_client = get_es_client()
    await es_client.delete_by_query(
        index=index_name, body={"query": query}, conflicts="proceed", refresh=True
    )


async def search(index_name: str, body: Dict[str, Any]) -> Dict[str, Any]:
    es_client = get_es_client()
    return await es_client.search(index=index_name, body=body)
