import time
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")

class BaseResponse(BaseModel, Generic[T]):
    code: int = 200
    message: str = "success"
    data: Optional[T] = None
    timestamp: float = 0.0

    def __init__(self, **data):
        if "timestamp" not in data:
            data["timestamp"] = time.time()
        super().__init__(**data)
