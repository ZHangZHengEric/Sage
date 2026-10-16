"""Run-local evidence of repeated inspections, independent of read line ranges."""
from __future__ import annotations
import hashlib
import json


def inspection_progress(state, response, results, read_tools):
    if not response.tool_calls:
        return state
    seen = list(state.inspection_evidence)
    evidence = {r.tool_call_id: r for r in results}
    inspections_only = True
    novel = False
    for call in response.tool_calls:
        result = evidence.get(call.tool_call_id)
        if result is None:
            continue
        if result.error:
            continue
        if call.name not in read_tools:
            inspections_only = False
            break
        contents = []
        for block in result.content:
            value = block.model_dump(mode='json')
            if value.get('kind') == 'json' and isinstance(value.get('value'), dict):
                payload = value['value']
                # The same content with different request ranges is not new evidence.
                value = payload.get('content', payload.get('entries', payload))
            contents.append(value)
        path = call.arguments.get('file_path', call.arguments.get('path', ''))
        digest = hashlib.sha256(json.dumps([call.name, path, contents], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if digest not in seen:
            novel = True
            seen.append(digest)
    return state.model_copy(update={
        'inspection_evidence': tuple(seen[-128:]),
        'no_progress_steps': state.no_progress_steps + 1 if inspections_only and not novel else 0,
    })


def repeated_cycles(values):
    for period in range(1, min(6, len(values) // 3) + 1):
        pattern = values[-period:]
        count = 1
        while len(values) >= (count + 1) * period and values[-(count + 1)*period:-count*period] == pattern:
            count += 1
        if count >= 3:
            return count
    return 1 if values else 0
