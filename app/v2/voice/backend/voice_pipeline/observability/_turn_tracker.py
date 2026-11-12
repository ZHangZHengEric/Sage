"""Collect timing and usage for one voice turn."""

import time
from collections.abc import Mapping

from ..asr import ASRResult
from .metrics import TurnMetrics


class _TurnMetricsTracker:
    """Record monotonic milestones and build one final metrics snapshot."""

    def __init__(
        self,
        *,
        prompt_ready_at: float,
        speech_stopped_at: float | None = None,
        estimated_speech_ended_at: float | None = None,
        turn_decided_at: float | None = None,
        asr_finished_at: float | None = None,
        asr_result: ASRResult | None = None,
    ) -> None:
        self._prompt_ready_at = prompt_ready_at
        self._speech_stopped_at = speech_stopped_at
        self._estimated_speech_ended_at = estimated_speech_ended_at
        self._turn_decided_at = turn_decided_at
        self._asr_finished_at = asr_finished_at
        self._asr_result = asr_result
        self._turn_started_at = time.perf_counter()

        self._model_request_at: float | None = None
        self._first_agent_text_at: float | None = None
        self._first_tts_text_at: float | None = None
        self._first_audio_at: float | None = None
        self._first_playback_at: float | None = None
        self._interruption_requested_at: float | None = None
        self._interruption_finished_at: float | None = None
        self._llm_usage: dict[str, int] = {}
        self._tts_usage: dict[str, int | float] | None = None

    def mark_model_request_started(self) -> None:
        if self._model_request_at is None:
            self._model_request_at = time.perf_counter()

    def mark_agent_text(self) -> None:
        if self._first_agent_text_at is None:
            self._first_agent_text_at = time.perf_counter()

    def mark_tts_text(self) -> None:
        if self._first_tts_text_at is None:
            self._first_tts_text_at = time.perf_counter()

    def mark_tts_audio(self) -> None:
        if self._first_audio_at is None:
            self._first_audio_at = time.perf_counter()

    def mark_playback(self) -> None:
        if self._first_playback_at is None:
            self._first_playback_at = time.perf_counter()

    def mark_interruption_requested(self) -> None:
        if self._interruption_requested_at is None:
            self._interruption_requested_at = time.perf_counter()

    def mark_interruption_finished(self) -> None:
        if self._interruption_finished_at is None:
            self._interruption_finished_at = time.perf_counter()

    def add_llm_usage(self, usage: Mapping[object, object]) -> None:
        for key, value in usage.items():
            if isinstance(key, str) and isinstance(value, int):
                self._llm_usage[key] = self._llm_usage.get(key, 0) + value

    def set_llm_usage(self, usage: Mapping[str, int]) -> None:
        self._llm_usage = dict(usage)

    def set_tts_usage(
        self,
        *,
        provider_usage: Mapping[str, int | float] | None,
        input_characters: int,
        audio_bytes: int,
    ) -> None:
        usage = dict(provider_usage or {})
        usage["input_characters"] = input_characters
        usage["audio_bytes"] = audio_bytes
        self._tts_usage = usage

    def snapshot(self) -> TurnMetrics:
        """Build metrics from all milestones observed so far."""

        asr_usage: dict[str, int | float] | None = None
        if self._asr_result is not None:
            asr_usage = dict(self._asr_result.provider_usage or {})
            asr_usage["input_audio_seconds"] = self._asr_result.input_audio_seconds
            asr_usage["output_characters"] = self._asr_result.output_characters

        return TurnMetrics(
            vad_confirmation_ms=_optional_duration_ms(
                self._estimated_speech_ended_at,
                self._speech_stopped_at,
            ),
            turn_detection_ms=_optional_duration_ms(
                self._speech_stopped_at,
                self._turn_decided_at,
            ),
            asr_finalization_ms=_optional_duration_ms(
                self._turn_decided_at,
                self._asr_finished_at,
            ),
            asr_audio_seconds=(
                self._asr_result.input_audio_seconds
                if self._asr_result is not None
                else None
            ),
            agent_request_preparation_ms=_optional_duration_ms(
                self._prompt_ready_at,
                self._model_request_at,
            ),
            agent_first_token_ms=_optional_duration_ms(
                self._prompt_ready_at,
                self._first_agent_text_at,
            ),
            llm_first_token_ms=_optional_duration_ms(
                self._model_request_at,
                self._first_agent_text_at,
            ),
            text_aggregation_ms=_optional_duration_ms(
                self._first_agent_text_at,
                self._first_tts_text_at,
            ),
            tts_first_audio_ms=_optional_duration_ms(
                self._first_tts_text_at,
                self._first_audio_at,
            ),
            vad_stop_to_tts_first_audio_ms=_optional_duration_ms(
                self._speech_stopped_at,
                self._first_audio_at,
            ),
            estimated_user_stop_to_first_playback_ms=_optional_duration_ms(
                self._estimated_speech_ended_at,
                self._first_playback_at,
            ),
            speech_first_playback_ms=_optional_duration_ms(
                self._first_agent_text_at,
                self._first_playback_at,
            )
            if self._estimated_speech_ended_at is not None
            else None,
            interruption_ms=_optional_duration_ms(
                self._interruption_requested_at,
                self._interruption_finished_at,
            ),
            turn_ms=_duration_ms(self._turn_started_at, time.perf_counter()),
            asr_usage=asr_usage,
            llm_usage=dict(self._llm_usage) or None,
            tts_usage=dict(self._tts_usage) if self._tts_usage is not None else None,
        )


def _duration_ms(start: float, end: float) -> float:
    return round(max(end - start, 0) * 1_000, 1)


def _optional_duration_ms(start: float | None, end: float | None) -> float | None:
    if start is None or end is None:
        return None
    return _duration_ms(start, end)
