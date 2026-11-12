"""Local duplex audio with optional macOS echo cancellation."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import dataclass
from typing import Literal

from ._macos import MacOSVoiceProcessingBackend
from ._portaudio import PortAudioBackend
from .errors import AudioDeviceError, AudioStateError
from .filters.protocols import AudioInputFilter
from .types import AudioChunk, AudioFormat

logger = logging.getLogger(__name__)

EchoCancellation = Literal["disabled", "preferred", "required"]


@dataclass(frozen=True, slots=True)
class _PortAudioSettings:
    input_device: int | str | None
    output_device: int | str | None
    input_format: AudioFormat
    output_format: AudioFormat
    block_ms: int
    capture_buffer_ms: int
    latency: float | Literal["low", "high"]


class LocalAudio:
    """Capture and play local PCM audio.

    On macOS, ``echo_cancellation="preferred"`` uses VoiceProcessingIO when
    the native library and its fixed audio formats are available. All other
    configurations use PortAudio through ``sounddevice``.

    ``input_filter`` processes captured audio before it reaches consumers,
    preserving the input format and leaving playback untouched.
    """

    def __init__(
        self,
        *,
        input_device: int | str | None = None,
        output_device: int | str | None = None,
        input_sample_rate: int = 16_000,
        output_sample_rate: int = 48_000,
        input_channels: int = 1,
        output_channels: int = 1,
        block_ms: int = 20,
        capture_buffer_ms: int = 500,
        latency: float | Literal["low", "high"] = "low",
        echo_cancellation: EchoCancellation = "preferred",
        input_filter: AudioInputFilter | None = None,
    ) -> None:
        """Store local audio settings without opening a device."""

        if echo_cancellation not in {"disabled", "preferred", "required"}:
            raise ValueError(
                "echo_cancellation must be 'disabled', 'preferred', or 'required'"
            )
        if block_ms <= 0:
            raise ValueError("block_ms must be greater than zero")
        if capture_buffer_ms <= 0:
            raise ValueError("capture_buffer_ms must be greater than zero")
        if isinstance(latency, float) and latency <= 0:
            raise ValueError("latency must be greater than zero")

        input_format = AudioFormat(input_sample_rate, input_channels)
        output_format = AudioFormat(output_sample_rate, output_channels)
        aec_compatible = (
            input_device is None
            and output_device is None
            and input_format == MacOSVoiceProcessingBackend.INPUT_FORMAT
            and output_format == MacOSVoiceProcessingBackend.OUTPUT_FORMAT
        )
        if echo_cancellation == "required" and not aec_compatible:
            raise ValueError(
                "macOS echo cancellation requires default devices, "
                "16 kHz mono input, and 48 kHz mono output"
            )

        self._portaudio_settings = _PortAudioSettings(
            input_device=input_device,
            output_device=output_device,
            input_format=input_format,
            output_format=output_format,
            block_ms=block_ms,
            capture_buffer_ms=capture_buffer_ms,
            latency=latency,
        )
        self._allow_fallback = echo_cancellation == "preferred"
        self._using_voice_processing = False
        self._input_filter = input_filter
        self._lifecycle_lock = asyncio.Lock()
        self._started = False
        self._closed = False
        self._filter_started = False

        if echo_cancellation == "required" or (
            echo_cancellation == "preferred"
            and aec_compatible
            and MacOSVoiceProcessingBackend.is_available()
        ):
            self._backend = MacOSVoiceProcessingBackend(block_ms=block_ms)
            self._using_voice_processing = True
        else:
            self._backend = self._new_portaudio_backend()

    @property
    def input_format(self) -> AudioFormat:
        """Format produced by microphone capture."""

        return self._backend.input_format

    @property
    def output_format(self) -> AudioFormat:
        """Format accepted by playback."""

        return self._backend.output_format

    @property
    def played_frames(self) -> int:
        """Number of output frames confirmed by the active backend."""

        return self._backend.played_frames

    async def start(self) -> None:
        """Initialize the input filter, then start the local audio backend."""

        async with self._lifecycle_lock:
            if self._closed:
                raise AudioStateError("LocalAudio has already been closed")
            if self._started:
                return
            try:
                if self._input_filter is not None:
                    self._filter_started = True
                    await self._input_filter.start(self.input_format)
                await self._start_backend()
            except BaseException:
                await self._close_filter()
                raise
            self._started = True

    async def _start_backend(self) -> None:
        try:
            await self._backend.start()
        except AudioDeviceError as voice_processing_error:
            if not self._using_voice_processing or not self._allow_fallback:
                raise

            await asyncio.gather(self._backend.close(), return_exceptions=True)
            logger.warning(
                "macOS echo cancellation is unavailable; using PortAudio: %s",
                voice_processing_error,
            )
            self._backend = self._new_portaudio_backend()
            self._using_voice_processing = False
            try:
                await self._backend.start()
            except AudioDeviceError as portaudio_error:
                raise AudioDeviceError(
                    "Unable to start macOS VoiceProcessingIO or PortAudio: "
                    f"{voice_processing_error}; {portaudio_error}"
                ) from portaudio_error

    def capture(self) -> AsyncGenerator[AudioChunk, None]:
        """Yield microphone chunks until the audio component closes."""

        if self._input_filter is None:
            return self._backend.capture()
        return self._filtered_capture()

    async def _filtered_capture(self) -> AsyncGenerator[AudioChunk, None]:
        assert self._input_filter is not None
        async with aclosing(self._backend.capture()) as capture:
            async for chunk in capture:
                filtered = await self._input_filter.filter(chunk)
                if self._closed:
                    return
                if filtered is not None:
                    yield filtered

    async def write(self, chunk: AudioChunk) -> None:
        """Play one PCM chunk."""

        await self._backend.write(chunk)

    async def interrupt_playback(self) -> None:
        """Stop queued playback immediately."""

        await self._backend.interrupt_playback()

    async def wait_for_playback(self) -> None:
        """Wait until all previously written audio has played."""

        await self._backend.wait_for_playback()

    async def close(self) -> None:
        """Close the backend and release input-filter resources."""

        async with self._lifecycle_lock:
            self._closed = True
            self._started = False
            try:
                await self._backend.close()
            finally:
                await self._close_filter()

    async def _close_filter(self) -> None:
        if self._input_filter is not None and self._filter_started:
            await self._input_filter.close()
            self._filter_started = False

    def _new_portaudio_backend(self) -> PortAudioBackend:
        settings = self._portaudio_settings
        return PortAudioBackend(
            input_device=settings.input_device,
            output_device=settings.output_device,
            input_format=settings.input_format,
            output_format=settings.output_format,
            block_ms=settings.block_ms,
            capture_buffer_ms=settings.capture_buffer_ms,
            latency=settings.latency,
        )
