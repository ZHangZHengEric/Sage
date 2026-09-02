"""headless 纵切：StartRun → 消费事件流 → 审批 → 续跑 → 终态结果（支持用户中断与跨进程接管）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sagents.v2 import SAgent
from sagents.v2.contracts.commands import (
    CancelRun,
    InputItem,
    ReplyInteraction,
    ResumeRun,
    RunConfig,
    StartRun,
    SteerRun,
)
from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import (
    TERMINAL_RUN_STATES,
    EventCursor,
    RunSnapshot,
    RunState,
)

from app.cli.services.base import CLIError
from app.cli.v2.interaction import JSON_DECISION_TYPE, InteractionDecider
from app.cli.v2.render import EventRenderer, final_assistant_text
from app.cli.v2.signals import EXIT_INTERRUPTED

# 用户中断后，等待 driver 在安全点退出的时间；超时不阻塞进程退出（durable 状态已是 CANCELLED）。
INTERRUPT_GRACE_SECONDS = 5.0
INTERRUPT_REASON = "user_interrupt"
# CancelRun 是乐观 CAS；driver 每提交一次事件 revision 就会前进，撞车后重读重试的上限。
CANCEL_CAS_ATTEMPTS = 8
# SteerRun 同样是 CAS；运行中 revision 变得更快。
STEER_CAS_ATTEMPTS = 6
# ``--json`` 模式下，驱动方在 Run 进行中追加输入的帧类型。
JSON_STEER_TYPE = "v2_steer"
LineReader = Callable[[], Awaitable[str | None]]
# 上一个进程崩溃后遗留的非终态 run：其 worker 租约（CLI 配 5s）过期后才会被重新入队并
# 结算为 execution.worker_restarted，这里等待的上限要明显大于租约。
PENDING_RUN_SETTLE_SECONDS = 12.0
_PENDING_STATES = frozenset(
    {RunState.QUEUED, RunState.RUNNING, RunState.RESUMING, RunState.SUSPEND_REQUESTED}
)


@dataclass
class RunOutcome:
    run_id: str
    session_id: str
    state: RunState
    final_text: str = ""
    error: RuntimeErrorInfo | None = None
    event_types: list[str] = field(default_factory=list)
    interrupted: bool = False
    # 被接受但 Run 结束前没有机会应用的 steer 文本（模型没有再走下一步）。
    unapplied_steers: tuple[str, ...] = ()

    @property
    def exit_code(self) -> int:
        if self.interrupted:
            return EXIT_INTERRUPTED
        if self.state == RunState.COMPLETED:
            return 0
        if self.state == RunState.SUSPENDED:
            return 2
        return 1


def build_start_run(
    *,
    agent_id: str,
    task: str,
    resolved_spec_hash: str,
    session_id: str | None = None,
    config: RunConfig | None = None,
    metadata: dict | None = None,
    invocation_mode: str | None = None,
    idempotency_key: str | None = None,
) -> StartRun:
    if config is None:
        config = RunConfig(metadata=dict(metadata or {}))
    elif metadata:
        config = config.model_copy(update={"metadata": {**config.metadata, **metadata}})
    return StartRun(
        session_id=session_id,
        agent_id=agent_id,
        input=(InputItem(role="user", content=(TextBlock(text=task),)),),
        config=config,
        resolved_spec_hash=resolved_spec_hash,
        idempotency_key=idempotency_key or new_id("cli_request"),
        invocation_mode=invocation_mode,
    )


class _EventTracker:
    """记录本 Run 已看到的事件类型与续订阅 cursor（renderer 可能跨多个 Run 复用）。"""

    def __init__(self, renderer: EventRenderer, *, start_sequence: int = 0) -> None:
        self.renderer = renderer
        self.seen: list[str] = []
        self.run_sequence = start_sequence

    def render(self, event) -> None:
        self.seen.append(event.type)
        self.run_sequence = max(self.run_sequence, event.run_sequence)
        self.renderer.handle(event)

    def cursor(self, run_id: str) -> EventCursor:
        return EventCursor(run_id=run_id, run_sequence=self.run_sequence)


async def run_task(
    agent: SAgent,
    command: StartRun,
    context: RequestContext,
    *,
    renderer: EventRenderer,
    decider: InteractionDecider,
    session_frame: dict | None = None,
    interrupt: asyncio.Event | None = None,
    interrupt_grace_seconds: float = INTERRUPT_GRACE_SECONDS,
    steer_source: LineReader | None = None,
    steer_json: bool = False,
) -> RunOutcome:
    """驱动一次新 Run 直到终态；期间的每次挂起都交给 ``decider`` 作答。

    ``interrupt`` 被置位（如用户按 Ctrl-C）时立即发 ``CancelRun``：durable 状态先变为
    CANCELLED，driver 在下一个安全点看到终态自行退出。``steer_source`` 给出时，Run 进行中
    读到的输入以 ``SteerRun`` 排入下一个安全模型边界。
    """

    stream = await agent.run_stream(command, context)
    run_id = stream.handle.run_id
    renderer.frame(
        {
            "type": "cli_v2_session",
            "session_id": stream.handle.session_id,
            "run_id": run_id,
            "agent_id": command.agent_id,
            **(session_frame or {}),
        }
    )
    tracker = _EventTracker(renderer)
    canceller = _InterruptCanceller(agent, run_id, context, renderer, interrupt)
    steerer = _Steerer(agent, run_id, context, renderer, steer_source, json_frames=steer_json)
    canceller.start()
    try:
        await _consume_events(stream.events, tracker, steerer)
        snapshot = await canceller.wait_driver(stream.wait(), interrupt_grace_seconds)
        snapshot = await _drive_suspensions(
            agent,
            snapshot,
            context,
            renderer=renderer,
            decider=decider,
            tracker=tracker,
            canceller=canceller,
            steerer=steerer,
            interrupt=interrupt,
            grace_seconds=interrupt_grace_seconds,
        )
    finally:
        await canceller.stop()
    return await _finish(agent, snapshot, renderer, tracker, canceller, steerer)


async def resume_run(
    agent: SAgent,
    run_id: str,
    context: RequestContext,
    *,
    renderer: EventRenderer,
    decider: InteractionDecider,
    session_frame: dict | None = None,
    interrupt: asyncio.Event | None = None,
    interrupt_grace_seconds: float = INTERRUPT_GRACE_SECONDS,
    steer_source: LineReader | None = None,
    steer_json: bool = False,
) -> RunOutcome:
    """接管一个已挂起的 Run（通常来自上一个进程）：作答/恢复后续跑到终态。"""

    snapshot = await agent.runtime.get_run(run_id)
    renderer.frame(
        {
            "type": "cli_v2_session",
            "session_id": snapshot.session_id,
            "run_id": run_id,
            "resumed": True,
            **(session_frame or {}),
        }
    )
    tracker = _EventTracker(renderer, start_sequence=snapshot.last_run_sequence)
    canceller = _InterruptCanceller(agent, run_id, context, renderer, interrupt)
    steerer = _Steerer(agent, run_id, context, renderer, steer_source, json_frames=steer_json)
    canceller.start()
    try:
        snapshot = await _drive_suspensions(
            agent,
            snapshot,
            context,
            renderer=renderer,
            decider=decider,
            tracker=tracker,
            canceller=canceller,
            steerer=steerer,
            interrupt=interrupt,
            grace_seconds=interrupt_grace_seconds,
        )
    finally:
        await canceller.stop()
    return await _finish(agent, snapshot, renderer, tracker, canceller, steerer)


async def wait_for_pending_run_settlement(
    agent: SAgent,
    snapshot: RunSnapshot,
    context: RequestContext,
    *,
    timeout: float = PENDING_RUN_SETTLE_SECONDS,
) -> RunSnapshot:
    """等一个非终态、非挂起的遗留 Run 被本进程的 dispatcher 恢复结算（或超时原样返回）。

    filesystem scheduler 会在启动时把没有安全检查点的孤儿 Run 标为
    ``execution.worker_restarted``；这里只是事件驱动地等那个结果，不重放任何副作用。
    """

    if snapshot.state not in _PENDING_STATES:
        return snapshot

    async def observe() -> None:
        async for _ in agent.subscribe_events(
            EventCursor(run_id=snapshot.run_id, run_sequence=snapshot.last_run_sequence),
            context,
        ):
            current = await agent.runtime.get_run(snapshot.run_id)
            if current.state not in _PENDING_STATES:
                return

    try:
        await asyncio.wait_for(observe(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    return await agent.runtime.get_run(snapshot.run_id)


async def _drive_suspensions(
    agent: SAgent,
    snapshot: RunSnapshot,
    context: RequestContext,
    *,
    renderer: EventRenderer,
    decider: InteractionDecider,
    tracker: _EventTracker,
    canceller: "_InterruptCanceller",
    steerer: "_Steerer",
    interrupt: asyncio.Event | None,
    grace_seconds: float,
) -> RunSnapshot:
    run_id = snapshot.run_id
    while snapshot.state == RunState.SUSPENDED and not canceller.triggered:
        replied = await _answer_suspension(
            agent,
            snapshot,
            context,
            decider=decider,
            renderer=renderer,
            abort=interrupt,
        )
        if not replied or canceller.triggered:
            # 中断可能发生在等待用户作答期间：此时 Run 已被取消，不能再续跑。
            if canceller.triggered:
                snapshot = await agent.runtime.get_run(run_id)
            break
        execution = await agent.continue_run(run_id, context)
        await _consume_events(
            agent.subscribe_events(tracker.cursor(run_id), context), tracker, steerer
        )
        snapshot = await canceller.wait_driver(asyncio.shield(execution), grace_seconds)
    return snapshot


async def _consume_events(events, tracker: _EventTracker, steerer: "_Steerer") -> None:
    """渲染事件流直到它在传输边界关闭；同时把运行中读到的输入交给 steerer。"""

    if not steerer.enabled:
        async for event in events:
            tracker.render(event)
            steerer.observe(event)
        return
    iterator = events.__aiter__()
    next_event = asyncio.ensure_future(iterator.__anext__())
    next_line: asyncio.Future | None = asyncio.ensure_future(steerer.read_line())
    try:
        while True:
            waiting = {next_event} | ({next_line} if next_line is not None else set())
            done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
            if next_line is not None and next_line in done:
                line = next_line.result()
                if line is None:
                    next_line = None  # stdin EOF：不再读，只继续消费事件
                else:
                    await steerer.submit_line(line)
                    next_line = asyncio.ensure_future(steerer.read_line())
            if next_event in done:
                try:
                    event = next_event.result()
                except StopAsyncIteration:
                    return
                tracker.render(event)
                steerer.observe(event)
                next_event = asyncio.ensure_future(iterator.__anext__())
    finally:
        # 取消挂着的 stdin 读取是安全的：单一读取者的队列不会因此丢行。
        for task in (next_event, next_line):
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


class _Steerer:
    """把 Run 进行中读到的输入变成 ``SteerRun``，在下一个安全模型边界生效。"""

    def __init__(
        self,
        agent,
        run_id: str,
        context,
        renderer: EventRenderer,
        read_line: LineReader | None,
        *,
        json_frames: bool,
    ) -> None:
        self.agent = agent
        self.run_id = run_id
        self.context = context
        self.renderer = renderer
        self._read_line = read_line
        self.json_frames = json_frames
        self.turn_id: str | None = None
        self.pending: list[str] = []
        # 已提交待 steer.accepted 事件确认的文本（FIFO，与 inbox 顺序一致）
        self._awaiting_ack: list[str] = []
        self._accepted: dict[str, str] = {}  # steer_id -> text
        self._settled: set[str] = set()  # applied / rejected

    @property
    def enabled(self) -> bool:
        return self._read_line is not None

    def unapplied(self) -> tuple[str, ...]:
        return tuple(
            text for steer_id, text in self._accepted.items() if steer_id not in self._settled
        ) + tuple(self._awaiting_ack) + tuple(self.pending)

    async def read_line(self) -> str | None:
        assert self._read_line is not None
        return await self._read_line()

    def observe(self, event) -> None:
        if event.type == "turn.started" and event.turn_id:
            self.turn_id = event.turn_id
            pending, self.pending = self.pending, []
            for text in pending:
                asyncio.ensure_future(self.submit(text))
        elif event.type == "steer.accepted":
            text = self._awaiting_ack.pop(0) if self._awaiting_ack else ""
            self._accepted[event.data.steer_id] = text
        elif event.type in {"steer.applied", "steer.rejected"}:
            self._settled.add(event.data.steer_id)

    def parse(self, line: str) -> str | None:
        """把一行 stdin 解释成 steer 文本；不是 steer 的输入给出提示并丢弃。"""

        if self.json_frames:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                return None
            if not isinstance(payload, dict):
                return None
            if payload.get("type") == JSON_STEER_TYPE:
                text = str(payload.get("text") or "").strip()
                return text or None
            if payload.get("type") == JSON_DECISION_TYPE:
                self._report("rejected", "", "no interaction is pending")
            return None
        text = line.strip()
        if not text:
            return None
        if text.startswith("/"):
            self.renderer.notice(
                f"commands are not available while a run is active: {text}"
            )
            return None
        return text

    async def submit_line(self, line: str) -> None:
        text = self.parse(line)
        if text is not None:
            await self.submit(text)

    async def submit(self, text: str, *, attempts: int = STEER_CAS_ATTEMPTS) -> bool:
        if self.turn_id is None:
            # Turn 还没开始（run.accepted/queued 阶段）：等 turn.started 再发。
            self.pending.append(text)
            return False
        runtime = self.agent.runtime
        receipt = None
        for _ in range(attempts):
            current = await runtime.get_run(self.run_id)
            if current.state in TERMINAL_RUN_STATES:
                self._report("rejected", text, f"run is already {current.state.value}")
                return False
            receipt = await runtime.steer_run(
                SteerRun(
                    run_id=self.run_id,
                    expected_revision=current.revision,
                    expected_turn_id=self.turn_id,
                    input=(InputItem(role="user", content=(TextBlock(text=text),)),),
                    idempotency_key=new_id("cli_steer"),
                ),
                self.context,
            )
            if receipt.error is None:
                self._awaiting_ack.append(text)
                self._report("accepted", text, None)
                return True
            if receipt.error.category != ErrorCategory.CONFLICT:
                break
        code = receipt.error.code if receipt is not None and receipt.error else "?"
        self._report("rejected", text, code)
        return False

    def _report(self, status: str, text: str, detail: str | None) -> None:
        self.renderer.frame(
            {
                "type": "cli_v2_steer",
                "run_id": self.run_id,
                "status": status,
                "text": text,
                "detail": detail,
            }
        )


async def _finish(
    agent: SAgent,
    snapshot: RunSnapshot,
    renderer: EventRenderer,
    tracker: _EventTracker,
    canceller: "_InterruptCanceller",
    steerer: "_Steerer",
) -> RunOutcome:
    outcome = RunOutcome(
        run_id=snapshot.run_id,
        session_id=snapshot.session_id,
        state=snapshot.state,
        event_types=tracker.seen,
        interrupted=canceller.triggered,
        unapplied_steers=steerer.unapplied(),
    )
    for text in outcome.unapplied_steers:
        steerer._report("unapplied", text, "the run ended before its next model step")
    if snapshot.state in TERMINAL_RUN_STATES and not canceller.driver_pending:
        result = await agent.runtime.get_run_result(snapshot.run_id)
        outcome.final_text = final_assistant_text(result)
        outcome.error = result.error
    renderer.frame(
        {
            "type": "cli_v2_result",
            "run_id": outcome.run_id,
            "session_id": outcome.session_id,
            "state": outcome.state.value,
            "interrupted": outcome.interrupted,
            "final_text": outcome.final_text,
            "error": outcome.error.model_dump(mode="json") if outcome.error else None,
        }
    )
    return outcome


class _InterruptCanceller:
    """把用户中断翻译成一次幂等的 ``CancelRun``，并有限等待 driver 退出。"""

    def __init__(self, agent, run_id, context, renderer, interrupt) -> None:
        self.agent = agent
        self.run_id = run_id
        self.context = context
        self.renderer = renderer
        self.interrupt = interrupt
        self.triggered = False
        self.driver_pending = False
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self.interrupt is not None:
            self._task = asyncio.create_task(self._watch())

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _watch(self) -> None:
        assert self.interrupt is not None
        await self.interrupt.wait()
        self.triggered = True
        self.renderer.notice("cancelling run (press Ctrl-C again to force quit)")
        await self.cancel_run()

    async def cancel_run(self, *, attempts: int = CANCEL_CAS_ATTEMPTS) -> bool:
        """发 ``CancelRun``；revision 与 driver 的提交撞车时重读重试，直到终态或用尽次数。"""

        runtime = self.agent.runtime
        receipt = None
        for _ in range(attempts):
            current = await runtime.get_run(self.run_id)
            if current.state in TERMINAL_RUN_STATES:
                return True
            receipt = await runtime.cancel_run(
                CancelRun(
                    run_id=self.run_id,
                    expected_revision=current.revision,
                    idempotency_key=(
                        f"cli-interrupt:{self.run_id}:{current.revision}"
                    ),
                    reason=INTERRUPT_REASON,
                ),
                self.context,
            )
            if receipt.error is None:
                return True
        latest = await runtime.get_run(self.run_id)
        if latest.state in TERMINAL_RUN_STATES:
            return True
        code = receipt.error.code if receipt is not None and receipt.error else "?"
        self.renderer.notice(
            f"cancel was rejected after {attempts} attempts ({code}); "
            f"run is still {latest.state.value}"
        )
        return False

    async def wait_driver(self, waiter, grace_seconds: float) -> RunSnapshot:
        if not self.triggered:
            return await waiter
        try:
            return await asyncio.wait_for(waiter, timeout=grace_seconds)
        except asyncio.TimeoutError:
            self.driver_pending = True
            self.renderer.notice(
                "run is cancelled; the local driver is still finishing its current "
                "operation and will be abandoned on exit"
            )
            return await self.agent.runtime.get_run(self.run_id)


async def _answer_suspension(
    agent: SAgent,
    snapshot: RunSnapshot,
    context: RequestContext,
    *,
    decider: InteractionDecider,
    renderer: EventRenderer,
    abort: asyncio.Event | None = None,
) -> bool:
    """回答当前挂起的交互（或恢复一次手动暂停）；被中断时返回 False 交给上层。"""

    store = agent.runtime.session_store
    if snapshot.suspension_id is None:
        return False
    suspension = await store.get_suspension(snapshot.suspension_id)
    if suspension.interaction_id is None:
        return await _resume_manual_pause(agent, snapshot, suspension, context, renderer)
    interaction = await store.get_interaction(suspension.interaction_id)
    answer = await _decide_or_abort(decider, interaction, abort)
    if answer is None:
        return False
    receipt = await agent.runtime.reply_interaction(
        ReplyInteraction(
            run_id=snapshot.run_id,
            suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id,
            expected_revision=snapshot.revision,
            expected_suspension_revision=suspension.expected_revision,
            expected_interaction_revision=interaction.expected_revision,
            decision=answer.decision,
            payload=answer.payload,
            idempotency_key=new_id("cli_reply"),
        ),
        context,
    )
    if receipt.error is not None:
        latest = await agent.runtime.get_run(snapshot.run_id)
        if latest.state in TERMINAL_RUN_STATES:
            # 作答期间 Run 已到终态（典型：用户 Ctrl-C 取消），答案作废即可。
            return False
        raise CLIError(
            f"interaction reply was rejected: {receipt.error.code}",
            debug_detail=receipt.error.message,
        )
    return True


async def _resume_manual_pause(agent, snapshot, suspension, context, renderer) -> bool:
    """没有待答交互的挂起（手动暂停/上个进程留下的安全点）：显式 ResumeRun 后续跑。"""

    renderer.notice(f"resuming paused run {snapshot.run_id}")
    receipt = await agent.runtime.resume_run(
        ResumeRun(
            run_id=snapshot.run_id,
            suspension_id=suspension.suspension_id,
            expected_revision=snapshot.revision,
            expected_suspension_revision=suspension.expected_revision,
            idempotency_key=new_id("cli_resume"),
        ),
        context,
    )
    if receipt.error is not None:
        latest = await agent.runtime.get_run(snapshot.run_id)
        if latest.state in TERMINAL_RUN_STATES:
            return False
        raise CLIError(
            f"resume was rejected: {receipt.error.code}",
            debug_detail=receipt.error.message,
        )
    return True


async def _decide_or_abort(decider, interaction, abort: asyncio.Event | None):
    """等用户作答，但用户中断（Ctrl-C）时立刻放弃，不再等阻塞中的输入。"""

    if abort is None:
        return await decider.decide(interaction)
    if abort.is_set():
        return None
    answer_task = asyncio.ensure_future(decider.decide(interaction))
    abort_task = asyncio.ensure_future(abort.wait())
    try:
        done, _ = await asyncio.wait(
            {answer_task, abort_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if answer_task in done:
            return answer_task.result()
        return None
    finally:
        for task in (answer_task, abort_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(answer_task, abort_task, return_exceptions=True)
