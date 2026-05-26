"""stream_api_with_disconnect_check 行为测试。

回归本次修复（commit 0bb54693）：
- disconnect 检测后改为 break，不再人为 raise GeneratorExit
  （旧实现会在 generator 关闭临界态做远程持久化，叠加 anyio CancelScope
  造成 100% CPU 空转）。
- interrupt_session / generator.aclose() 都加 5s 超时封顶，下层偶发卡死
  不会拖死整个清理链路。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.server.routers import chat as chat_module


class _FakeRequest:
    """模拟 FastAPI Request.is_disconnected()：按预设序列返回。"""

    def __init__(self, disconnect_at: int):
        self._disconnect_at = disconnect_at
        self._calls = 0

    async def is_disconnected(self) -> bool:
        self._calls += 1
        return self._calls > self._disconnect_at


async def _normal_generator(num_chunks: int):
    for i in range(num_chunks):
        yield f"chunk-{i}\n"


async def _generator_with_hanging_aclose():
    """yield 一个 chunk 后 sleep；finally（被 aclose 触发）里卡死，模拟下层
    清理被某个永远不返回的 await 挡住。"""
    try:
        yield "chunk-0\n"
        await asyncio.sleep(10)
    finally:
        await asyncio.Future()


@pytest.fixture
def _patch_chat_module(monkeypatch):
    """统一 patch chat router 模块里的副作用入口，返回一组 mock 供断言。"""
    interrupt_mock = AsyncMock()
    safe_release_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(chat_module, "delete_session_run_lock", lambda session_id: None)

    monkeypatch.setattr(
        chat_module.conversation_service, "interrupt_session", interrupt_mock
    )
    monkeypatch.setattr(chat_module, "safe_release", safe_release_mock)

    # 缩短超时，便于在 pytest 全局 2s timeout 内验证。
    monkeypatch.setattr(chat_module, "_DISCONNECT_INTERRUPT_TIMEOUT", 0.1)
    monkeypatch.setattr(chat_module, "_GENERATOR_ACLOSE_TIMEOUT", 0.1)

    return SimpleNamespace(
        interrupt=interrupt_mock,
        safe_release=safe_release_mock,
    )


@pytest.mark.asyncio
async def test_disconnect_breaks_loop_without_raising_generator_exit(
    _patch_chat_module,
):
    """断开后正常 break；不应有 GeneratorExit 泄漏到调用方，
    interrupt_session 应被调用一次，资源应被释放。"""
    # 让 is_disconnected 第 1 次就返回 True（迭代第一个 chunk 后立即触发）
    request = _FakeRequest(disconnect_at=0)
    lock = asyncio.Lock()

    chunks = []
    gen = chat_module.stream_api_with_disconnect_check(
        _normal_generator(5), request, lock, "session-disconnect-1"
    )
    # 直接消费完，不应抛任何异常
    async for ch in gen:
        chunks.append(ch)

    # 第一个 chunk 还没 yield 就 break 了（因为先检查 is_disconnected）
    assert chunks == []
    _patch_chat_module.interrupt.assert_awaited_once()
    _patch_chat_module.safe_release.assert_awaited_once()


@pytest.mark.asyncio
async def test_disconnect_yields_chunks_before_break(_patch_chat_module):
    """前 N 次 is_disconnected 返回 False 时正常 yield，第 N+1 次返回 True 才 break。"""
    request = _FakeRequest(disconnect_at=2)
    lock = asyncio.Lock()

    chunks = []
    async for ch in chat_module.stream_api_with_disconnect_check(
        _normal_generator(10), request, lock, "session-disconnect-2"
    ):
        chunks.append(ch)

    assert chunks == ["chunk-0\n", "chunk-1\n"]
    _patch_chat_module.interrupt.assert_awaited_once()


@pytest.mark.asyncio
async def test_interrupt_session_timeout_does_not_block_cleanup(
    monkeypatch, _patch_chat_module
):
    """interrupt_session 卡死时应在超时后跳过，aclose / safe_release 仍要执行。"""

    async def _hanging_interrupt(*args, **kwargs):
        await asyncio.Future()

    monkeypatch.setattr(
        chat_module.conversation_service, "interrupt_session", _hanging_interrupt
    )

    request = _FakeRequest(disconnect_at=0)
    lock = asyncio.Lock()

    start = asyncio.get_event_loop().time()
    async for _ in chat_module.stream_api_with_disconnect_check(
        _normal_generator(5), request, lock, "session-interrupt-hang"
    ):
        pass
    elapsed = asyncio.get_event_loop().time() - start

    # 应在 interrupt 超时（100ms）附近完成，远小于 pytest 2s timeout。
    assert elapsed < 1.0, (
        f"interrupt_session 卡死时清理未及时返回，elapsed={elapsed:.3f}s"
    )
    # 资源释放路径仍要被走到。
    _patch_chat_module.safe_release.assert_awaited_once()


@pytest.mark.asyncio
async def test_generator_aclose_timeout_does_not_block_cleanup(_patch_chat_module):
    """generator.aclose() 卡死时应在超时后跳过，safe_release 仍要执行。"""
    request = _FakeRequest(disconnect_at=0)
    lock = asyncio.Lock()

    start = asyncio.get_event_loop().time()
    async for _ in chat_module.stream_api_with_disconnect_check(
        _generator_with_hanging_aclose(), request, lock, "session-aclose-hang"
    ):
        pass
    elapsed = asyncio.get_event_loop().time() - start

    # 两个超时窗口都 100ms，且 interrupt mock 立即返回，总耗时应在 ~100ms 附近。
    assert elapsed < 1.0, f"aclose 卡死时清理未及时返回，elapsed={elapsed:.3f}s"
    _patch_chat_module.safe_release.assert_awaited_once()
