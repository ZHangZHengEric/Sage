"""Microphone-to-user-input processing for a voice session."""

import asyncio
import time
import unicodedata
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from typing import Any, Protocol

from ..asr import ASR, ASRResult, ASRStream
from ..audio import AudioChunk, AudioIO
from ..audio._level import pcm16_rms_level
from ..observability import (
    Component,
    InputLevelEvent,
    SpeechEvent,
    SpeechState,
    TranscriptEvent,
    VoiceEvent,
)
from ..turn_detection import (
    SemanticTurnSegmenter,
    TurnAnalysis,
    TurnAnalyzer,
    TurnDetectionError,
    TurnPause,
)
from ..vad import VAD, AdaptiveInputLevelGate, VADState

_INPUT_LEVEL_INTERVAL_SECONDS = 0.1
_PRE_SPEECH_MS = 500
_DEFAULT_BACKCHANNEL_PHRASES = frozenset(
    {
        "嗯",
        "嗯嗯",
        "嗯哼",
        "嗯呢",
        "uh-huh",
        "mhm",
        "mm-hmm",
    }
)


def _normalize_speech_content(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(
        character
        for character in normalized
        if unicodedata.category(character)[0] in {"L", "M", "N"}
    )


def _could_be_backchannel(content: str, phrases: frozenset[str]) -> bool:
    return any(phrase == content or phrase.startswith(content) for phrase in phrases)


def _is_backchannel(content: str, phrases: frozenset[str]) -> bool:
    return content in phrases


def _is_backchannel_candidate(
    text: str,
    phrases: frozenset[str],
) -> bool:
    content = _normalize_speech_content(text)
    return not text or not content or _could_be_backchannel(content, phrases)


def _is_ignorable_backchannel(
    text: str,
    phrases: frozenset[str],
) -> bool:
    content = _normalize_speech_content(text)
    return not content or _is_backchannel(content, phrases)


class _ReportError(Protocol):
    def __call__(
        self,
        *,
        component: Component,
        operation: str,
        error: BaseException,
        fatal: bool,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class _VoiceInput:
    text: str
    language: str | None
    asr_result: ASRResult
    asr_finished_at: float
    speech_stopped_at: float
    estimated_speech_ended_at: float
    turn_decided_at: float


@dataclass(frozen=True, slots=True)
class _DroppedVoiceInput:
    """Terminal result for speech that could not produce an ASR result."""


_VoiceInputResult = _VoiceInput | _DroppedVoiceInput


@dataclass(frozen=True, slots=True)
class _PendingPause:
    pause: TurnPause
    speech_stopped_at: float
    estimated_speech_ended_at: float


@dataclass(frozen=True, slots=True)
class _RecognitionResult:
    text: str
    language: str | None
    asr_result: ASRResult


async def _collect_transcripts(
    stream: ASRStream,
    *,
    on_update: Callable[[str, str | None, bool], None],
) -> tuple[str, str | None]:
    final_text: list[str] = []
    language: str | None = None
    last_update: tuple[str, str | None, bool] | None = None
    async for transcript in stream:
        if transcript.language is not None:
            language = transcript.language
        if not transcript.text:
            continue
        if transcript.is_final:
            final_text.append(transcript.text)
            current = "".join(final_text).strip()
        else:
            current = "".join((*final_text, transcript.text)).strip()
        update = (current, language, transcript.is_final)
        if current and update != last_update:
            on_update(*update)
            last_update = update
    return "".join(final_text).strip(), language


class _StreamingRecognition:
    """Own one streaming ASR task from its first write through collection."""

    def __init__(
        self,
        stream: ASRStream,
        *,
        on_update: Callable[[str, str | None, bool], None],
    ) -> None:
        self._stream = stream
        self._latest_text = ""
        self._latest_language: str | None = None
        self._collector = asyncio.create_task(
            _collect_transcripts(stream, on_update=self._record_update(on_update)),
            name="lalk-asr-transcripts",
        )

    @property
    def latest_text(self) -> str:
        return self._latest_text

    @property
    def latest_language(self) -> str | None:
        return self._latest_language

    def _record_update(
        self,
        on_update: Callable[[str, str | None, bool], None],
    ) -> Callable[[str, str | None, bool], None]:
        def record(text: str, language: str | None, is_final: bool) -> None:
            self._latest_text = text
            self._latest_language = language
            on_update(text, language, is_final)

        return record

    async def write(self, audio: AudioChunk) -> None:
        await self._stream.write(audio)

    async def finish(self) -> _RecognitionResult:
        await self._stream.finish()
        text, language = await self._collector
        asr_result = await self._stream.result()
        return _RecognitionResult(text, language, asr_result)

    async def close(self) -> None:
        await self._stream.aclose()
        if not self._collector.done():
            self._collector.cancel()
        await asyncio.gather(self._collector, return_exceptions=True)


class _VoiceInputProcessor:
    """Convert microphone audio into complete semantic voice inputs."""

    def __init__(
        self,
        *,
        audio: AudioIO,
        vad: VAD,
        turn_analyzer: TurnAnalyzer,
        asr: ASR,
        session_id: str,
        emit: Callable[[VoiceEvent], None],
        report_error: _ReportError,
        submit: Callable[[_VoiceInputResult], Awaitable[None]],
        on_speech_started: Callable[[], object],
        playback_active: Callable[[], bool],
        input_level_gate: AdaptiveInputLevelGate | None,
        incomplete_turn_timeout_seconds: float,
        backchannel_filter_enabled: bool,
        backchannel_phrases: Collection[str] | None,
    ) -> None:
        self._audio = audio
        self._vad = vad
        self._turn_analyzer = turn_analyzer
        self._asr = asr
        self._session_id = session_id
        self._emit = emit
        self._report_error = report_error
        self._submit = submit
        self._on_speech_started = on_speech_started
        self._playback_active = playback_active
        self._input_level_gate = input_level_gate
        self._incomplete_turn_timeout_seconds = incomplete_turn_timeout_seconds
        self._backchannel_filter_enabled = backchannel_filter_enabled
        phrases = (
            _DEFAULT_BACKCHANNEL_PHRASES
            if backchannel_phrases is None
            else backchannel_phrases
        )
        self._backchannel_phrases = frozenset(
            content
            for phrase in phrases
            if (content := _normalize_speech_content(phrase))
        )

        effective_pre_speech_ms = _PRE_SPEECH_MS + round(
            vad.speech_start_confirmation_seconds * 1_000
        )
        self._segmenter = SemanticTurnSegmenter(pre_roll_ms=effective_pre_speech_ms)
        self._speech_started = asyncio.Event()
        self._in_progress = False

    @property
    def speech_started(self) -> asyncio.Event:
        return self._speech_started

    @property
    def in_progress(self) -> bool:
        return self._in_progress

    async def run(self) -> None:
        previous = VADState.SILENCE
        next_level_at = 0.0
        capture = self._audio.capture().__aiter__()
        next_audio = asyncio.ensure_future(anext(capture))
        decision_task: asyncio.Task[_PendingPause] | None = None
        recognition: _StreamingRecognition | None = None
        try:
            while True:
                waiters: set[asyncio.Future[Any]] = {next_audio}
                if decision_task is not None:
                    waiters.add(decision_task)
                done, _ = await asyncio.wait(
                    waiters,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Microphone input wins ties so resumed speech invalidates a
                # decision before that decision can finalize the old pause.
                if next_audio in done:
                    try:
                        chunk = next_audio.result()
                    except StopAsyncIteration:
                        return

                    state, next_level_at = await self._process_audio_chunk(
                        chunk,
                        previous=previous,
                        next_level_at=next_level_at,
                    )
                    update = self._segmenter.push(chunk, state)

                    if update.started:
                        assert update.started_audio is not None
                        filter_backchannel = (
                            self._backchannel_filter_enabled
                            and self._playback_active()
                            and self._asr.supports_interim_transcripts
                        )
                        if not filter_backchannel:
                            self._start_voice_input()
                        recognition = await self._start_recognition(
                            update.started_audio
                        )
                        if recognition is None and not self._in_progress:
                            self._start_voice_input()
                    elif recognition is not None:
                        if not await self._write_recognition(recognition, chunk):
                            recognition = None
                            if not self._in_progress:
                                self._start_voice_input()

                    if (
                        recognition is not None
                        and not self._in_progress
                        and not self._playback_active()
                    ):
                        self._start_voice_input()

                    if update.resumed and decision_task is not None:
                        await self._cancel_task(decision_task)
                        decision_task = None

                    defer_until_final = False
                    if (
                        update.pause is not None
                        and not self._in_progress
                        and recognition is not None
                    ):
                        defer_until_final = _is_backchannel_candidate(
                            recognition.latest_text,
                            self._backchannel_phrases,
                        )

                    if update.pause is not None:
                        if not self._in_progress and not defer_until_final:
                            self._start_voice_input()
                        if decision_task is not None:
                            await self._cancel_task(decision_task)
                        speech_stopped_at = time.perf_counter()
                        pending_pause = _PendingPause(
                            pause=update.pause,
                            speech_stopped_at=speech_stopped_at,
                            estimated_speech_ended_at=(
                                speech_stopped_at
                                - self._vad.speech_end_confirmation_seconds
                            ),
                        )
                        decision_task = asyncio.create_task(
                            self._await_turn_decision(pending_pause),
                            name=f"lalk-turn-decision-{update.pause.id}",
                        )

                    previous = state
                    next_audio = asyncio.ensure_future(anext(capture))

                if decision_task is not None and decision_task.done():
                    pending_pause = decision_task.result()
                    submitted = await self._submit_voice_pause(
                        pending_pause,
                        recognition,
                        turn_decided_at=time.perf_counter(),
                    )
                    if submitted:
                        recognition = None
                    decision_task = None
        except asyncio.CancelledError:
            raise
        except TurnDetectionError as error:
            self._report_error(
                component=Component.TURN_DETECTION,
                operation="analyze",
                error=error,
                fatal=True,
            )
            raise
        except BaseException as error:
            self._report_error(
                component=Component.AUDIO,
                operation="capture",
                error=error,
                fatal=True,
            )
            raise
        finally:
            tasks: list[asyncio.Future[Any]] = [next_audio]
            if decision_task is not None:
                tasks.append(decision_task)
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if recognition is not None:
                await recognition.close()
            self._in_progress = False
            self._speech_started.clear()
            self._emit(InputLevelEvent(session_id=self._session_id, level=0.0))

    async def _process_audio_chunk(
        self,
        chunk: AudioChunk,
        *,
        previous: VADState,
        next_level_at: float,
    ) -> tuple[VADState, float]:
        now = time.perf_counter()
        emit_level = now >= next_level_at
        input_level = pcm16_rms_level(chunk.data) if emit_level else 0.0
        playback_active = self._playback_active()
        vad_chunk = chunk
        gate_level_db: float | None = None
        if self._input_level_gate is not None:
            vad_chunk, gate_level_db = self._input_level_gate.filter(
                chunk,
                speaking=previous is VADState.SPEAKING,
                playback_active=playback_active,
            )
        try:
            state = await self._vad.analyze(vad_chunk)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._report_error(
                component=Component.VAD,
                operation="analyze",
                error=error,
                fatal=True,
            )
            raise

        if self._input_level_gate is not None:
            assert gate_level_db is not None
            self._input_level_gate.observe(
                level_db=gate_level_db,
                duration_seconds=chunk.duration_seconds,
                state=state,
                adapt=not playback_active,
            )

        if emit_level:
            gate_status = (
                self._input_level_gate.status
                if self._input_level_gate is not None
                else None
            )
            self._emit(
                InputLevelEvent(
                    session_id=self._session_id,
                    level=input_level,
                    level_db=(
                        gate_status.level_db if gate_status is not None else None
                    ),
                    noise_floor_db=(
                        gate_status.noise_floor_db if gate_status is not None else None
                    ),
                    threshold_db=(
                        gate_status.threshold_db if gate_status is not None else None
                    ),
                    gate_mode=(
                        gate_status.mode.value if gate_status is not None else None
                    ),
                    gate_passed=(
                        gate_status.passed if gate_status is not None else None
                    ),
                )
            )
            next_level_at = now + _INPUT_LEVEL_INTERVAL_SECONDS

        return state, next_level_at

    def _start_voice_input(self) -> None:
        self._in_progress = True
        self._speech_started.set()
        self._emit(
            SpeechEvent(
                session_id=self._session_id,
                state=SpeechState.STARTED,
            )
        )
        self._on_speech_started()

    async def _await_turn_decision(
        self,
        pending: _PendingPause,
    ) -> _PendingPause:
        deadline = (
            asyncio.get_running_loop().time() + self._incomplete_turn_timeout_seconds
        )
        try:
            async with asyncio.timeout_at(deadline):
                analysis = await self._analyze_turn(pending.pause.audio)
                if analysis.complete:
                    return pending
                remaining = max(deadline - asyncio.get_running_loop().time(), 0)
                await asyncio.sleep(remaining)
        except TimeoutError:
            pass
        return pending

    async def _analyze_turn(self, audio: AudioChunk) -> TurnAnalysis:
        try:
            return await self._turn_analyzer.analyze(audio)
        except asyncio.CancelledError:
            raise
        except TurnDetectionError:
            raise
        except Exception as error:  # noqa: BLE001 - normalize provider failures
            raise TurnDetectionError(f"Turn analyzer failed: {error}") from error

    async def _start_recognition(
        self,
        audio: AudioChunk,
    ) -> _StreamingRecognition | None:
        recognition: _StreamingRecognition | None = None
        try:
            recognition = _StreamingRecognition(
                self._asr.recognize(),
                on_update=self._handle_transcript_update,
            )
            await recognition.write(audio)
            return recognition
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - ASR failure is input-local
            self._report_error(
                component=Component.ASR,
                operation="recognize",
                error=error,
                fatal=False,
            )
            if recognition is not None:
                await recognition.close()
            return None

    async def _write_recognition(
        self,
        recognition: _StreamingRecognition,
        audio: AudioChunk,
    ) -> bool:
        try:
            await recognition.write(audio)
            return True
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - ASR failure is input-local
            self._report_error(
                component=Component.ASR,
                operation="write",
                error=error,
                fatal=False,
            )
            await recognition.close()
            return False

    def _emit_interim_transcript(self, text: str, language: str | None) -> None:
        self._emit(
            TranscriptEvent(
                session_id=self._session_id,
                text=text,
                is_final=False,
                language=language,
            )
        )

    def _handle_transcript_update(
        self,
        text: str,
        language: str | None,
        is_final: bool,
    ) -> None:
        content = _normalize_speech_content(text)
        if not content:
            return

        if not self._in_progress:
            if _could_be_backchannel(content, self._backchannel_phrases):
                return
            self._start_voice_input()

        if not is_final:
            self._emit_interim_transcript(text, language)

    async def _submit_voice_pause(
        self,
        pending: _PendingPause,
        recognition: _StreamingRecognition | None,
        *,
        turn_decided_at: float,
    ) -> bool:
        audio = self._segmenter.finalize(pending.pause.id)
        if audio is None:
            return False

        started_before_final = self._in_progress
        if started_before_final:
            self._emit_speech_stopped()

        if recognition is None:
            await self._finish_voice_input(_DroppedVoiceInput())
            return True

        try:
            recognized = await recognition.finish()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - ASR failure is input-local
            self._report_error(
                component=Component.ASR,
                operation="transcribe",
                error=error,
                fatal=False,
            )
            await recognition.close()
            if not started_before_final:
                self._start_voice_input()
                self._emit_speech_stopped()
            await self._finish_voice_input(_DroppedVoiceInput())
            return True

        if not started_before_final:
            if not self._in_progress and _is_ignorable_backchannel(
                recognized.text,
                self._backchannel_phrases,
            ):
                return True
            if not self._in_progress:
                self._start_voice_input()
            self._emit_speech_stopped()

        asr_finished_at = time.perf_counter()
        await self._finish_voice_input(
            _VoiceInput(
                text=recognized.text,
                language=recognized.language,
                asr_result=recognized.asr_result,
                asr_finished_at=asr_finished_at,
                speech_stopped_at=pending.speech_stopped_at,
                estimated_speech_ended_at=pending.estimated_speech_ended_at,
                turn_decided_at=turn_decided_at,
            )
        )
        return True

    def _emit_speech_stopped(self) -> None:
        self._emit(
            SpeechEvent(
                session_id=self._session_id,
                state=SpeechState.STOPPED,
            )
        )

    async def _finish_voice_input(self, result: _VoiceInputResult) -> None:
        await self._submit(result)
        self._in_progress = False
        self._speech_started.clear()

    @staticmethod
    async def _cancel_task(task: asyncio.Task[Any]) -> None:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
