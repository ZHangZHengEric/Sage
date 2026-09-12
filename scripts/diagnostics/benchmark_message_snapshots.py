"""Small offline CPU benchmark against standard-library snapshot behavior."""
from copy import deepcopy
from dataclasses import asdict
import json
import statistics
import time
from types import SimpleNamespace
from sagents.context.messages.message import MessageChunk, copy_message_snapshot
from sagents.utils.dataclass_snapshot import dataclass_snapshot
from common.services.chat_processor import ContentProcessor


def cpu_ms(fn):
    samples = []
    for _ in range(3):
        started = time.thread_time()
        for _ in range(1000):
            fn()
        samples.append((time.thread_time()-started)*1000)
    return round(statistics.median(samples), 3)


for label, message in [
    ('text', MessageChunk(role='assistant', content='text'*1000, metadata={'nested':[{'x':1}]})),
    ('tool_delta', MessageChunk(role='assistant', tool_calls=[SimpleNamespace(id='a', index=0, type='function', function=SimpleNamespace(name='f',arguments='x'*1000))])),
]:
    assert dataclass_snapshot(message) == asdict(message)
    assert copy_message_snapshot(message) == deepcopy(message)
    assert ContentProcessor.clean_owned_content(message.to_dict()) == ContentProcessor.clean_content(message.to_dict())
    print('SNAPSHOT_BENCH', json.dumps({'shape':label,'iterations':1000,
        'asdict_cpu_ms':cpu_ms(lambda:asdict(message)),
        'snapshot_cpu_ms':cpu_ms(lambda:dataclass_snapshot(message)),
        'deepcopy_cpu_ms':cpu_ms(lambda:deepcopy(message)),
        'tail_snapshot_cpu_ms':cpu_ms(lambda:copy_message_snapshot(message)),
        'serialize_and_clean_cpu_ms':cpu_ms(lambda:ContentProcessor.clean_content(message.to_dict())),
        'serialize_and_clean_owned_cpu_ms':cpu_ms(lambda:ContentProcessor.clean_owned_content(message.to_dict())),
    }))
