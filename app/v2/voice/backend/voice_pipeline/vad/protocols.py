"""Public protocol implemented by voice activity detectors."""

from typing import Protocol

from ..audio import AudioChunk, AudioFormat
from .types import VADState


class VAD(Protocol):
    """Provider-neutral streaming voice activity detector."""

    @property
    def speech_start_confirmation_seconds(self) -> float:
        """Speech required before reporting that speech has started."""

        ...

    @property
    def speech_end_confirmation_seconds(self) -> float:
        """Silence required before reporting that speech has ended."""

        ...

    async def start(self, input_format: AudioFormat) -> None:
        """Initialize the detector for an input audio format."""

        ...

    async def analyze(self, chunk: AudioChunk) -> VADState:
        """Analyze the next audio chunk and return the stable speech state."""

        ...

    async def close(self) -> None:
        """Release model and worker resources."""

        ...
