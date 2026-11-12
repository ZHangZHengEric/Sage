"""Value objects for semantic user-turn detection."""

from dataclasses import dataclass

from ..audio import AudioChunk


@dataclass(frozen=True, slots=True)
class TurnAnalysis:
    """One end-of-turn prediction produced by a turn analyzer."""

    complete: bool
    probability: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError("probability must be between zero and one")


@dataclass(frozen=True, slots=True)
class TurnPause:
    """Immutable candidate boundary created by a VAD stop transition."""

    id: int
    audio: AudioChunk


@dataclass(frozen=True, slots=True)
class TurnBufferUpdate:
    """State changes produced while buffering one microphone chunk."""

    started: bool = False
    started_audio: AudioChunk | None = None
    resumed: bool = False
    pause: TurnPause | None = None
