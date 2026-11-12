"""Silero voice activity detection using sherpa-onnx."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import as_file, files
from typing import Any

import numpy as np
import sherpa_onnx

from ..audio import AudioChunk, AudioFormat
from ..audio._level import pcm16_rms_level
from .errors import VADError, VADFormatError, VADStateError
from .types import VADState

_SAMPLE_RATE = 16_000
_WINDOW_SAMPLES = 512
_BUFFER_SECONDS = 30
_INPUT_LEVEL_SMOOTHING_FACTOR = 0.2


class SileroVAD:
    """Detect stable speech states from 16 kHz mono PCM audio."""

    def __init__(
        self,
        *,
        threshold: float = 0.7,
        min_input_level: float = 0.0,
        speech_start_ms: int = 200,
        speech_end_ms: int = 300,
    ) -> None:
        """Initialize configuration without loading the Silero model."""

        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between zero and one")
        if not 0 <= min_input_level <= 1:
            raise ValueError("min_input_level must be between zero and one")
        if speech_start_ms <= 0:
            raise ValueError("speech_start_ms must be greater than zero")
        if speech_end_ms <= 0:
            raise ValueError("speech_end_ms must be greater than zero")

        self._threshold = threshold
        self._min_input_level = min_input_level
        self._speech_start_seconds = speech_start_ms / 1_000
        self._speech_end_seconds = speech_end_ms / 1_000
        self._smoothed_input_level = 0.0

        self._lock = asyncio.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._detector: Any | None = None
        self._input_format: AudioFormat | None = None
        self._state = VADState.SILENCE
        self._started = False
        self._closed = False

    @property
    def speech_start_confirmation_seconds(self) -> float:
        """Speech required before Silero reports the start of speech."""

        return self._speech_start_seconds

    @property
    def speech_end_confirmation_seconds(self) -> float:
        """Silence required before Silero reports the end of speech."""

        return self._speech_end_seconds

    async def start(self, input_format: AudioFormat) -> None:
        """Load the detector and validate the input format."""

        async with self._lock:
            if self._closed:
                raise VADStateError("SileroVAD has already been closed")
            if self._started:
                if input_format != self._input_format:
                    raise VADStateError(
                        "SileroVAD is already running with another audio format"
                    )
                return
            self._validate_format(input_format)

            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lalk-vad")
            try:
                future = asyncio.get_running_loop().run_in_executor(
                    executor, self._load_detector, input_format
                )
                detector = await self._await_worker(future)
            except asyncio.CancelledError:
                await asyncio.to_thread(
                    executor.shutdown, wait=True, cancel_futures=True
                )
                raise
            except Exception as error:
                await asyncio.to_thread(
                    executor.shutdown, wait=True, cancel_futures=True
                )
                raise VADError(f"Unable to load Silero VAD model: {error}") from error

            self._executor = executor
            self._detector = detector
            self._input_format = input_format
            self._started = True

    async def analyze(self, chunk: AudioChunk) -> VADState:
        """Analyze one PCM chunk without blocking the asyncio event loop."""

        async with self._lock:
            self._ensure_started()
            if chunk.format != self._input_format:
                raise VADFormatError(
                    f"SileroVAD requires {self._input_format!r}, "
                    f"received {chunk.format!r}"
                )
            if not chunk.data:
                return self._state

            executor = self._require_executor()
            try:
                future = asyncio.get_running_loop().run_in_executor(
                    executor, self._analyze_pcm, chunk.data
                )
                self._state = await self._await_worker(future)
                return self._state
            except asyncio.CancelledError:
                raise
            except Exception as error:
                raise VADError(
                    f"Unable to analyze audio with SileroVAD: {error}"
                ) from error

    async def close(self) -> None:
        """Release the detector and inference thread."""

        async with self._lock:
            if self._closed:
                return
            self._closed = True
            self._started = False
            self._detector = None
            self._input_format = None
            self._state = VADState.SILENCE

            executor = self._executor
            self._executor = None
            if executor is not None:
                await asyncio.to_thread(
                    executor.shutdown, wait=True, cancel_futures=True
                )

    def _load_detector(self, input_format: AudioFormat) -> Any:
        model_resource = files(f"{__package__}.data").joinpath("silero_vad.onnx")
        with as_file(model_resource) as model_path:
            silero = sherpa_onnx.SileroVadModelConfig(
                model=str(model_path),
                threshold=self._threshold,
                min_speech_duration=self._speech_start_seconds,
                min_silence_duration=self._speech_end_seconds,
                window_size=_WINDOW_SAMPLES,
                max_speech_duration=float("inf"),
            )
            config = sherpa_onnx.VadModelConfig(
                silero_vad=silero,
                sample_rate=input_format.sample_rate,
                num_threads=1,
                provider="cpu",
            )
            if not config.validate():
                raise RuntimeError("Invalid sherpa-onnx Silero VAD configuration")
            return sherpa_onnx.VoiceActivityDetector(
                config,
                buffer_size_in_seconds=_BUFFER_SECONDS,
            )

    def _analyze_pcm(self, data: bytes) -> VADState:
        detector = self._require_detector()
        samples = np.frombuffer(data, dtype="<i2").astype(np.float32)
        samples *= 1.0 / 32_768.0
        if self._min_input_level > 0:
            level = pcm16_rms_level(data)
            self._smoothed_input_level += _INPUT_LEVEL_SMOOTHING_FACTOR * (
                level - self._smoothed_input_level
            )
            if self._smoothed_input_level < self._min_input_level:
                samples.fill(0)
        detector.accept_waveform(samples)

        state = VADState.SPEAKING if detector.is_speech_detected() else VADState.SILENCE
        while not detector.empty():
            detector.pop()
        return state

    async def _await_worker(self, future: asyncio.Future[Any]) -> Any:
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            await asyncio.shield(future)
            raise

    def _validate_format(self, input_format: AudioFormat) -> None:
        if input_format.channels != 1:
            raise VADFormatError("SileroVAD requires mono audio")
        if input_format.sample_rate != _SAMPLE_RATE:
            raise VADFormatError(f"SileroVAD requires {_SAMPLE_RATE} Hz audio")

    def _ensure_started(self) -> None:
        if self._closed:
            raise VADStateError("SileroVAD has been closed")
        if not self._started:
            raise VADStateError("SileroVAD has not been started")

    def _require_executor(self) -> ThreadPoolExecutor:
        if self._executor is None:
            raise VADStateError("SileroVAD inference worker is unavailable")
        return self._executor

    def _require_detector(self) -> Any:
        if self._detector is None:
            raise VADStateError("SileroVAD detector is unavailable")
        return self._detector
