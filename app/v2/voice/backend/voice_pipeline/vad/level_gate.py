"""Adaptive input-level gating for voice activity detection."""

import math
from dataclasses import dataclass
from enum import StrEnum

from ..audio import AudioChunk
from ..audio._level import pcm16_rms_level
from .types import VADState

_BOOTSTRAP_SECONDS = 0.5
_ADAPTATION_SECONDS = 3.0
_START_MARGIN_DB = 7.0
_PLAYBACK_START_MARGIN_DB = 0.0
_CONTINUATION_MARGIN_DB = 3.0
_MAX_UPWARD_OBSERVATION_DB = 6.0
_LEVEL_SMOOTHING_FACTOR = 0.2
_MIN_LEVEL = 1.0 / 32_768.0


class InputLevelGateMode(StrEnum):
    """Active threshold profile used by the input-level gate."""

    BOOTSTRAP = "bootstrap"
    NORMAL = "normal"
    PLAYBACK = "playback"
    SPEAKING = "speaking"


@dataclass(frozen=True, slots=True)
class InputLevelGateStatus:
    """Latest observable state of the adaptive input-level gate."""

    level_db: float
    noise_floor_db: float | None
    threshold_db: float | None
    mode: InputLevelGateMode
    passed: bool


class AdaptiveInputLevelGate:
    """Create a VAD-only audio view relative to the ambient noise floor."""

    def __init__(self, *, minimum_level: float = 0.0) -> None:
        """Set an optional hard lower bound for the adaptive thresholds."""

        if not 0 <= minimum_level <= 1:
            raise ValueError("minimum_level must be between zero and one")

        self._minimum_level_db = (
            _level_to_db(minimum_level) if minimum_level > 0 else None
        )
        self._smoothed_level: float | None = None
        self._noise_floor_db: float | None = None
        self._bootstrap_levels: list[float] = []
        self._bootstrap_seconds = 0.0
        self._status: InputLevelGateStatus | None = None

    @property
    def status(self) -> InputLevelGateStatus | None:
        """Return the latest gate state for diagnostics and user interfaces."""

        return self._status

    def filter(
        self,
        chunk: AudioChunk,
        *,
        speaking: bool,
        playback_active: bool = False,
    ) -> tuple[AudioChunk, float]:
        """Return a VAD-only chunk and its smoothed input level in dBFS."""

        level = pcm16_rms_level(chunk.data)
        if self._smoothed_level is None:
            self._smoothed_level = level
        else:
            self._smoothed_level += _LEVEL_SMOOTHING_FACTOR * (
                level - self._smoothed_level
            )
        level_db = _level_to_db(self._smoothed_level)

        noise_floor_db = self._noise_floor_db
        if noise_floor_db is None:
            self._status = InputLevelGateStatus(
                level_db=level_db,
                noise_floor_db=None,
                threshold_db=None,
                mode=InputLevelGateMode.BOOTSTRAP,
                passed=True,
            )
            return chunk, level_db

        if speaking:
            margin_db = _CONTINUATION_MARGIN_DB
            mode = InputLevelGateMode.SPEAKING
        elif playback_active:
            margin_db = _PLAYBACK_START_MARGIN_DB
            mode = InputLevelGateMode.PLAYBACK
        else:
            margin_db = _START_MARGIN_DB
            mode = InputLevelGateMode.NORMAL
        threshold_db = noise_floor_db + margin_db
        if self._minimum_level_db is not None:
            threshold_db = max(threshold_db, self._minimum_level_db)
        passed = level_db >= threshold_db
        self._status = InputLevelGateStatus(
            level_db=level_db,
            noise_floor_db=noise_floor_db,
            threshold_db=threshold_db,
            mode=mode,
            passed=passed,
        )
        if passed:
            return chunk, level_db
        return AudioChunk(bytes(len(chunk.data)), chunk.format), level_db

    def observe(
        self,
        *,
        level_db: float,
        duration_seconds: float,
        state: VADState,
        adapt: bool,
    ) -> None:
        """Update the ambient estimate after VAD has classified one chunk."""

        if duration_seconds <= 0:
            return
        if not adapt or state is VADState.SPEAKING:
            if self._noise_floor_db is None:
                self._reset_bootstrap()
            return

        if self._noise_floor_db is None:
            self._bootstrap_levels.append(level_db)
            self._bootstrap_seconds += duration_seconds
            if self._bootstrap_seconds >= _BOOTSTRAP_SECONDS:
                ordered = sorted(self._bootstrap_levels)
                self._noise_floor_db = ordered[len(ordered) // 2]
                self._reset_bootstrap()
            return

        observed_db = min(
            level_db,
            self._noise_floor_db + _MAX_UPWARD_OBSERVATION_DB,
        )
        alpha = 1.0 - math.exp(-duration_seconds / _ADAPTATION_SECONDS)
        self._noise_floor_db += alpha * (observed_db - self._noise_floor_db)

    def _reset_bootstrap(self) -> None:
        self._bootstrap_levels.clear()
        self._bootstrap_seconds = 0.0


def _level_to_db(level: float) -> float:
    return 20.0 * math.log10(max(level, _MIN_LEVEL))
