"""Streaming filters applied to captured audio before session processing."""

from typing import Protocol

from ..types import AudioChunk, AudioFormat


class AudioInputFilter(Protocol):
    """Preserve the input format while allowing variable-sized output chunks.

    Each instance owns one continuous input stream. Buffered audio may produce
    no output for a call; closing discards any remaining buffered audio.
    """

    async def start(self, audio_format: AudioFormat) -> None:
        """Initialize resources for the capture format."""
        ...

    async def filter(self, chunk: AudioChunk) -> AudioChunk | None:
        """Return processed audio, or None while buffering."""
        ...

    async def close(self) -> None:
        """Wait for processing to finish and release resources."""
        ...
