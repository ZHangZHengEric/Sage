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

    def add_event(self, name, attributes=None):
        self.event_name = name
        self.event_attributes = attributes or {}

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


def test_message_start_formats_start_ts_for_trace(monkeypatch):
    handler = OpenTelemetryTraceHandler()
    span = FakeSpan()

    monkeypatch.setattr(handler, "_get_current_span", lambda: span)
    monkeypatch.setattr(
        handler,
        "_format_epoch_millis",
        lambda value: "2026-06-30 13:46:34.871",
    )

    handler.on_message_start(
        "session-1",
        "message-1",
        role="assistant",
        message_type="tool_call",
        sequence_index=3,
        start_ts=1782798394.871,
    )

    assert span.event_name == "message.start"
    assert span.event_attributes["start_ts"] == "2026-06-30 13:46:34.871"
    assert span.event_attributes["sequence_index"] == 3
