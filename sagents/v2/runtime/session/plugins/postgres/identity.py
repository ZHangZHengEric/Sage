"""Credential-independent PostgreSQL storage identity for Redis namespaces."""

from urllib.parse import parse_qsl, unquote, urlsplit
from .state import parse_postgres_dsn


def postgres_storage_identity(dsn):
    parsed = urlsplit(parse_postgres_dsn(dsn))
    query = dict(parse_qsl(parsed.query))
    # libpq query parameters can override the URI authority. Include the SQL
    # search path because two schemas in one database must not share hot state.
    return {
        "backend": "postgres",
        "host": query.get("host", parsed.hostname or "127.0.0.1"),
        "port": int(query.get("port", parsed.port or 5432)),
        "user": query.get("user", unquote(parsed.username or "postgres")),
        "db": query.get("dbname", unquote(parsed.path.lstrip("/"))),
        "options": query.get("options", ""),
        "service": query.get("service", ""),
    }
