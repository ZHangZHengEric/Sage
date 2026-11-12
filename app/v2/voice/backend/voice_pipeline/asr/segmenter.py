"""Build complete speech segments from VAD states and PCM chunks."""

from ..audio import AudioChunk, AudioFormat, AudioFormatError
from ..vad import VADState


class SpeechSegmenter:
    """Collect continuous PCM chunks into VAD-delimited speech segments."""

    def __init__(self, *, pre_roll_ms: int = 500) -> None:
        """Configure how much audio to retain before speech is detected."""

        if pre_roll_ms < 0:
            raise ValueError("pre_roll_ms must not be negative")

        self._pre_roll_ms = pre_roll_ms
        self._format: AudioFormat | None = None
        self._pre_roll = bytearray()
        self._speech = bytearray()
        self._speaking = False

    def push(self, chunk: AudioChunk, state: VADState) -> AudioChunk | None:
        """Consume one audio chunk and return a segment when speech ends."""

        self._validate_format(chunk.format)

        if state is VADState.SPEAKING:
            if not self._speaking:
                self._speaking = True
                self._speech.extend(self._pre_roll)
                self._pre_roll.clear()
            self._speech.extend(chunk.data)
            return None

        if self._speaking:
            self._speech.extend(chunk.data)
            segment = AudioChunk(bytes(self._speech), chunk.format)
            self._speech.clear()
            self._speaking = False
            return segment

        self._append_pre_roll(chunk)
        return None

    def reset(self) -> None:
        """Discard buffered audio and accept a new stream format."""

        self._format = None
        self._pre_roll.clear()
        self._speech.clear()
        self._speaking = False

    def _validate_format(self, audio_format: AudioFormat) -> None:
        if self._format is None:
            self._format = audio_format
        elif audio_format != self._format:
            raise AudioFormatError(
                f"SpeechSegmenter requires {self._format!r}, received {audio_format!r}"
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
