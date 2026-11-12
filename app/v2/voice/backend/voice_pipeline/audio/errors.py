"""Errors raised by audio components."""


class AudioError(Exception):
    """Base error for audio operations."""


class AudioDeviceError(AudioError):
    """Raised when an audio device cannot be opened or operated."""


class AudioFormatError(AudioError, ValueError):
    """Raised when audio data has an unsupported or invalid format."""


class AudioStateError(AudioError, RuntimeError):
    """Raised when an operation is invalid for the current lifecycle state."""
