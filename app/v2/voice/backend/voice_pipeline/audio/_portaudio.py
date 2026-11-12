"""PortAudio implementation used by :mod:`lalk.audio.local`."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable
from typing import Any, Literal

import sounddevice as sd

from .errors import AudioDeviceError, AudioFormatError, AudioStateError
from .types import AudioChunk, AudioFormat

logger = logging.getLogger(__name__)


class _CaptureClosed:
    pass


_CAPTURE_CLOSED = _CaptureClosed()
_CaptureItem = AudioChunk | AudioDeviceError | _CaptureClosed


class PortAudioBackend:
    """Capture and play signed 16-bit PCM through PortAudio."""

    def __init__(
        self,
        *,
        input_device: int | str | None,
        output_device: int | str | None,
        input_format: AudioFormat,
        output_format: AudioFormat,
        block_ms: int,
        capture_buffer_ms: int,
        latency: float | Literal["low", "high"],
    ) -> None:
        self._input_device = input_device
        self._output_device = output_device
        self._input_format = input_format
        self._output_format = output_format
        self._block_ms = block_ms
        self._capture_buffer_ms = capture_buffer_ms
        self._latency = latency

        self._control_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._output_device_lock = asyncio.Lock()

        self._input_stream: Any | None = None
        self._output_stream: Any | None = None
        self._input_queue: asyncio.Queue[_CaptureItem] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._input_error: AudioDeviceError | None = None

        self._started = False
        self._closed = False
        self._capture_active = False
        self._playback_generation = 0
        self._played_frames = 0

    @property
    def input_format(self) -> AudioFormat:
        return self._input_format

    @property
    def output_format(self) -> AudioFormat:
        return self._output_format

    @property
    def played_frames(self) -> int:
        return self._played_frames

    async def start(self) -> None:
        async with self._control_lock:
            if self._closed:
                raise AudioStateError("LocalAudio has already been closed")
            if self._started:
                return

            self._initialize_capture_queue()
            try:
                self._check_device_formats()
                self._input_stream = sd.RawInputStream(
                    device=self._input_device,
                    samplerate=self._input_format.sample_rate,
                    channels=self._input_format.channels,
                    dtype="int16",
                    blocksize=self._block_frames(self._input_format.sample_rate),
                    latency=self._latency,
                    callback=self._input_callback,
                    finished_callback=self._input_finished_callback,
                )
                self._output_stream = sd.RawOutputStream(
                    device=self._output_device,
                    samplerate=self._output_format.sample_rate,
                    channels=self._output_format.channels,
                    dtype="int16",
                    blocksize=self._block_frames(self._output_format.sample_rate),
                    latency=self._latency,
                )
                await asyncio.to_thread(self._output_stream.start)
                await asyncio.to_thread(self._input_stream.start)
            except Exception as error:
                await self._close_streams()
                raise AudioDeviceError(
                    f"Unable to start local audio: {error}"
                ) from error

            self._started = True

    async def capture(self) -> AsyncGenerator[AudioChunk, None]:
        self._ensure_started()
        if self._capture_active:
            raise AudioStateError("LocalAudio.capture() supports only one consumer")
        if self._input_queue is None:
            raise AudioStateError("LocalAudio input queue is unavailable")
        if self._input_error is not None:
            raise self._input_error

        self._capture_active = True
        try:
            while True:
                item = await self._input_queue.get()
                if item is _CAPTURE_CLOSED:
                    return
                if isinstance(item, AudioDeviceError):
                    raise item
                if isinstance(item, AudioChunk):
                    yield item
        finally:
            self._capture_active = False

    async def write(self, chunk: AudioChunk) -> None:
        self._ensure_started()
        if chunk.format != self._output_format:
            raise AudioFormatError(
                f"Playback requires {self._output_format!r}, received {chunk.format!r}"
            )
        if not chunk.data:
            return

        generation = self._playback_generation
        block_bytes = self._block_frames(self._output_format.sample_rate)
        block_bytes *= self._output_format.frame_bytes

        async with self._write_lock:
            self._ensure_started()
            for offset in range(0, len(chunk.data), block_bytes):
                if generation != self._playback_generation:
                    return
                await self._write_block(
                    chunk.data[offset : offset + block_bytes], generation
                )

    async def interrupt_playback(self) -> None:
        async with self._control_lock:
            self._ensure_started()
            self._playback_generation += 1

            async with self._output_device_lock:
                stream = self._require_output_stream()
                try:
                    await asyncio.to_thread(stream.abort)
                    await asyncio.to_thread(stream.start)
                except Exception as error:
                    raise AudioDeviceError(
                        f"Unable to interrupt local playback: {error}"
                    ) from error

    async def wait_for_playback(self) -> None:
        """Wait until previously written audio has reached the device."""

        self._ensure_started()

    async def close(self) -> None:
        async with self._control_lock:
            if self._closed:
                return
            self._closed = True
            self._started = False
            self._playback_generation += 1
            self._finish_capture()

            async with self._output_device_lock:
                error = await self._close_streams()
            if error is not None:
                raise AudioDeviceError(
                    f"Unable to close local audio: {error}"
                ) from error

    async def _write_block(self, data: bytes, generation: int) -> None:
        async with self._output_device_lock:
            self._ensure_started()
            if generation != self._playback_generation:
                return
            stream = self._require_output_stream()
            try:
                await asyncio.to_thread(stream.write, data)
            except Exception as error:
                raise AudioDeviceError(
                    f"Unable to play local audio: {error}"
                ) from error
            self._played_frames += self._output_format.frame_count(data)

    def _initialize_capture_queue(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._input_error = None
        capture_chunks = max(
            1,
            (self._capture_buffer_ms + self._block_ms - 1) // self._block_ms,
        )
        self._input_queue = asyncio.Queue(maxsize=capture_chunks)

    def _check_device_formats(self) -> None:
        sd.check_input_settings(
            device=self._input_device,
            channels=self._input_format.channels,
            dtype="int16",
            samplerate=self._input_format.sample_rate,
        )
        sd.check_output_settings(
            device=self._output_device,
            channels=self._output_format.channels,
            dtype="int16",
            samplerate=self._output_format.sample_rate,
        )

    def _input_callback(
        self,
        indata: Any,
        frames: int,
        _time_info: Any,
        status: Any,
    ) -> None:
        if status:
            logger.warning("Local audio input status: %s", status)
        data = bytes(indata)
        expected_bytes = frames * self._input_format.frame_bytes
        if len(data) != expected_bytes:
            logger.error(
                "Ignoring malformed input block: expected %s bytes, received %s",
                expected_bytes,
                len(data),
            )
            return
        self._call_soon(self._enqueue_input, data)

    def _input_finished_callback(self) -> None:
        self._call_soon(self._report_input_failure)

    def _report_input_failure(self) -> None:
        if self._closed or not self._started or self._input_error is not None:
            return
        self._input_error = AudioDeviceError(
            "Local audio input stream stopped unexpectedly"
        )
        self._finish_capture(self._input_error)

    def _enqueue_input(self, data: bytes) -> None:
        queue = self._input_queue
        if (
            queue is None
            or self._closed
            or not self._started
            or self._input_error is not None
        ):
            return
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(AudioChunk(data=data, format=self._input_format))

    def _finish_capture(self, final_item: _CaptureItem = _CAPTURE_CLOSED) -> None:
        queue = self._input_queue
        if queue is None:
            return
        while not queue.empty():
            queue.get_nowait()
        queue.put_nowait(final_item)

    def _call_soon(self, callback: Callable[..., None], *args: object) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(callback, *args)

    def _require_output_stream(self) -> Any:
        if self._output_stream is None:
            raise AudioStateError("LocalAudio output stream is unavailable")
        return self._output_stream

    def _ensure_started(self) -> None:
        if self._closed:
            raise AudioStateError("LocalAudio has been closed")
        if not self._started:
            raise AudioStateError("LocalAudio has not been started")

    def _block_frames(self, sample_rate: int) -> int:
        return max(1, round(sample_rate * self._block_ms / 1_000))

    async def _close_streams(self) -> Exception | None:
        first_error: Exception | None = None
        for stream in (self._input_stream, self._output_stream):
            if stream is None:
                continue
            for operation in (stream.stop, stream.close):
                try:
                    await asyncio.to_thread(operation)
                except Exception as error:  # noqa: BLE001
                    if first_error is None:
                        first_error = error
        self._input_stream = None
        self._output_stream = None
        return first_error
