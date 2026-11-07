"""Redis metadata protocol shared by SQL archive backends."""
from .._shared.redis_metadata import (
    decode_redis_metadata as decode_redis_metadata,
    read_redis_metadata_batch as read_redis_metadata_batch,
)
