"""Speech recognition value objects."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Transcript:
    """Normalized text produced by a speech recognizer."""

    text: str
    is_final: bool = True
    language: str | None = None


@dataclass(frozen=True, slots=True)
class ASRResult:
    """Usage and completion summary for one recognition stream."""

    input_audio_seconds: float
    output_characters: int
    completed: bool
    provider_usage: Mapping[str, int | float] | None = None
