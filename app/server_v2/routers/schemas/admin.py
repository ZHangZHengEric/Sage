from __future__ import annotations

from app.server_v2.routers.schemas.catalog import ModelPublic
from app.server_v2.routers.schemas.conversations import ThreadPublic

class AdminThreadPublic(ThreadPublic):
    username: str

class AdminModelPublic(ModelPublic):
    user_id: str
    username: str

