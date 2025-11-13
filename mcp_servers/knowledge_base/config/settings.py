import os


LLM_API_KEY = (
    os.getenv("LLM_API_KEY")
    or os.getenv("KB_LLM_API_KEY")
    or os.getenv("OPENAI_API_KEY")
)
LLM_BASE_URL = (
    os.getenv("LLM_BASE_URL")
    or os.getenv("KB_LLM_BASE_URL")
    or os.getenv("OPENAI_BASE_URL")
)
LLM_MODEL = os.getenv("LLM_MODEL") or os.getenv("KB_LLM_MODEL") or "gpt-4o-mini"
_LLM_TEMPERATURE = os.getenv("LLM_TEMPERATURE")
LLM_TEMPERATURE = float(_LLM_TEMPERATURE) if _LLM_TEMPERATURE else None
_LLM_MAX_TOKENS = os.getenv("LLM_MAX_TOKENS")
LLM_MAX_TOKENS = int(_LLM_MAX_TOKENS) if _LLM_MAX_TOKENS else None

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

KB_MINIO_ENDPOINT = os.getenv("KB_MINIO_ENDPOINT", "")
KB_MINIO_ACCESS_KEY = os.getenv("KB_MINIO_ACCESS_KEY", "")
KB_MINIO_SECRET_KEY = os.getenv("KB_MINIO_SECRET_KEY", "")
KB_MINIO_SECURE = os.getenv("KB_MINIO_SECURE", "false").lower() == "true"
KB_MINIO_BUCKET = os.getenv("KB_MINIO_BUCKET", "origin")
KB_MINIO_PUBLIC_BASE_URL = os.getenv("KB_MINIO_PUBLIC_BASE_URL", "")
