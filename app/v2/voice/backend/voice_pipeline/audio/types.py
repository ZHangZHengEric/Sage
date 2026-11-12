"""Shared audio value objects."""

from dataclasses import dataclass

from .errors import AudioFormatError


@dataclass(frozen=True, slots=True)
class AudioFormat:
    """Format of a signed 16-bit little-endian PCM stream."""

    sample_rate: int
    channels: int = 1

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise AudioFormatError("sample_rate must be greater than zero")
        if self.channels <= 0:
            raise AudioFormatError("channels must be greater than zero")

    @property
    def frame_bytes(self) -> int:
        """Number of bytes in one interleaved audio frame."""

        return self.channels * 2

    def frame_count(self, data: bytes) -> int:
        """Return the number of frames in aligned PCM data."""

        if len(data) % self.frame_bytes:
            raise AudioFormatError(
                f"PCM data length {len(data)} is not aligned to "
                f"{self.frame_bytes} bytes per frame"
            )
        return len(data) // self.frame_bytes


@dataclass(frozen=True, slots=True)
class AudioChunk:
    """A format-aware chunk of PCM audio."""

    data: bytes
    format: AudioFormat

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes):
            raise AudioFormatError("AudioChunk.data must be bytes")
        self.format.frame_count(self.data)

    @property
    def frame_count(self) -> int:
        """Number of audio frames in this chunk."""

        return self.format.frame_count(self.data)

    @property
    def duration_seconds(self) -> float:
        """Duration of this chunk in seconds."""

        return self.frame_count / self.format.sample_rate
