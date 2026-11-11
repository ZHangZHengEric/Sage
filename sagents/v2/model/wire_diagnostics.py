"""Optional scoped wire evidence, isolated from provider execution contracts."""
from contextvars import ContextVar
import json

wire_request_observer = ContextVar('sage_model_wire_request_observer', default=None)
wire_capture = ContextVar('sage_model_wire_capture', default=None)


class WireCapture:
    def __init__(self, max_bytes=8 * 1024 * 1024):
        self.events = []
        self.bytes = 0
        self.dropped = 0
        self.max_bytes = max_bytes
        self.observed = 0

    def append(self, value):
        self.observed += 1
        try:
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


_WIRE_PARAMETERS = frozenset({
    "temperature", "top_p", "top_k", "max_tokens", "max_completion_tokens",
    "max_output_tokens", "tool_choice", "response_format", "seed", "reasoning",
    "reasoning_effort", "thinking", "enable_thinking", "chat_template_kwargs",
    "generationConfig",
})


async def record_wire_request(payload, *, model, provider):
    observer = wire_request_observer.get()
    if observer is not None:
        parameters = {
            key: value
            for source in (payload, payload.get("extra_body") or {})
            for key, value in source.items()
            if key in _WIRE_PARAMETERS
        }
        await observer(payload, model=payload.get("model") or model, provider=provider, parameters=parameters)
