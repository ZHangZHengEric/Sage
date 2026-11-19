from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.v2.server.config.settings import ServerSettings


def distributed_runtime_prefix(settings: ServerSettings, component: str) -> str:
    if settings.postgres_url:
        from sagents.v2.runtime.session.plugins.postgres.identity import postgres_storage_identity
        identity = postgres_storage_identity(settings.postgres_url)
    elif settings.mysql_url:
        from sagents.v2.runtime.session.plugins.mysql import parse_mysql_dsn
        identity = parse_mysql_dsn(settings.mysql_url)
        identity.pop("password")
    else:
        raise ValueError("A SQL storage identity is required for the distributed runtime")
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
    return f"sage:{component}:{{{digest}}}:distributed"
