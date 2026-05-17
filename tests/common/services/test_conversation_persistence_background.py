"""持久化背景任务行为测试。

回归本次修复（commit 0bb54693）：persist_session_state_with_cancel_protection
不再用 anyio.CancelScope(shield=True) + asyncio.shield() 双 shield，改为
立刻派发后台 task，避免取消链路里同一上下文连续两次撞 shield 导致 anyio
_deliver_cancellation 反复 call_soon 自己造成 100% CPU 空转。
"""

import asyncio

import pytest

from common.services import conversation_service


@pytest.fixture(autouse=True)
def _clear_background_tasks():
    """每个用例前后清空全局后台 task 集合，避免互相串扰。"""
    conversation_service._BACKGROUND_PERSISTENCE_TASKS.clear()
    yield
    conversation_service._BACKGROUND_PERSISTENCE_TASKS.clear()


def _install_fake_persist(monkeypatch, *, duration: float = 0.0, raise_exc: Exception | None = None):
    """把模块级 persist_session_state 替换成可控 fake，返回观测列表。"""
    calls: list[str] = []

    async def _fake(session_id: str) -> None:
        calls.append(session_id)
        if duration > 0:
            await asyncio.sleep(duration)
        if raise_exc is not None:
            raise raise_exc

    monkeypatch.setattr(conversation_service, "persist_session_state", _fake)
    return calls


@pytest.mark.asyncio
async def test_persist_with_cancel_protection_returns_immediately_without_waiting(monkeypatch):
    """调用后立即返回，不等持久化跑完。"""
    # 把持久化设成 100ms 才结束，但 wait_for(协程, timeout=10ms) 应该仍能完成。
    _install_fake_persist(monkeypatch, duration=0.1)

    await asyncio.wait_for(
        conversation_service.persist_session_state_with_cancel_protection("s1"),
        timeout=0.01,
    )


@pytest.mark.asyncio
async def test_persist_with_cancel_protection_registers_and_unregisters_task(monkeypatch):
    """后台 task 应登记到全局集合，跑完后自动移除。"""
    _install_fake_persist(monkeypatch, duration=0.05)

    await conversation_service.persist_session_state_with_cancel_protection("s1")
    assert len(conversation_service._BACKGROUND_PERSISTENCE_TASKS) == 1
    [task] = list(conversation_service._BACKGROUND_PERSISTENCE_TASKS)
    assert task.get_name() == "persist-session-s1"

    await task
    # done_callback 是在 task 完成后被事件循环调度的，需要让出一次让 callback 跑完。
    await asyncio.sleep(0)
    assert conversation_service._BACKGROUND_PERSISTENCE_TASKS == set()


@pytest.mark.asyncio
async def test_persist_with_cancel_protection_two_calls_in_same_context_dont_deadlock(monkeypatch):
    """事故重现 case：取消链路里 interrupt_session 与 _finalize_session_end 会连续
    调用同一个函数两次。原实现的双 shield 在这个场景里会让取消传播卡住，
    新实现两次都应立即返回。"""
    _install_fake_persist(monkeypatch, duration=0.05)

    await asyncio.wait_for(
        asyncio.gather(
            conversation_service.persist_session_state_with_cancel_protection("s1"),
            conversation_service.persist_session_state_with_cancel_protection("s1"),
        ),
        timeout=0.1,
    )

    assert len(conversation_service._BACKGROUND_PERSISTENCE_TASKS) == 2


@pytest.mark.asyncio
async def test_persist_with_cancel_protection_does_not_block_caller_cancellation(monkeypatch):
    """调用方被取消时立即收敛，不再被持久化 shield 顶住。"""
    _install_fake_persist(monkeypatch, duration=10.0)

    async def _caller():
        await conversation_service.persist_session_state_with_cancel_protection("s1")
        # 模拟调用方在持久化后做"真正的耗时工作"被 cancel
        await asyncio.sleep(10.0)

    task = asyncio.create_task(_caller())
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=0.1)


@pytest.mark.asyncio
async def test_persist_with_cancel_protection_swallows_background_exception(monkeypatch):
    """后台持久化抛异常时调用方不感知，异常只会被 logger.warning 吞掉。"""
    _install_fake_persist(monkeypatch, raise_exc=RuntimeError("boom"))

    await conversation_service.persist_session_state_with_cancel_protection("s1")

    [task] = list(conversation_service._BACKGROUND_PERSISTENCE_TASKS)
    with pytest.raises(RuntimeError, match="boom"):
        await task
    # 让 done_callback 跑完，集合清空。
    await asyncio.sleep(0)
    assert conversation_service._BACKGROUND_PERSISTENCE_TASKS == set()
