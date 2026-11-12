"""Public protocols implemented by speech recognizers."""

from typing import Protocol, Self

from ..audio import AudioChunk, AudioFormat
from .types import ASRResult, Transcript


class ASRStream(Protocol):
    """One audio-input, transcript-output recognition task."""

    def __aiter__(self) -> Self: ...

    async def __anext__(self) -> Transcript: ...

    async def write(self, audio: AudioChunk) -> None:
        """Submit the next PCM audio chunk."""

        ...

    async def finish(self) -> None:
        """Finish audio input normally and wait for recognition to complete.

        Consumers must drain the transcript iterator to ``StopAsyncIteration``.
        Natural iterator exhaustion releases the completed recognition's active
        stream slot. The recognition result remains available afterward.
        """

        ...

    async def aclose(self) -> None:
        """Cancel or discard the stream before natural iterator exhaustion."""

        ...

    async def result(self) -> ASRResult:
        """Wait for recognition to stop and return collected usage."""

        ...


class ASR(Protocol):
    """Provider-neutral speech recognizer."""

    @property
    def supports_interim_transcripts(self) -> bool:
        """Whether streams can emit transcripts before input is finished."""

        ...

    async def start(self, input_format: AudioFormat) -> None:
        """Initialize the recognizer for an input audio format."""

        ...

    def recognize(self) -> ASRStream:
        """Create one recognition stream."""

        ...

    async def close(self) -> None:
        """Release model and worker resources."""

        ...
