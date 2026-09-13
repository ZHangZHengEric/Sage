from collections import namedtuple, OrderedDict
from copy import deepcopy
from dataclasses import asdict, dataclass
from enum import Enum
from types import SimpleNamespace
import random

import pytest
from sagents.utils.dataclass_snapshot import dataclass_snapshot
from sagents.context.messages.message import MessageChunk, copy_message_snapshot
from common.services.chat_processor import ContentProcessor


@dataclass
class Nested:
    payload: list


class Color(Enum):
    BLUE = 'blue'


class CustomString(str):
    def __deepcopy__(self, memo):
        return CustomString(self + '-copied')


def test_asdict_matches_nested_sdk_enums_subclasses_and_mutable_isolation():
    Point = namedtuple('Point', 'x y')
    message = MessageChunk(role='assistant', content=[{'type':'text','text':'hello'}], metadata={
        'nested': Nested([{'a':[1,2]}]), 'tuple': (1,[2]),
        'named': Point(1,[2]), 'ordered': OrderedDict([('x',[1])]),
        'enum': Color.BLUE, 'custom': CustomString('value'),
    }, tool_calls=[SimpleNamespace(id='call', index=0, type='function', function=SimpleNamespace(name='f', arguments='{}'))])
    assert dataclass_snapshot(message) == asdict(message)
    snapshot = dataclass_snapshot(message)
    snapshot['metadata']['nested']['payload'][0]['a'].append(3)
    snapshot['content'][0]['text'] = 'changed'
    snapshot['tool_calls'][0].function.arguments = 'changed'
    assert message.content[0]['text'] == 'hello'
    assert message.metadata['nested'].payload[0]['a'] == [1,2]
    assert message.tool_calls[0].function.arguments == '{}'


def test_plain_payload_differential_against_asdict():
    rng = random.Random(73)
    def value(depth=0):
        if depth == 3 or rng.random() < .4:
            return rng.choice([None, True, False, 0, -5, 1.25, 'text', b'bytes'])
        if rng.random() < .5:
            return [value(depth+1) for _ in range(rng.randrange(5))]
        return {str(i): value(depth+1) for i in range(rng.randrange(5))}
    for _ in range(200):
        message = MessageChunk(role='assistant', content='text', metadata={'data':value()})
        assert dataclass_snapshot(message) == asdict(message)


def test_tail_copy_preserves_cycles_shared_references_extra_fields_and_inputs():
    original = MessageChunk(role='assistant', content='hello', metadata={'list':[1]})
    original.error_info = original.metadata
    original.metadata['self'] = original
    original.metadata['state'] = original.__dict__
    original.extra = ['dynamic attribute']
    clone = copy_message_snapshot(original)
    assert clone is not original
    assert clone.metadata is clone.error_info
    assert clone.metadata['self'] is clone
    assert clone.metadata['state'] is clone.__dict__
    clone.metadata['list'].append(2)
    clone.extra.append('changed')
    assert original.metadata['list'] == [1]
    assert original.extra == ['dynamic attribute']
    assert clone.content == original.content


def test_tail_copy_preserves_subclass_deepcopy_hook():
    class Special(MessageChunk):
        def __deepcopy__(self, memo):
            return 'custom snapshot'
    assert copy_message_snapshot(Special(role='assistant', content='x')) == 'custom snapshot'


@pytest.mark.parametrize('content', ['text', '{"results":[{"image":"data:image/png;base64,AAAA","content":"'+'x'*5100+'"}]}', {'results':[{'description':'y'*5100}]}])
def test_owned_cleanup_has_identical_output_and_does_not_mutate_message(content):
    original = MessageChunk(role='tool', tool_call_id='c', content=content, metadata={'nested':[1]})
    before = deepcopy(original)
    expected = ContentProcessor.clean_content(original.to_dict())
    owned = original.to_dict()
    actual = ContentProcessor.clean_owned_content(owned)
    assert actual == expected
    assert actual is owned
    actual['metadata']['nested'].append(2)
    assert original == before


def test_owned_cleanup_preserves_custom_copy_transformations():
    original = MessageChunk(role='assistant', content='text', metadata={'custom':CustomString('x')})
    assert ContentProcessor.clean_owned_content(original.to_dict()) == ContentProcessor.clean_content(original.to_dict())
    assert original.metadata['custom'] == 'x'


def test_instance_snapshot_copy_hook_retains_generic_behavior():
    message = MessageChunk(role='assistant', content='text')
    message.__deepcopy__ = lambda memo: 'instance hook'
    assert copy_message_snapshot(message) == deepcopy(message) == 'instance hook'


def test_snapshot_plain_containers_preserve_cycles_aliases_and_custom_backrefs():
    from copy import deepcopy
    from sagents.context.messages.message import MessageChunk, copy_message_snapshot

    class Backref:
        def __init__(self, owner):
            self.owner = owner

        def __deepcopy__(self, memo):
            return Backref(deepcopy(self.owner, memo))

    shared = []
    metadata = {"left": shared, "right": shared}
    shared.extend([metadata, Backref(metadata)])
    message = MessageChunk(role="assistant", content="hello", metadata=metadata)
    message.extra = shared
    for clone in (deepcopy(message), copy_message_snapshot(message)):
        assert clone.metadata is not metadata
        assert clone.metadata["left"] is clone.metadata["right"] is clone.extra
        assert clone.extra[0] is clone.metadata
        assert clone.extra[1].owner is clone.metadata
