"""Semantic turn detection errors."""


class TurnDetectionError(Exception):
    """Base error raised by semantic turn detection."""


class TurnDetectionFormatError(TurnDetectionError, ValueError):
    """Raised when audio is incompatible with a turn analyzer."""


class TurnDetectionStateError(TurnDetectionError, RuntimeError):
    """Raised when a turn analyzer is used outside its lifecycle."""
