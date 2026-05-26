from types import SimpleNamespace

from common.core.client import db


def test_create_aiomysql_engine_forces_ping_reconnect_arg(monkeypatch):
    fake_dialect = SimpleNamespace()
    fake_engine = SimpleNamespace(sync_engine=SimpleNamespace(dialect=fake_dialect))
    calls = []

    def fake_create_async_engine(*args, **kwargs):
        calls.append((args, kwargs))
        return fake_engine

    monkeypatch.setattr(db, "create_async_engine", fake_create_async_engine)

    engine = db._create_aiomysql_engine(
        "mysql+aiomysql://user:pass@host/db", future=True, pool_pre_ping=True
    )

    assert engine is fake_engine
    assert fake_dialect.__dict__["_send_false_to_ping"] is True
    assert calls == [
        (
            ("mysql+aiomysql://user:pass@host/db",),
            {"future": True, "pool_pre_ping": True},
        )
    ]
