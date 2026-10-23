"""Freeze only ToolSandbox's datetime bindings, never the host or SDK clocks."""
from contextlib import contextmanager
import datetime
import sys
from types import SimpleNamespace

FROZEN_TIME = '2024-05-17 12:00:00+00:00'
_instant = datetime.datetime.fromisoformat(FROZEN_TIME)


class ScenarioDatetime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        value = _instant.astimezone(tz or datetime.timezone.utc)
        return cls.fromisoformat(value.isoformat()) if tz else cls.fromisoformat(value.replace(tzinfo=None).isoformat())

    @classmethod
    def utcnow(cls):
        return cls.now()

    @classmethod
    def today(cls):
        return cls.now()

    @classmethod
    def fromtimestamp(cls, timestamp, tz=None):
        value = datetime.datetime.fromtimestamp(timestamp, tz or datetime.timezone.utc)
        if tz is None:
            value = value.replace(tzinfo=None)
        return cls.fromisoformat(value.isoformat())

    def timestamp(self):
        # Treat naive scenario datetimes as UTC on every host, including macOS.
        value = self if self.tzinfo else self.replace(tzinfo=datetime.timezone.utc)
        return datetime.datetime.timestamp(value)


@contextmanager
def frozen_clock():
    proxy = SimpleNamespace(**{**vars(datetime), 'datetime': ScenarioDatetime})
    bindings = []
    for name, module in list(sys.modules.items()):
        if name.startswith('tool_sandbox.') and module is not None and vars(module).get('datetime') is datetime:
            bindings.append(module)
            module.datetime = proxy
    try:
        yield
    finally:
        for module in bindings:
            module.datetime = datetime
