"""Public protocol implemented by semantic turn analyzers."""

from typing import Protocol

from ..audio import AudioChunk, AudioFormat
from .types import TurnAnalysis


class TurnAnalyzer(Protocol):
    """Classify whether the current user audio completes a conversational turn."""

    async def start(self, input_format: AudioFormat) -> None:
        """Load the analyzer and validate the microphone format."""

        ...

    async def analyze(self, audio: AudioChunk) -> TurnAnalysis:
        """Analyze a snapshot of the current user turn."""

        ...

    async def close(self) -> None:
        """Release model and worker resources."""

        ...
