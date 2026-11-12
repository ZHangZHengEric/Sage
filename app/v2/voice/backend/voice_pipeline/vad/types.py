"""Shared voice activity detection types."""

from enum import Enum


class VADState(Enum):
    """Stable speech state returned by a voice activity detector."""

    SILENCE = "silence"
    SPEAKING = "speaking"
