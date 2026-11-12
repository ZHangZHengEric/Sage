"""Errors raised by text-to-speech components."""


class TTSError(Exception):
    """Base error for speech synthesis."""


class TTSStateError(TTSError, RuntimeError):
    """Raised when an operation is invalid for the synthesizer state."""
