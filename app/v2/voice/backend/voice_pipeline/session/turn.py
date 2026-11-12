"""Run one interruptible Sage response through TTS and audio output."""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace

from ..agent import AgentTurn, ToolActivity, VoiceAgent
from ..asr import ASRResult
from ..audio import AudioChunk, AudioError, AudioIO
from ..observability import (
    AgentTextEvent,
    Component,
    PlaybackEvent,
    PlaybackState,
    SynthesisEvent,
    SynthesisState,
    TurnMetrics,
    VoiceEvent,
)
from ..observability._turn_tracker import _TurnMetricsTracker
from ..observability.events import ProgressSpeechEvent
from ..tool_speech import tool_speech_text
from ..tts import (
    TTS,
    StreamingTextProcessor,
    TTSResult,
    TTSStream,
    TTSTextMark,
)

_PLAYBACK_PROGRESS_INTERVAL_SECONDS = 0.05
_TOOL_PROGRESS_DELAY = 1.2
_SILENCE_PROGRESS_DELAY = 4.0
_PlaybackItem = AudioChunk | None


@dataclass(frozen=True, slots=True)
class _ProgressCue:
    text: str
    call_id: str | None = None


class _TurnFailure(Exception):
    """Failure classified at the component boundary of one turn."""

    def __init__(
        self,
        *,
        component: Component,
        operation: str,
        error: Exception,
        fatal: bool,
    ) -> None:
        super().__init__(str(error))
        self.component = component
        self.operation = operation
        self.error = error
        self.fatal = fatal


class _PlaybackTracker:
    """Map TTS text marks onto output progress for one synthesis stream."""

    def __init__(self, audio: AudioIO) -> None:
        self._audio = audio
        self._start_frame = audio.played_frames
        self._marks: list[TTSTextMark] = []
        self._submitted: list[str] = []
        self.progress_text: str | None = None

    def submit(self, text: str) -> None:
        self._submitted.append(text)

    def mark(self, mark: TTSTextMark) -> None:
        self._marks.append(mark)

    @property
    def spoken_text(self) -> str:
        """Return text confirmed by provider marks and output progress."""

        return self._spoken_text()

    @property
    def submitted_text(self) -> str:
        """Return all text submitted to synthesis in response order."""

        return "".join(self._submitted)

    @property
    def played_frames(self) -> int:
        """Output frames confirmed as played during this turn."""

        return max(self._audio.played_frames - self._start_frame, 0)

    def _spoken_text(self) -> str:
        played = self.played_frames
        if played <= 0:
            return ""
        spoken = "".join(mark.text for mark in self._marks if mark.at_frame <= played)
        if self.progress_text is None:
            return spoken
        # Provider marks can omit punctuation or whitespace from the cue.
        prefix = iter(char.casefold() for char in self.progress_text if char.isalnum())
        for index, char in enumerate(spoken):
            if not char.isalnum():
                continue
            expected = next(prefix, None)
            if expected is None:
                return spoken[index:]
            if char.casefold() != expected:
                break
        return ""


class _TurnRunner:
    """Coordinate the streamed response, synthesis, and playback of one turn."""

    def __init__(
        self,
        *,
        prompt: str,
        audio: AudioIO,
        agent: VoiceAgent,
        tts: TTS,
        session_id: str,
        turn_id: int,
        emit: Callable[[VoiceEvent], None],
        prompt_ready_at: float,
        speech_stopped_at: float | None = None,
        estimated_speech_ended_at: float | None = None,
        turn_decided_at: float | None = None,
        asr_finished_at: float | None = None,
        asr_result: ASRResult | None = None,
        tool_speech: dict | None = None,
    ) -> None:
        self._prompt = prompt
        self._audio = audio
        self._agent = agent
        self._tts = tts
        self._session_id = session_id
        self._turn_id = turn_id
        self._emit = emit
        self._metrics = _TurnMetricsTracker(
            prompt_ready_at=prompt_ready_at,
            speech_stopped_at=speech_stopped_at,
            estimated_speech_ended_at=estimated_speech_ended_at,
            turn_decided_at=turn_decided_at,
            asr_finished_at=asr_finished_at,
            asr_result=asr_result,
        )

        self._playback = _PlaybackTracker(audio)
        self._tts_input: asyncio.Queue[str | _ProgressCue | None] = asyncio.Queue()
        self._tool_speech = tool_speech or {}
        self._tool_timers: dict[str, asyncio.TimerHandle] = {}
        self._has_agent_text = False
        self._agent_finished = False
        self._chinese_prompt = any("\u4e00" <= char <= "\u9fff" for char in prompt)
        # Provider marks can arrive behind audio, so device backpressure must not
        # stop the TTS stream from reaching them.
        self._playback_items: asyncio.Queue[_PlaybackItem] = asyncio.Queue()
        self._interruption = asyncio.Event()

        self._turn: AgentTurn | None = None
        self._tts_stream: TTSStream | None = None
        self._agent_task: asyncio.Task[None] | None = None
        self._tts_task: asyncio.Task[None] | None = None
        self._playback_task: asyncio.Task[None] | None = None
        self._playback_progress_task: asyncio.Task[None] | None = None

        self._synthesis_started_at: float | None = None
        self._synthesis_terminal = False
        self._received_first_audio = False
        self._playback_started = False
        self._playback_active = False
        self._last_spoken_text = ""

    @property
    def playback_active(self) -> bool:
        """Whether assistant audio has started and not reached a terminal state."""

        return self._playback_active

    def interrupt(self) -> bool:
        """Request interruption without blocking microphone capture."""

        if self._interruption.is_set():
            return False
        self._metrics.mark_interruption_requested()
        self._interruption.set()
        return True

    def metrics(self) -> TurnMetrics:
        """Build a final timing and usage snapshot for this turn."""

        metrics = self._metrics.snapshot()
        if self._playback.progress_text is not None:
            return replace(
                metrics,
                progress_cue=True,
                text_aggregation_ms=None,
                speech_first_playback_ms=None,
            )
        return metrics

    async def run(self) -> bool:
        """Return whether playback was interrupted."""
        try:
            self._turn = self._agent.stream(self._prompt)
        except Exception as error:
            raise _TurnFailure(
                component=Component.AGENT,
                operation="stream",
                error=error,
                fatal=False,
            ) from error

        self._agent_task = asyncio.create_task(
            self._consume_agent(),
            name="lalk-agent-turn",
        )
        self._playback_task = asyncio.create_task(
            self._play_audio(),
            name="lalk-audio-playback",
        )
        self._tts_task = asyncio.create_task(
            self._consume_tts(),
            name="lalk-tts-stream",
        )
        completion = asyncio.create_task(
            self._complete(),
            name="lalk-turn-completion",
        )
        interruption = asyncio.create_task(
            self._interruption.wait(),
            name="lalk-turn-interruption",
        )
        outcome_ready = False

        try:
            done, _ = await asyncio.wait(
                {completion, interruption},
                return_when=asyncio.FIRST_COMPLETED,
            )
            interrupted = completion not in done
            if interrupted:
                await self._interrupt_turn()
            else:
                await asyncio.shield(completion)
            outcome_ready = True
            return interrupted
        except asyncio.CancelledError:
            if self._playback_active:
                await self._interrupt_turn()
            raise
        except BaseException as error:
            try:
                await self._fail_playback()
            except BaseException as playback_error:
                raise playback_error from error
            raise
        finally:
            interruption.cancel()
            await asyncio.gather(interruption, return_exceptions=True)
            try:
                await self._close(suppress_errors=not outcome_ready)
            finally:
                await asyncio.gather(completion, return_exceptions=True)

    async def _consume_agent(self) -> None:
        fallback = asyncio.get_running_loop().call_later(
            _SILENCE_PROGRESS_DELAY,
            self._queue_progress,
            _ProgressCue(
                "我还在处理。" if self._chinese_prompt else "I'm still working on it."
            ),
        )
        try:
            async for delta in self._require_turn():
                if self._interruption.is_set():
                    return
                if isinstance(delta, ToolActivity):
                    self._track_tool(delta)
                    continue
                if not delta:
                    continue
                if delta.strip():
                    self._has_agent_text = True
                self._metrics.mark_agent_text()
                self._emit(
                    AgentTextEvent(
                        session_id=self._session_id, turn_id=self._turn_id, delta=delta
                    )
                )
                self._tts_input.put_nowait(delta)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise _TurnFailure(
                component=Component.AGENT,
                operation="stream",
                error=error,
                fatal=False,
            ) from error
        finally:
            self._agent_finished = True
            fallback.cancel()
            for timer in self._tool_timers.values():
                timer.cancel()
            self._tool_timers.clear()
            self._tts_input.put_nowait(None)

    def _track_tool(self, activity: ToolActivity) -> None:
        if not activity.running:
            timer = self._tool_timers.pop(activity.call_id, None)
            if timer is not None:
                timer.cancel()
            return
        if activity.call_id in self._tool_timers or self._has_agent_text:
            return
        phrase = tool_speech_text(
            activity.name,
            activity.target,
            chinese=self._chinese_prompt,
            overrides=self._tool_speech,
        )
        if phrase:
            self._tool_timers[activity.call_id] = asyncio.get_running_loop().call_later(
                _TOOL_PROGRESS_DELAY,
                self._queue_progress,
                _ProgressCue(phrase, activity.call_id),
            )

    def _queue_progress(self, cue: _ProgressCue) -> None:
        if (
            self._playback.progress_text is None
            and not self._has_agent_text
            and not self._interruption.is_set()
        ):
            self._tts_input.put_nowait(cue)

    async def _consume_tts(self) -> None:
        try:
            text = self._stream_tts_text()
            first = await anext(text, None)
            if first is None:
                self._playback_items.put_nowait(None)
                return

            async def speakable_text() -> AsyncIterator[str]:
                yield first
                async for part in text:
                    yield part

            tts_stream = self._tts.synthesize(speakable_text())
            self._tts_stream = tts_stream
            async for output in tts_stream:
                if isinstance(output, TTSTextMark):
                    self._playback.mark(output)
                    self._emit_playback_progress()
                    continue
                if not isinstance(output, AudioChunk):
                    raise TypeError(f"Unsupported TTS output: {type(output).__name__}")
                if self._interruption.is_set():
                    continue
                self._metrics.mark_tts_audio()
                if not self._received_first_audio:
                    self._received_first_audio = True
                    self._emit_synthesis(SynthesisState.FIRST_AUDIO)
                self._playback_items.put_nowait(output)

            result = await tts_stream.result()
            self._record_tts_result(result)
            if not result.completed:
                raise RuntimeError("TTS synthesis did not complete")
            self._finish_synthesis(SynthesisState.FINISHED)
            self._playback_items.put_nowait(None)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._finish_synthesis(SynthesisState.FAILED)
            raise _TurnFailure(
                component=Component.TTS,
                operation="synthesize",
                error=error,
                fatal=False,
            ) from error

    async def _play_audio(self) -> None:
        try:
            while True:
                item = await self._playback_items.get()
                if item is None:
                    break
                if self._interruption.is_set():
                    continue
                if not self._playback_started:
                    self._playback_started = True
                    self._playback_active = True
                    self._emit(
                        PlaybackEvent(
                            session_id=self._session_id,
                            turn_id=self._turn_id,
                            state=PlaybackState.STARTED,
                        )
                    )
                    self._start_playback_progress()
                await self._audio.write(item)
                self._emit_playback_progress()

            await self._audio.wait_for_playback()
            await self._stop_playback_progress()
            self._emit_playback_progress()
            self._emit_playback_terminal(
                PlaybackState.FINISHED,
                self._playback.submitted_text,
            )
        except asyncio.CancelledError:
            raise
        except AudioError:
            raise
        except Exception as error:
            raise AudioError(f"Audio playback failed: {error}") from error

    async def _stream_tts_text(self) -> AsyncIterator[str]:
        processor = StreamingTextProcessor()
        while True:
            item = await self._tts_input.get()
            if isinstance(item, _ProgressCue):
                if (
                    not self._has_agent_text
                    and not self._agent_finished
                    and not self._interruption.is_set()
                    and self._playback.progress_text is None
                    and (item.call_id is None or item.call_id in self._tool_timers)
                ):
                    self._playback.progress_text = item.text
                    self._record_first_tts_text()
                    self._emit(
                        ProgressSpeechEvent(
                            session_id=self._session_id,
                            turn_id=self._turn_id,
                            text=item.text,
                        )
                    )
                    yield item.text
                continue
            parts = processor.flush() if item is None else processor.push(item)
            for text in parts:
                self._record_first_tts_text()
                self._playback.submit(text)
                yield text
            if item is None:
                return

    async def _complete(self) -> None:
        await asyncio.gather(
            self._require_agent_task(),
            self._require_tts_task(),
            self._require_playback_task(),
        )

    async def _interrupt_turn(self) -> None:
        await self._audio.interrupt_playback()
        await self._stop_playback_progress()
        self._metrics.mark_interruption_finished()
        self._emit_playback_terminal(
            PlaybackState.INTERRUPTED,
            self._playback.spoken_text,
        )
        self._finish_synthesis(SynthesisState.INTERRUPTED)

    async def _fail_playback(self) -> None:
        if not self._playback_started:
            return
        await self._audio.interrupt_playback()
        await self._stop_playback_progress()
        self._emit_playback_terminal(
            PlaybackState.FAILED,
            self._playback.spoken_text,
        )

    def _record_first_tts_text(self) -> None:
        self._metrics.mark_tts_text()
        if self._synthesis_started_at is None:
            self._synthesis_started_at = time.perf_counter()
            self._emit_synthesis(SynthesisState.STARTED)

    def _emit_synthesis(self, state: SynthesisState) -> None:
        started_at = self._synthesis_started_at
        if started_at is None:
            return
        self._emit(
            SynthesisEvent(
                session_id=self._session_id,
                turn_id=self._turn_id,
                state=state,
                elapsed_ms=(
                    0.0
                    if state is SynthesisState.STARTED
                    else _duration_ms(started_at, time.perf_counter())
                ),
            )
        )

    def _finish_synthesis(self, state: SynthesisState) -> None:
        if self._synthesis_started_at is None or self._synthesis_terminal:
            return
        self._synthesis_terminal = True
        self._emit_synthesis(state)

    def _record_tts_result(self, result: TTSResult) -> None:
        self._metrics.set_tts_usage(
            provider_usage=result.provider_usage,
            input_characters=result.input_characters,
            audio_bytes=result.audio_bytes,
        )

    def _start_playback_progress(self) -> None:
        if self._playback_progress_task is None:
            self._playback_progress_task = asyncio.create_task(
                self._monitor_playback_progress(),
                name="lalk-playback-progress",
            )

    async def _monitor_playback_progress(self) -> None:
        while True:
            self._emit_playback_progress()
            await asyncio.sleep(_PLAYBACK_PROGRESS_INTERVAL_SECONDS)

    async def _stop_playback_progress(self) -> None:
        task = self._playback_progress_task
        if task is None:
            return
        self._playback_progress_task = None
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    def _emit_playback_progress(self) -> None:
        self._record_first_playback()
        spoken = self._playback.spoken_text
        if (
            not spoken.startswith(self._last_spoken_text)
            or spoken == self._last_spoken_text
        ):
            return
        delta = spoken[len(self._last_spoken_text) :]
        self._last_spoken_text = spoken
        self._emit(
            PlaybackEvent(
                session_id=self._session_id,
                turn_id=self._turn_id,
                state=PlaybackState.PROGRESS,
                spoken_text=spoken,
                delta=delta,
            )
        )

    def _emit_playback_terminal(self, state: PlaybackState, spoken: str) -> None:
        self._playback_active = False
        self._record_first_playback()
        delta = ""
        if spoken.startswith(self._last_spoken_text):
            delta = spoken[len(self._last_spoken_text) :]
        self._last_spoken_text = spoken
        self._emit(
            PlaybackEvent(
                session_id=self._session_id,
                turn_id=self._turn_id,
                state=state,
                spoken_text=spoken,
                delta=delta,
            )
        )

    def _record_first_playback(self) -> None:
        if self._playback.played_frames > 0:
            self._metrics.mark_playback()

    async def _close(self, *, suppress_errors: bool) -> None:
        await self._stop_playback_progress()
        for task in (self._tts_task, self._playback_task, self._agent_task):
            if task is not None and not task.done():
                task.cancel()

        async def close_stream(task, stream) -> None:
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            if stream is not None:
                await stream.aclose()

        errors = await asyncio.gather(
            close_stream(self._tts_task, self._tts_stream),
            close_stream(self._agent_task, self._turn),
            close_stream(self._playback_task, None),
            return_exceptions=True,
        )

        self._finish_synthesis(SynthesisState.INTERRUPTED)
        if not suppress_errors:
            for error in errors:
                if isinstance(error, BaseException):
                    raise error

    def _require_turn(self) -> AgentTurn:
        if self._turn is None:
            raise RuntimeError("Agent turn has not started")
        return self._turn

    def _require_agent_task(self) -> asyncio.Task[None]:
        if self._agent_task is None:
            raise RuntimeError("Agent task has not started")
        return self._agent_task

    def _require_tts_task(self) -> asyncio.Task[None]:
        if self._tts_task is None:
            raise RuntimeError("TTS task has not started")
        return self._tts_task

    def _require_playback_task(self) -> asyncio.Task[None]:
        if self._playback_task is None:
            raise RuntimeError("Playback task has not started")
        return self._playback_task


def _duration_ms(start: float, end: float) -> float:
    return round(max(end - start, 0) * 1_000, 1)
