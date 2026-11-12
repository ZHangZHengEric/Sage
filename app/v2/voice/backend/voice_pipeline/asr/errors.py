"""Errors raised by speech recognition components."""


class ASRError(Exception):
    """Base error for speech recognition."""


class ASRFormatError(ASRError, ValueError):
    """Raised when a recognizer cannot process an audio format."""


class ASRStateError(ASRError, RuntimeError):
    """Raised when an operation is invalid for the recognizer state."""
