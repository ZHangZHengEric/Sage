"""Filter structured stream events before encoding without changing wire rules."""

import json


def should_filter_stream_chunk(chunk, filtered_types):
    try:
        payload = json.loads(chunk)
    except Exception:
        return False
    return isinstance(payload, dict) and payload.get("type") in filtered_types


def should_filter_stream_payload(payload, filtered_types):
    if filtered_types is None:
        return False
    if type(payload) is dict and type(payload.get("type")) in (str, type(None)):
        return payload.get("type") in filtered_types
    # Preserve JSON normalization/errors for unusual or custom event types.
    return should_filter_stream_chunk(
        json.dumps(payload, ensure_ascii=False), filtered_types
    )
