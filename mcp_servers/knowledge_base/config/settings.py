import os


EMBED_API_KEY = (
    os.getenv("EMBEDDING_API_KEY")
    or os.getenv("KB_EMBEDDING_API_KEY")
    or os.getenv("OPENAI_API_KEY")
)
EMBED_BASE_URL = (
    os.getenv("EMBEDDING_BASE_URL")
    or os.getenv("KB_EMBEDDING_BASE_URL")
    or os.getenv("OPENAI_BASE_URL")
)
EMBED_MODEL = (
    os.getenv("EMBEDDING_MODEL")
    or os.getenv("KB_EMBEDDING_MODEL")
    or "text-embedding-3-large"
)
_EMBEDDING_DIMS = (
    os.getenv("KB_EMBEDDING_DIMS") or os.getenv("EMBEDDING_DIMS") or "1024"
)
try:
    EMBEDDING_DIMS = int(_EMBEDDING_DIMS)
except Exception:
    EMBEDDING_DIMS = 1024

ES_URL = (
    os.getenv("ELASTICSEARCH_URL") or os.getenv("ES_URL") or "http://localhost:9200"
)
ES_API_KEY = os.getenv("ELASTICSEARCH_API_KEY") or os.getenv("ES_API_KEY")
ES_USERNAME = os.getenv("ELASTICSEARCH_USERNAME") or os.getenv("ES_USERNAME")
ES_PASSWORD = os.getenv("ELASTICSEARCH_PASSWORD") or os.getenv("ES_PASSWORD")
