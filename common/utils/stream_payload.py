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


# Bound event-loop inspection even for deeply nested/large tool results.
INLINE_JSON_CHAR_LIMIT = 16 * 1024
INLINE_JSON_NODE_LIMIT = 128


def _needs_background_encoding(payload):
    pending = [payload]
    characters = nodes = 0
    while pending:
        value = pending.pop()
        nodes += 1
        if nodes > INLINE_JSON_NODE_LIMIT:
            return True
        kind = type(value)
        if kind is str:
            characters += len(value)
            if characters > INLINE_JSON_CHAR_LIMIT:
                return True
        elif kind is dict:
            if nodes + len(pending) + 2 * len(value) > INLINE_JSON_NODE_LIMIT:
                return True
            pending.extend(value.keys())
            pending.extend(value.values())
        elif kind in (list, tuple):
            if nodes + len(pending) + len(value) > INLINE_JSON_NODE_LIMIT:
                return True
            pending.extend(value)
        elif kind not in (type(None), bool, int, float):
            return True
    return False


async def encode_stream_payload(payload, *, latency_budget=None, session_id=None):
    from sagents.utils.request_latency import stream_sync_stage
    from sagents.utils.latency_diagnostics import measured_to_thread

    def encode():
        with stream_sync_stage("delivery.json_encode", latency_budget):
            return json.dumps(payload, ensure_ascii=False) + "\n"

    if _needs_background_encoding(payload):
        return await measured_to_thread(
            "delivery.encode_large_payload", encode, session_id=session_id
        )
    return encode()
