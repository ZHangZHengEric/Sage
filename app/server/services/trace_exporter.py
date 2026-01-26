import datetime
import typing

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import format_span_id, format_trace_id

from .trace import TraceService


class SageSpanExporter(SpanExporter):
    def export(self, spans: typing.Sequence[ReadableSpan]) -> SpanExportResult:
        service = TraceService.get_instance()

        span_dicts = []
        for span in spans:
            ctx = span.get_span_context()
            parent = span.parent

            start_dt = datetime.datetime.fromtimestamp(span.start_time / 1e9)
            end_dt = datetime.datetime.fromtimestamp(span.end_time / 1e9)

            span_dict = {
                "name": span.name,
                "context": {
                    "trace_id": format_trace_id(ctx.trace_id),
                    "span_id": format_span_id(ctx.span_id),
                },
                "kind": str(span.kind),
                "parent_id": format_span_id(parent.span_id) if parent else None,
                "start_time": start_dt,
                "end_time": end_dt,
                "status": {
                    "status_code": span.status.status_code.name,
                    "description": span.status.description,
                },
                "attributes": dict(span.attributes) if span.attributes else {},
                "events": [
                    {
                        "name": event.name,
                        "timestamp": datetime.datetime.fromtimestamp(
                            event.timestamp / 1e9
                        ).isoformat(),
                        "attributes": dict(event.attributes) if event.attributes else {},
                    }
                    for event in span.events
                ],
                "resource": dict(span.resource.attributes) if span.resource else {},
            }
            span_dicts.append(span_dict)

        service.enqueue_spans(span_dicts)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass
