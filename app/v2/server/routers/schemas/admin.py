from __future__ import annotations

from app.v2.server.routers.schemas.catalog import ModelPublic
from app.v2.server.routers.schemas.conversations import ThreadPublic

class AdminThreadPublic(ThreadPublic):
    username: str

class AdminModelPublic(ModelPublic):
    user_id: str
    username: str

