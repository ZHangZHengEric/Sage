from typing import Any, Dict, List, Optional, Union

from core.config import StartupConfig
from elasticsearch import AsyncElasticsearch, helpers
from core.client.embed import EMBEDDING_DIMS
from sagents.utils.logger import logger

ES_CLIENT: Optional[AsyncElasticsearch] = None


def get_es_client() -> AsyncElasticsearch:
    """
    获取全局 ES 客户端
    """
    global ES_CLIENT
    if ES_CLIENT is None:
        raise RuntimeError("ES 客户端未初始化，请先调用 init_es_client()")
    return ES_CLIENT


async def init_es_client(
    cfg: Optional[StartupConfig] = None,
) -> Optional[AsyncElasticsearch]:
    """
    初始化全局 ES 客户端
    """
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
            f"Elasticsearch 参数不足，未初始化 base={base}, api_key={api_key}, username={username}, password={'***' if password else None}"
        )
        return None

    try:
        if api_key:
            ES_CLIENT = AsyncElasticsearch(base, api_key=api_key)
        elif username and password:
            ES_CLIENT = AsyncElasticsearch(base, basic_auth=(username, password))
        else:
            ES_CLIENT = AsyncElasticsearch(base)
        logger.info(f"ES 客户端初始化成功: {base}")
        return ES_CLIENT
    except Exception as e:
        logger.error(f"ES 客户端初始化失败: {e}")
        return None


async def close_es_client() -> None:
    """
    关闭全局 ES 客户端
    """
    global ES_CLIENT
    if ES_CLIENT is not None:
        try:
            await ES_CLIENT.close()
            logger.info("ES 客户端已关闭")
        except Exception as e:
            logger.error(f"关闭 ES 客户端失败: {e}")
        finally:
            ES_CLIENT = None


def dims() -> int:
    """
    返回向量维度
    """
    return EMBEDDING_DIMS


async def _index_exists(client: AsyncElasticsearch, index_name: str) -> bool:
    try:
        return await client.indices.exists(index=index_name, ignore=[404, 400])
    except Exception as e:
        logger.error(f"检查索引是否存在失败 ({index_name}): {e}")
        return False


def _common_settings() -> Dict[str, Any]:
    """
    Elasticsearch 通用索引设置
    """
    return {
        "similarity": {"my_similarity": {"type": "BM25", "b": 0.5, "k1": 2.0}},
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
    """
    创建索引
    """
    es_client = get_es_client()
    body = {"settings": _common_settings(), "mappings": mapping}
    try:
        await es_client.indices.create(index=index_name, body=body)
        logger.info(f"索引创建成功: {index_name}")
    except Exception as e:
        logger.error(f"索引创建失败 ({index_name}): {e}")


async def index_exists(index_name: str) -> bool:
    es_client = get_es_client()
    return await _index_exists(es_client, index_name)


async def index_delete(index_name: str) -> None:
    es_client = get_es_client()
    try:
        await es_client.indices.delete(index=index_name, ignore_unavailable=True)
        logger.info(f"索引删除成功: {index_name}")
    except Exception as e:
        logger.error(f"索引删除失败 ({index_name}): {e}")


async def index_clear(index_name: str) -> None:
    es_client = get_es_client()
    try:
        await es_client.delete_by_query(
            index=index_name, body={"query": {"match_all": {}}}, refresh=True
        )
        logger.info(f"索引清空成功: {index_name}")
    except Exception as e:
        logger.error(f"索引清空失败 ({index_name}): {e}")


async def document_insert(
    index_name: str,
    docs: List[Dict[str, Any]],
    chunk_size: int = 1000,
    refresh: bool = True,
) -> None:
    """
    批量插入文档
    """
    if not docs:
        return
    es_client = get_es_client()
    try:
        for i in range(0, len(docs), chunk_size):
            chunk = docs[i : i + chunk_size]
            actions = [{"_index": index_name, "_source": doc} for doc in chunk]
            await helpers.async_bulk(es_client, actions, refresh=refresh)
        logger.info(f"文档批量插入完成: {len(docs)} 条, 索引 {index_name}")
    except Exception as e:
        logger.error(f"文档插入失败 ({index_name}): {e}")


async def document_delete(index_name: str, query: Dict[str, Any]) -> None:
    es_client = get_es_client()
    try:
        await es_client.delete_by_query(
            index=index_name, body={"query": query}, conflicts="proceed", refresh=True
        )
        logger.info(f"文档删除完成: 索引 {index_name}")
    except Exception as e:
        logger.error(f"文档删除失败 ({index_name}): {e}")


async def search(index_name: str, body: Dict[str, Any]) -> Dict[str, Any]:
    es_client = get_es_client()
    try:
        return await es_client.search(index=index_name, body=body)
    except Exception as e:
        logger.error(f"ES 搜索失败 ({index_name}): {e}")
        return {"hits": {"total": 0, "hits": []}}
