"""Result types shared by text-to-speech providers."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TTSTextMark:
    """Text added to the spoken transcript at an audio position.

    Parameters:
        text: Text considered spoken when playback reaches this mark.
        at_frame: Frame offset from the start of the synthesis stream.
    """

    text: str
    at_frame: int

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("TTSTextMark.text must not be empty")
        if self.at_frame < 0:
            raise ValueError("TTSTextMark.at_frame must not be negative")


@dataclass(frozen=True, slots=True)
class TTSResult:
    """Summary of one synthesis stream.

    Parameters:
        input_characters: Characters successfully submitted to the provider.
        audio_bytes: PCM bytes received from the provider.
        completed: Whether the provider finished the synthesis normally.
        provider_usage: Optional provider-specific numeric usage values.
    """

    input_characters: int
    audio_bytes: int
    completed: bool
    provider_usage: Mapping[str, int | float] | None = None
