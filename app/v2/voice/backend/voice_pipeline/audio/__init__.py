"""Audio input and output interfaces."""

from .errors import (
    AudioDeviceError,
    AudioError,
    AudioFormatError,
    AudioStateError,
)
from .local import LocalAudio
from .protocols import AudioIO
from .types import AudioChunk, AudioFormat

__all__ = [
    "AudioChunk",
    "AudioDeviceError",
    "AudioError",
    "AudioFormat",
    "AudioFormatError",
    "AudioIO",
    "AudioStateError",
    "LocalAudio",
]
