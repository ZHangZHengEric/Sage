"""Buffer semantic user turns across VAD-detected pauses."""

from ..audio import AudioChunk, AudioFormat, AudioFormatError
from ..vad import VADState
from .types import TurnBufferUpdate, TurnPause


class SemanticTurnSegmenter:
    """Collect one user turn without treating every VAD stop as its boundary."""

    def __init__(self, *, pre_roll_ms: int = 500) -> None:
        """Configure how much audio to retain before the first VAD start."""

        if pre_roll_ms < 0:
            raise ValueError("pre_roll_ms must not be negative")

        self._pre_roll_ms = pre_roll_ms
        self._format: AudioFormat | None = None
        self._pre_roll = bytearray()
        self._turn = bytearray()
        self._active = False
        self._vad_state = VADState.SILENCE
        self._pause_id = 0
        self._current_pause: TurnPause | None = None

    @property
    def active(self) -> bool:
        """Whether a semantic user turn is currently buffered."""

        return self._active

    @property
    def current_pause(self) -> TurnPause | None:
        """Return the current VAD-stop candidate, if it is still valid."""

        return self._current_pause

    def push(self, chunk: AudioChunk, state: VADState) -> TurnBufferUpdate:
        """Buffer one raw microphone chunk and report boundary transitions."""

        self._validate_format(chunk.format)
        started = False
        started_audio: AudioChunk | None = None
        resumed = False
        pause: TurnPause | None = None

        if not self._active:
            if state is VADState.SPEAKING:
                self._active = True
                started = True
                self._turn.extend(self._pre_roll)
                self._pre_roll.clear()
                self._turn.extend(chunk.data)
                started_audio = AudioChunk(bytes(self._turn), chunk.format)
            else:
                self._append_pre_roll(chunk)
        else:
            self._turn.extend(chunk.data)
            if (
                state is VADState.SPEAKING
                and self._vad_state is VADState.SILENCE
            ):
                resumed = True
                self._current_pause = None
            elif (
                state is VADState.SILENCE
                and self._vad_state is VADState.SPEAKING
            ):
                self._pause_id += 1
                pause = TurnPause(
                    id=self._pause_id,
                    audio=AudioChunk(bytes(self._turn), chunk.format),
                )
                self._current_pause = pause

        self._vad_state = state
        return TurnBufferUpdate(
            started=started,
            started_audio=started_audio,
            resumed=resumed,
            pause=pause,
        )

    def finalize(self, pause_id: int) -> AudioChunk | None:
        """Finalize a still-current pause, ignoring stale analyzer results."""

        pause = self._current_pause
        if pause is None or pause.id != pause_id:
            return None

        audio = pause.audio
        self._turn.clear()
        self._active = False
        self._current_pause = None
        return audio

    def reset(self) -> None:
        """Discard all buffered audio and accept a new stream format."""

        self._format = None
        self._pre_roll.clear()
        self._turn.clear()
        self._active = False
        self._vad_state = VADState.SILENCE
        self._current_pause = None

    def _validate_format(self, audio_format: AudioFormat) -> None:
        if self._format is None:
            self._format = audio_format
        elif audio_format != self._format:
            raise AudioFormatError(
                f"SemanticTurnSegmenter requires {self._format!r}, "
                f"received {audio_format!r}"
            )

    def _append_pre_roll(self, chunk: AudioChunk) -> None:
        max_frames = chunk.format.sample_rate * self._pre_roll_ms // 1_000
        max_bytes = max_frames * chunk.format.frame_bytes
        if max_bytes == 0:
            self._pre_roll.clear()
            return

        self._pre_roll.extend(chunk.data)
        if len(self._pre_roll) > max_bytes:
            del self._pre_roll[:-max_bytes]
