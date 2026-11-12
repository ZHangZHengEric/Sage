"""Run a local voice conversation from microphone input to speech output."""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable, Collection, Iterable
from dataclasses import dataclass
from enum import StrEnum

from ..agent import VoiceAgent
from ..asr import ASR, ASRResult
from ..audio import AudioError, AudioFormatError, AudioIO
from ..observability import (
    Component,
    ComponentEvent,
    ComponentState,
    ErrorEvent,
    InputSource,
    MetricsEvent,
    SessionEvent,
    SessionState,
    TranscriptEvent,
    TurnEvent,
    TurnState,
    UserInputEvent,
    VoiceEvent,
    VoiceObserver,
)
from ..observability._dispatcher import _EventDispatcher
from ..tts import TTS
from ..turn_detection import TurnAnalyzer
from ..vad import VAD, AdaptiveInputLevelGate
from ._voice_input import (
    _DroppedVoiceInput,
    _VoiceInput,
    _VoiceInputProcessor,
    _VoiceInputResult,
)
from .turn import _TurnFailure, _TurnRunner

_Close = Callable[[], Awaitable[None]]


def _opening_prompt() -> str:
    return (
        "Begin the conversation proactively according to the system instructions. "
        "Do not mention this internal trigger or its implementation details."
    )


def _proactive_prompt(instruction: str) -> str:
    return (
        "The user explicitly accepted a proactive conversation request. "
        "Begin the conversation naturally and follow the instruction below. "
        "Do not mention this internal request or its implementation details.\n\n"
        "Instruction:\n"
        f"{instruction}"
    )


def _followup_prompt(attempt: int, maximum: int) -> str:
    return (
        "The user has not responded during the current listening period. "
        "Briefly ask them a natural, context-aware question to re-engage them. "
        f"This is attempt {attempt} of {maximum}. "
        "Do not mention the timer or attempt count."
    )


def _farewell_prompt() -> str:
    return (
        "The user has not responded after the final follow-up. "
        "Briefly and naturally end the conversation without asking another question. "
        "Do not mention timers, attempts, or internal instructions."
    )


@dataclass(frozen=True, slots=True)
class _TextInput:
    text: str
    source: InputSource
    submitted_at: float


_TurnInput = _VoiceInputResult | _TextInput


class InactivityAction(StrEnum):
    """Action after all inactivity follow-ups receive no response."""

    WAIT = "wait"
    STOP = "stop"
    FAREWELL = "farewell"


@dataclass(frozen=True, slots=True, kw_only=True)
class ConversationInactivityPolicy:
    """Behavior when a listening session receives no user input."""

    timeout_seconds: float
    max_followups: int
    on_exhausted: InactivityAction = InactivityAction.WAIT

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if self.max_followups <= 0:
            raise ValueError("max_followups must be greater than zero")


class VoiceSession:
    """Run continuous interruptible voice turns with managed resources."""

    def __init__(
        self,
        *,
        audio: AudioIO,
        vad: VAD,
        turn_analyzer: TurnAnalyzer,
        asr: ASR,
        agent: VoiceAgent,
        tts: TTS,
        observers: Iterable[VoiceObserver] = (),
        opening_enabled: bool = False,
        inactivity_policy: ConversationInactivityPolicy | None = None,
        input_level_gate: AdaptiveInputLevelGate | None = None,
        incomplete_turn_timeout_seconds: float = 3.0,
        backchannel_filter_enabled: bool = True,
        backchannel_phrases: Collection[str] | None = None,
        tool_speech: dict | None = None,
    ) -> None:
        """Store conversation components without starting external resources."""

        if audio.output_format != tts.output_format:
            raise AudioFormatError(
                f"VoiceSession audio output requires {tts.output_format!r}, "
                f"received {audio.output_format!r}"
            )
        if incomplete_turn_timeout_seconds <= 0:
            raise ValueError(
                "incomplete_turn_timeout_seconds must be greater than zero"
            )

        self._audio = audio
        self._vad = vad
        self._turn_analyzer = turn_analyzer
        self._asr = asr
        self._agent = agent
        self._tts = tts
        self._tool_speech = tool_speech
        self._session_id = uuid.uuid4().hex
        self._events = _EventDispatcher(observers)
        self._opening_enabled = opening_enabled
        self._inactivity_policy = inactivity_policy
        self._input_level_gate = input_level_gate
        self._incomplete_turn_timeout_seconds = incomplete_turn_timeout_seconds

        self._inputs: asyncio.Queue[_TurnInput] = asyncio.Queue(maxsize=1)
        self._active_turn: _TurnRunner | None = None
        self._voice_input = _VoiceInputProcessor(
            audio=self._audio,
            vad=self._vad,
            turn_analyzer=self._turn_analyzer,
            asr=self._asr,
            session_id=self._session_id,
            emit=self._emit,
            report_error=self._emit_error,
            submit=self._inputs.put,
            on_speech_started=self.interrupt,
            playback_active=self._playback_active,
            input_level_gate=self._input_level_gate,
            incomplete_turn_timeout_seconds=(self._incomplete_turn_timeout_seconds),
            backchannel_filter_enabled=backchannel_filter_enabled,
            backchannel_phrases=backchannel_phrases,
        )
        self._input_task: asyncio.Task[None] | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._turn_id = 0
        self._started_closers: list[tuple[Component, _Close]] = []
        self._reported_errors: list[BaseException] = []
        self._accepting_inputs = False
        self._stop_after_turn = asyncio.Event()
        self._stop_after_turn_owner: _TurnRunner | None = None
        self._stop_requested = False
        self._finishing = False
        self._used = False

    @property
    def session_id(self) -> str:
        """Opaque identifier included in every emitted event."""

        return self._session_id

    async def run(self) -> None:
        """Start components and run turns until cancelled or an error occurs."""

        if self._used:
            raise RuntimeError("VoiceSession can only be run once")
        self._used = True
        self._run_task = asyncio.current_task()
        self._events.start()
        self._emit(
            SessionEvent(session_id=self._session_id, state=SessionState.STARTING)
        )

        try:
            await self._start_components()
            self._input_task = asyncio.create_task(
                self._voice_input.run(),
                name="lalk-voice-input",
            )
            self._accepting_inputs = True
            self._emit(
                SessionEvent(session_id=self._session_id, state=SessionState.READY)
            )
            await self._run_conversation()
        except asyncio.CancelledError:
            await self._finish(suppress_errors=True)
            if not self._stop_requested:
                raise
        except BaseException as error:
            self._emit_error(
                component=Component.SESSION,
                operation="run",
                error=error,
                fatal=True,
            )
            await self._finish(suppress_errors=True)
            raise
        else:
            await self._finish(suppress_errors=False)
        finally:
            self._accepting_inputs = False
            self._run_task = None

    async def stop(self) -> None:
        """Stop the session and wait for its resources to close."""

        task = self._run_task
        if task is None:
            return
        self._accepting_inputs = False
        if not self._stop_requested and not self._finishing:
            self._stop_requested = True
            task.cancel()
        await asyncio.shield(task)

    def interrupt(self) -> bool:
        """Interrupt the active assistant turn, if one is running."""

        turn = self._active_turn
        if turn is None:
            return False
        return turn.interrupt()

    def _playback_active(self) -> bool:
        turn = self._active_turn
        return turn is not None and turn.playback_active

    def request_stop_after_turn(self) -> None:
        """Finish the active turn, then close the voice session normally."""

        self._stop_after_turn_owner = self._active_turn
        self._stop_after_turn.set()

    def submit_text(self, text: str) -> None:
        """Interrupt an active reply and queue one text input."""

        if not self._accepting_inputs:
            raise RuntimeError("VoiceSession is not ready")
        if not text.strip():
            raise ValueError("Text input must not be empty")
        turn = self._active_turn
        item = _TextInput(text, InputSource.TEXT, time.perf_counter())
        try:
            self._inputs.put_nowait(item)
        except asyncio.QueueFull:
            queued = self._inputs.get_nowait()
            if turn is not None and isinstance(
                queued,
                (_VoiceInput, _DroppedVoiceInput),
            ):
                self._inputs.put_nowait(item)
            else:
                self._inputs.put_nowait(queued)
                raise
        if turn is not None:
            turn.interrupt()

    def submit_proactive(self, instruction: str) -> None:
        """Queue an agent-initiated turn only while the session is idle."""

        if not self._accepting_inputs:
            raise RuntimeError("VoiceSession is not ready")
        if not instruction.strip():
            raise ValueError("Proactive instruction must not be empty")
        if (
            self._voice_input.in_progress
            or self._active_turn is not None
            or not self._inputs.empty()
        ):
            raise RuntimeError("VoiceSession is busy")

        self._inputs.put_nowait(
            _TextInput(
                _proactive_prompt(instruction),
                InputSource.PROACTIVE,
                time.perf_counter(),
            )
        )

    async def _run_conversation(self) -> None:
        followups = 0
        awaiting_user_response = False
        if self._opening_enabled:
            state = await self._run_turn(
                _opening_prompt(),
                source=InputSource.OPENING,
                prompt_ready_at=time.perf_counter(),
            )
            awaiting_user_response = state is TurnState.COMPLETED

        while not self._stop_after_turn.is_set():
            policy = self._inactivity_policy
            exhausted = policy is not None and followups >= policy.max_followups
            timeout = (
                policy.timeout_seconds
                if policy is not None
                and awaiting_user_response
                and not (exhausted and policy.on_exhausted is InactivityAction.WAIT)
                else None
            )
            turn_input = await self._next_input(inactivity_seconds=timeout)
            if self._stop_after_turn.is_set():
                return
            if turn_input is None:
                assert policy is not None
                if not exhausted:
                    followups += 1
                    await self._run_turn(
                        _followup_prompt(followups, policy.max_followups),
                        source=InputSource.FOLLOWUP,
                        prompt_ready_at=time.perf_counter(),
                    )
                    continue
                if policy.on_exhausted is InactivityAction.STOP:
                    return
                state = await self._run_turn(
                    _farewell_prompt(),
                    source=InputSource.FOLLOWUP,
                    prompt_ready_at=time.perf_counter(),
                )
                if state is not TurnState.INTERRUPTED:
                    return
                continue

            if isinstance(turn_input, _TextInput):
                followups = 0
                awaiting_user_response = False
                state = await self._run_turn(
                    turn_input.text,
                    source=turn_input.source,
                    prompt_ready_at=turn_input.submitted_at,
                )
                awaiting_user_response = state is TurnState.COMPLETED
                continue

            resume_waiting_after_unrecognized_voice = awaiting_user_response
            followups = 0
            awaiting_user_response = False
            if (
                isinstance(turn_input, _DroppedVoiceInput)
                or not turn_input.text.strip()
            ):
                self._emit(
                    TranscriptEvent(
                        session_id=self._session_id,
                        text="",
                        is_final=True,
                    )
                )
                awaiting_user_response = resume_waiting_after_unrecognized_voice
                continue

            self._emit(
                TranscriptEvent(
                    session_id=self._session_id,
                    text=turn_input.text,
                    is_final=True,
                    language=turn_input.language,
                )
            )
            state = await self._run_turn(
                turn_input.text,
                source=InputSource.VOICE,
                prompt_ready_at=turn_input.asr_finished_at,
                speech_stopped_at=turn_input.speech_stopped_at,
                estimated_speech_ended_at=turn_input.estimated_speech_ended_at,
                turn_decided_at=turn_input.turn_decided_at,
                asr_finished_at=turn_input.asr_finished_at,
                asr_result=turn_input.asr_result,
            )
            awaiting_user_response = state is TurnState.COMPLETED

    async def _next_input(
        self,
        *,
        inactivity_seconds: float | None = None,
    ) -> _TurnInput | None:
        input_task = self._input_task
        if input_task is None:
            raise RuntimeError("VoiceSession voice input is not running")

        receive = asyncio.create_task(
            self._inputs.get(),
            name="lalk-next-input",
        )
        stop_after_turn = asyncio.create_task(
            self._stop_after_turn.wait(),
            name="lalk-wait-stop-after-turn",
        )
        speech_started = (
            asyncio.create_task(
                self._voice_input.speech_started.wait(),
                name="lalk-wait-speech-start",
            )
            if inactivity_seconds is not None
            else None
        )
        timer = (
            asyncio.create_task(
                asyncio.sleep(inactivity_seconds),
                name="lalk-inactivity-timeout",
            )
            if inactivity_seconds is not None
            else None
        )
        try:
            pending = {receive, input_task, stop_after_turn}
            if speech_started is not None:
                pending.add(speech_started)
            if timer is not None:
                pending.add(timer)
            done, _ = await asyncio.wait(
                pending,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if input_task in done:
                await input_task
                raise RuntimeError("Voice input stopped unexpectedly")
            if stop_after_turn in done:
                return None
            if receive in done:
                turn_input = receive.result()
            elif speech_started is not None and speech_started in done:
                done, _ = await asyncio.wait(
                    {receive, input_task, stop_after_turn},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if input_task in done:
                    await input_task
                    raise RuntimeError("Voice input stopped unexpectedly")
                if stop_after_turn in done:
                    return None
                turn_input = receive.result()
            else:
                return None

            return turn_input
        finally:
            waiters = tuple(
                waiter
                for waiter in (receive, stop_after_turn, speech_started, timer)
                if waiter is not None
            )
            for waiter in waiters:
                if not waiter.done():
                    waiter.cancel()
            for waiter in waiters:
                await asyncio.gather(waiter, return_exceptions=True)

    async def _run_turn(
        self,
        prompt: str,
        *,
        source: InputSource,
        prompt_ready_at: float,
        speech_stopped_at: float | None = None,
        estimated_speech_ended_at: float | None = None,
        turn_decided_at: float | None = None,
        asr_finished_at: float | None = None,
        asr_result: ASRResult | None = None,
    ) -> TurnState:
        self._turn_id += 1
        turn_id = self._turn_id
        self._emit(
            UserInputEvent(
                session_id=self._session_id,
                turn_id=turn_id,
                source=source,
                text=prompt,
            )
        )
        self._emit(
            TurnEvent(
                session_id=self._session_id,
                turn_id=turn_id,
                state=TurnState.STARTED,
            )
        )
        runner = _TurnRunner(
            prompt=prompt,
            audio=self._audio,
            agent=self._agent,
            tts=self._tts,
            session_id=self._session_id,
            turn_id=turn_id,
            emit=self._emit,
            prompt_ready_at=prompt_ready_at,
            speech_stopped_at=speech_stopped_at,
            estimated_speech_ended_at=estimated_speech_ended_at,
            turn_decided_at=turn_decided_at,
            asr_finished_at=asr_finished_at,
            asr_result=asr_result,
            tool_speech=self._tool_speech,
        )
        self._active_turn = runner
        task = asyncio.create_task(
            runner.run(),
            name=f"lalk-turn-{turn_id}",
        )
        input_task = self._input_task
        if input_task is None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise RuntimeError("VoiceSession voice input is not running")

        try:
            done, _ = await asyncio.wait(
                {task, input_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if input_task in done:
                await input_task
                raise RuntimeError("Voice input stopped unexpectedly")

            try:
                interrupted = await task
            except _TurnFailure as failure:
                self._emit(
                    TurnEvent(
                        session_id=self._session_id,
                        turn_id=turn_id,
                        state=TurnState.FAILED,
                    )
                )
                self._emit(
                    MetricsEvent(
                        session_id=self._session_id,
                        turn_id=turn_id,
                        metrics=runner.metrics(),
                    )
                )
                self._emit_error(
                    component=failure.component,
                    operation=failure.operation,
                    error=failure.error,
                    fatal=failure.fatal,
                    turn_id=turn_id,
                )
                if failure.fatal:
                    raise failure.error from failure
                return TurnState.FAILED
            except AudioError as error:
                self._emit(
                    TurnEvent(
                        session_id=self._session_id,
                        turn_id=turn_id,
                        state=TurnState.FAILED,
                    )
                )
                self._emit_error(
                    component=Component.AUDIO,
                    operation="playback",
                    error=error,
                    fatal=True,
                    turn_id=turn_id,
                )
                raise
            except Exception as error:
                self._emit(
                    TurnEvent(
                        session_id=self._session_id,
                        turn_id=turn_id,
                        state=TurnState.FAILED,
                    )
                )
                self._emit_error(
                    component=Component.SESSION,
                    operation="turn",
                    error=error,
                    fatal=True,
                    turn_id=turn_id,
                )
                raise

            state = TurnState.INTERRUPTED if interrupted else TurnState.COMPLETED

            if (
                state is not TurnState.COMPLETED
                and self._stop_after_turn_owner is runner
            ):
                self._stop_after_turn_owner = None
                self._stop_after_turn.clear()

            self._emit(
                TurnEvent(
                    session_id=self._session_id,
                    turn_id=turn_id,
                    state=state,
                )
            )
            self._emit(
                MetricsEvent(
                    session_id=self._session_id,
                    turn_id=turn_id,
                    metrics=runner.metrics(),
                )
            )
            return state
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if self._active_turn is runner:
                self._active_turn = None

    async def _start_components(self) -> None:
        await self._start_component(
            Component.VAD,
            lambda: self._vad.start(self._audio.input_format),
            self._vad.close,
        )
        await self._start_component(
            Component.TURN_DETECTION,
            lambda: self._turn_analyzer.start(self._audio.input_format),
            self._turn_analyzer.close,
        )
        await self._start_component(
            Component.ASR,
            lambda: self._asr.start(self._audio.input_format),
            self._asr.close,
        )
        await self._start_component(
            Component.AGENT,
            self._agent.start,
            self._agent.close,
        )
        await self._start_component(
            Component.TTS,
            self._tts.start,
            self._tts.close,
        )
        await self._start_component(
            Component.AUDIO,
            self._audio.start,
            self._audio.close,
        )

    async def _start_component(
        self,
        component: Component,
        start: Callable[[], Awaitable[None]],
        close: _Close,
    ) -> None:
        self._emit(
            ComponentEvent(
                session_id=self._session_id,
                component=component,
                state=ComponentState.STARTING,
            )
        )
        started_at = time.perf_counter()
        self._started_closers.append((component, close))
        try:
            await start()
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            elapsed = _duration_ms(started_at, time.perf_counter())
            self._emit(
                ComponentEvent(
                    session_id=self._session_id,
                    component=component,
                    state=ComponentState.FAILED,
                    elapsed_ms=elapsed,
                )
            )
            self._emit_error(
                component=component,
                operation="start",
                error=error,
                fatal=True,
            )
            raise
        self._emit(
            ComponentEvent(
                session_id=self._session_id,
                component=component,
                state=ComponentState.READY,
                elapsed_ms=_duration_ms(started_at, time.perf_counter()),
            )
        )

    async def _finish(self, *, suppress_errors: bool) -> None:
        self._finishing = True
        self._accepting_inputs = False
        self._emit(
            SessionEvent(session_id=self._session_id, state=SessionState.STOPPING)
        )
        try:
            await self._shutdown(suppress_errors=suppress_errors)
        except BaseException as error:
            self._emit_error(
                component=Component.SESSION,
                operation="shutdown",
                error=error,
                fatal=True,
            )
            self._emit(
                SessionEvent(session_id=self._session_id, state=SessionState.STOPPED)
            )
            await self._events.close()
            raise
        self._emit(
            SessionEvent(session_id=self._session_id, state=SessionState.STOPPED)
        )
        await self._events.close()

    async def _shutdown(self, *, suppress_errors: bool) -> None:
        input_task = self._input_task
        self._input_task = None
        if input_task is not None:
            if not input_task.done():
                input_task.cancel()
            await asyncio.gather(input_task, return_exceptions=True)

        await self._close_components(suppress_errors=suppress_errors)

    async def _close_components(self, *, suppress_errors: bool) -> None:
        closers = tuple(reversed(self._started_closers))
        self._started_closers.clear()
        await self._close_all(closers, suppress_errors=suppress_errors)

    async def _close_all(
        self,
        closers: Iterable[tuple[Component, _Close]],
        *,
        suppress_errors: bool,
    ) -> None:
        errors: list[Exception] = []
        for component, close in closers:
            try:
                await close()
            except Exception as error:  # noqa: BLE001 - remaining resources must still close
                errors.append(error)
                self._emit_error(
                    component=component,
                    operation="close",
                    error=error,
                    fatal=not suppress_errors,
                )

        if errors and not suppress_errors:
            raise errors[0]

    def _emit(self, event: VoiceEvent) -> None:
        self._events.emit(event)

    def _emit_error(
        self,
        *,
        component: Component,
        operation: str,
        error: BaseException,
        fatal: bool,
        turn_id: int | None = None,
    ) -> None:
        if any(reported is error for reported in self._reported_errors):
            return
        self._reported_errors.append(error)
        self._emit(
            ErrorEvent(
                session_id=self._session_id,
                component=component,
                operation=operation,
                message=str(error),
                error_type=type(error).__name__,
                fatal=fatal,
                turn_id=turn_id,
            )
        )


def _duration_ms(start: float, end: float) -> float:
    return round(max(end - start, 0) * 1_000, 1)
