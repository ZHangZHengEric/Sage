"""Optional scoped wire evidence, isolated from provider execution contracts."""
from contextvars import ContextVar
import json

wire_capture = ContextVar('sage_model_wire_capture', default=None)


class WireCapture:
    def __init__(self, max_bytes=8 * 1024 * 1024, consumer=None):
        self.consumer = consumer
        self.events = []
        self.bytes = 0
        self.dropped = 0
        self.max_bytes = max_bytes
        self.observed = 0

    def append(self, value):
        self.observed += 1
        try:
            if self.consumer is not None:
                if not self.consumer(value, self.observed - 1):
                    self.dropped += 1
                return
            if hasattr(value, 'model_dump'):
                value = value.model_dump(mode='json')
            encoded = json.dumps(value, ensure_ascii=False)
            size = len(encoded.encode())
            if self.max_bytes is not None and self.bytes + size > self.max_bytes:
                self.dropped += 1
                return
            self.bytes += size
            self.events.append(json.loads(encoded))
        except Exception:
            self.dropped += 1


def record_wire_event(value):
    capture = wire_capture.get()
    if capture is not None:
        capture.append(value)
