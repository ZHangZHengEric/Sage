import json

from sagents.observability.opentelemetry_handler import OpenTelemetryTraceHandler


class FakeSpan:
    def __init__(self):
        self.attributes = {}
        self.status = None

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def set_status(self, status):
        self.status = status

    def record_exception(self, error):
        self.error = error

    def end(self):
        self.ended = True


def test_chain_end_records_final_system_context(monkeypatch):
    handler = OpenTelemetryTraceHandler()
    span = FakeSpan()

    monkeypatch.setattr(handler, "_get_current_span", lambda: span)
    monkeypatch.setattr(handler, "_pop_span", lambda: span)

    handler.on_chain_end(
        {"status": "finished"},
        final_system_context={
            "session_id": "session-1",
            "response_language": "zh-CN",
            "file_permission": "only allow read and write files in: /tmp/work",
        },
    )

    assert json.loads(span.attributes["system_context"]) == {
        "session_id": "session-1",
        "response_language": "zh-CN",
        "file_permission": "only allow read and write files in: /tmp/work",
    }


def test_chain_error_records_final_system_context(monkeypatch):
    handler = OpenTelemetryTraceHandler()
    span = FakeSpan()

    monkeypatch.setattr(handler, "_get_current_span", lambda: span)
    monkeypatch.setattr(handler, "_end_span_on_error", lambda error: None)

    handler.on_chain_error(
        RuntimeError("boom"),
        final_system_context={
            "session_id": "session-1",
            "private_workspace": "/tmp/ws",
        },
    )

    assert json.loads(span.attributes["system_context"]) == {
        "session_id": "session-1",
        "private_workspace": "/tmp/ws",
    }
