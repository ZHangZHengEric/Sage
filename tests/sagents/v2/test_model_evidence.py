"""Diagnostic download projects existing model observations without inventing raw data."""
from sagents.v2.runtime.observability.evidence.models import model_evidence


def span(**attrs):
    return {"name":"model.request", "context":{"span_id":"a" * 16},
            "start_time":"2026-10-20T00:00:00Z", "end_time":"2026-10-20T00:00:02Z", "status_code":"OK",
            "attributes":{"session_id":"s", "run_id":"r", "request_id":"m", "model":"example",
                          "purpose":"agent", "input.value":'{"messages":[{"role":"user","content":"hello"}]}',
                          "output.value":'{"text":"answer","tool_calls":[]}',
                          "model_parameters":'{"max_tokens":100}', "usage":'{"input_tokens":10}', **attrs}}


def test_model_span_projects_normalized_request_and_response_without_raw_streams():
    row, = model_evidence([span()])
    assert row["request"]["messages"][0]["content"] == "hello"
    assert row["response"]["text"] == "answer"
    assert row["request_format"] == "normalized_trace"
    assert row["evidence_source"] == "trace_projection"
    assert row["usage"]["input_tokens"] == 10
    assert "stream" not in row
    assert row["status"] == "completed"


def test_raw_diagnostics_take_precedence_over_redacted_trace_projections():
    raw = {"session_id":"s", "run_id":"r", "request_id":"m", "request_format":"provider_wire",
           "request":{"password":"original", "messages":"full request"}, "response":{"text":"full answer"},
           "stream":{"wire_capture_available":True, "wire_events":[{"delta":"full"}]}}
    row, = model_evidence([span(**{"input.value":'{"truncated":true,"preview":"cut"}',
                                  "output.value":'{"text":"short"}'})], [raw])
    assert row["request"] == raw["request"] and row["response"] == raw["response"]
    assert row["stream"] == raw["stream"]
    assert row["request_format"] == "provider_wire" and not row["truncated"]
    assert row["evidence_source"] == "diagnostic_events"


def test_truncated_json_is_preserved_and_marked_without_attempted_repair():
    original = '{"messages":["long message' + 'x' * 20000
    row, = model_evidence([span(**{"input.value":original})])
    assert row["request"]["input"] == original
    assert row["request_truncated"] and row["truncated"]
    assert row["response"]["text"] == "answer"


def test_partial_diagnostics_fill_missing_fields_from_spans_with_sources():
    captured = {"session_id":"s", "run_id":"r", "request_id":"m", "stream":{"wire_events":[{"delta":"full"}]}}
    row, = model_evidence([span()], [captured])
    assert row["stream"] == captured["stream"]
    assert row["evidence_source"] == "mixed"
    assert row["field_sources"] == {"request":"trace_projection", "response":"trace_projection", "stream":"diagnostic_events"}


def test_metadata_only_span_keeps_request_identity_and_reports_missing_content():
    row, = model_evidence([span(**{"input.value":None, "output.value":None})])
    assert row["request_id"] == "m"
    assert not row["request_content_available"] and not row["response_content_available"]
    assert row.get("response") is None
