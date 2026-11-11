"""Server diagnostic evidence and its lightweight timing projection."""

from sqlalchemy import BigInteger, Column, Double, Index, Integer, String, Table, Text
from sqlalchemy.dialects.mysql import LONGTEXT, VARCHAR

from app.v2.server.database.base import Base

metadata = Base.metadata
identifier = String(191).with_variant(VARCHAR(191, charset="utf8mb4", collation="utf8mb4_bin"), "mysql")
payload = Text().with_variant(LONGTEXT(), "mysql")


def scope(*, primary_key=False):
    return (
        Column("session_id", identifier, nullable=False, primary_key=primary_key),
        Column("run_id", identifier, nullable=False, primary_key=primary_key),
    )


models = Table(
    "diagnostic_models", metadata,
    *scope(primary_key=True), Column("request_id", identifier, primary_key=True),
    Column("payload", payload, nullable=False),
)
logs = Table(
    "diagnostic_logs", metadata,
    Column("id", BigInteger().with_variant(Integer(), "sqlite"), primary_key=True),
    *scope(), Column("payload", payload, nullable=False),
    Index("ix_diagnostic_logs_scope", "session_id", "run_id", "id"),
)
dropped = Table(
    "diagnostic_dropped_logs", metadata, *scope(primary_key=True),
    Column("count", BigInteger, nullable=False),
)
events = Table(
    "diagnostic_performance_events", metadata,
    Column("id", String(64), primary_key=True), *scope(),
    Column("event", String(96), nullable=False), Column("at", Double, nullable=False),
    Column("agent_id", identifier), Column("identity", identifier), Column("purpose", String(128)),
    Column("started_at", Double), Column("turn_id", identifier), Column("state", String(32)),
    Index("ix_diagnostic_events_time", "event", "at"),
    Index("ix_diagnostic_events_entry", "event", "started_at"),
    Index("ix_diagnostic_events_run", "run_id", "at"),
)
timings = Table(
    "diagnostic_performance_models", metadata, *scope(primary_key=True),
    Column("request_id", identifier, primary_key=True),
    Column("started_at", Double), Column("ended_at", Double), Column("first_token_at", Double),
    Column("purpose", String(128)), Column("turn_id", identifier),
    Index("ix_diagnostic_models_run", "run_id", "started_at"),
)
