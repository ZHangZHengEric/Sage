"""Metrics produced by voice sessions."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class TurnMetrics:
    """Latency and usage summary for one assistant turn."""

    vad_confirmation_ms: float | None = None
    turn_detection_ms: float | None = None
    asr_finalization_ms: float | None = None
    asr_audio_seconds: float | None = None
    agent_request_preparation_ms: float | None = None
    agent_first_token_ms: float | None = None
    llm_first_token_ms: float | None = None
    text_aggregation_ms: float | None = None
    tts_first_audio_ms: float | None = None
    vad_stop_to_tts_first_audio_ms: float | None = None
    estimated_user_stop_to_first_playback_ms: float | None = None
    speech_first_playback_ms: float | None = None
    interruption_ms: float | None = None
    turn_ms: float | None = None
    progress_cue: bool = False
    asr_usage: Mapping[str, int | float] | None = None
    llm_usage: Mapping[str, int] | None = None
    tts_usage: Mapping[str, int | float] | None = None
