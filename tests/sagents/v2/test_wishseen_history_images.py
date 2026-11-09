"""Legacy feedback files affect inference only, never canonical history."""
import hashlib
import os

import pytest
from PIL import Image

from sagents.v2.context import ContextProjection, DefaultContextAssembler
from sagents.v2.context.summary import message_digests_async
from sagents.v2.contracts.items import ImageBlock, TextBlock
from sagents.v2.model import ModelMessage
from sagents.v2.runtime.artifact import images
from tests.sagents.v2.test_context_pipeline_matrix import command


def url(media='m_example', tenant='123'):
    return f'https://storage.withling.top/wishseen/media/{tenant}/{media}?X-Amz-Signature=expired'


def feedback(root, media='m_example'):
    path = root / (hashlib.sha256(media.encode()).hexdigest()[:24] + '.png')
    Image.new('RGB', (2, 2)).save(path)
    return path


def metadata(root):
    return {images.WISHSEEN_FEEDBACK_ROOT: str(root), 'server_v2.workspace_user_id': '123'}


@pytest.mark.parametrize('uri', [url(tenant='456'), url().replace('https:', 'http:'),
    url().replace('storage.withling.top', 'evil.test'), url().replace('/m_example?', '/m_example/wrong?'),
    url().replace('X-Amz-Signature=expired', 'other=X-Amz-Signature=expired'),
    url().replace('X-Amz-Signature=expired', 'X-Amz-Signature='),
    url().replace('m_example', '../m_example')])
def test_unrelated_or_malformed_urls_are_not_rewritten(uri):
    assert images.wishseen_history_image_id(uri, '123') is None


async def test_canonical_history_and_digests_survive_file_changes(tmp_path):
    root = tmp_path.resolve()
    path = feedback(root)
    ledger = (ModelMessage(role='user', content=(ImageBlock(uri=url(), mime_type='image/png'),)),)
    captured = []

    class Reducer:
        async def reduce(self, messages, budget, *, scope):
            captured.append(scope.canonical_messages)
            return ContextProjection(messages=messages, source_message_count=len(messages))

    assembler = DefaultContextAssembler(reducer=Reducer())
    first = await assembler.prepare_projection(command(metadata=metadata(root)), ledger)
    assert first.messages[0].content[0].uri.startswith('data:image/png;base64,')
    path.unlink()
    second = await assembler.prepare_projection(command(metadata=metadata(root)), ledger)
    assert isinstance(second.messages[0].content[0], TextBlock)
    assert captured == [ledger, ledger]
    assert await message_digests_async(captured[0]) == await message_digests_async(captured[1])
    assert ledger[0].content[0].uri == url()


async def test_pruned_images_are_never_loaded_and_search_history_stays_canonical(tmp_path, monkeypatch):
    ledger = (ModelMessage(role='user', content=(ImageBlock(uri=url(), mime_type='image/png'),)),
              ModelMessage(role='user', content=(TextBlock(text='follow up'),)))

    class Reducer:
        async def reduce(self, messages, budget, *, scope):
            return ContextProjection(messages=messages[-1:], historical_messages=messages[:-1],
                                     source_message_count=len(messages))

    def unexpected(*args, **kwargs):
        raise AssertionError('pruned image was read')
    monkeypatch.setattr(images, 'read_wishseen_feedback', unexpected)
    result = await DefaultContextAssembler(reducer=Reducer()).prepare_projection(
        command(metadata=metadata(tmp_path.resolve())), ledger)
    assert result.historical_messages == ledger[:-1]
    assert result.messages == ledger[-1:]


async def test_repeated_images_are_cached_and_non_user_images_unchanged(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    feedback(root)
    block = ImageBlock(uri=url(), mime_type='image/png')
    messages = (ModelMessage(role='user', content=(block, block)),
                ModelMessage(role='assistant', content=(block,)))
    read = images.read_wishseen_feedback
    calls = []
    def counted(*args, **kwargs):
        calls.append(args)
        return read(*args, **kwargs)
    monkeypatch.setattr(images, 'read_wishseen_feedback', counted)
    result = await images.hydrate_wishseen_history(messages, metadata(root))
    assert len(calls) == 1
    assert result[0].content[0] == result[0].content[1]
    assert result[1] == messages[1]
    assert await images.hydrate_wishseen_history(messages, {}) == messages


@pytest.mark.parametrize('kind', ['parent-link', 'leaf-link', 'oversize', 'empty'])
def test_feedback_rejects_unsafe_or_invalid_files(tmp_path, monkeypatch, kind):
    root = tmp_path.resolve()
    outside = root / 'outside'
    outside.mkdir()
    path = feedback(outside)
    target = root / 'feedback'
    if kind == 'parent-link':
        target.symlink_to(outside, target_is_directory=True)
    else:
        target.mkdir()
        if kind == 'leaf-link':
            (target / path.name).symlink_to(path)
        else:
            target_file = feedback(target)
            if kind == 'empty':
                target_file.write_bytes(b'')
            else:
                monkeypatch.setattr(images, '_MAX_FEEDBACK_BYTES', 1)
    assert images.read_wishseen_feedback(str(target), 'm_example') is None
    assert images.read_wishseen_feedback(str(target), 'm_example', read_data=False) is None


def test_feedback_rejects_same_size_rewrite_during_read(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    path = feedback(root)
    original = images.os.fdopen
    class Reader:
        def __init__(self, *args):
            self.inner = original(*args)
        def __enter__(self): return self
        def __exit__(self, *args): return self.inner.__exit__(*args)
        def fileno(self): return self.inner.fileno()
        def read(self, size):
            data = self.inner.read(size)
            info = path.stat()
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
            return data
    monkeypatch.setattr(images.os, 'fdopen', Reader)
    assert images.read_wishseen_feedback(str(root), 'm_example') is None
