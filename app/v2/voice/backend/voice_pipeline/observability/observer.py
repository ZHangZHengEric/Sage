"""Observer interface for consuming voice events."""

from collections.abc import Awaitable
from typing import Protocol

from .events import VoiceEvent


class VoiceObserver(Protocol):
    """Consume session events without participating in voice processing."""

    def on_event(self, event: VoiceEvent) -> Awaitable[None] | None:
        """Handle one event emitted by a voice session."""

        ...
