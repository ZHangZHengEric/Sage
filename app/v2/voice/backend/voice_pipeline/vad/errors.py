"""Errors raised by voice activity detectors."""


class VADError(Exception):
    """Base error for voice activity detection."""


class VADFormatError(VADError, ValueError):
    """Raised when a detector cannot process an audio format."""


class VADStateError(VADError, RuntimeError):
    """Raised when an operation is invalid for the detector state."""
