"""Domain records and invariants. No FastAPI, no SQLAlchemy.

New business: add ``domain/<name>.py`` and ``repositories/<name>.py``.
Add ``services/<name>.py`` only when a use case goes beyond CRUD.
"""

from app.server_v2.domain.catalog import ModelRecord, UserCatalog
from app.server_v2.domain.threads import ThreadRecord
from app.server_v2.domain.users import Role, UserRecord

__all__ = [
    "ModelRecord",
    "Role",
    "ThreadRecord",
    "UserCatalog",
    "UserRecord",
]
