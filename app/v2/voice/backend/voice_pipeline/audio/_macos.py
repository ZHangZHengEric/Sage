"""ctypes bridge for the macOS VoiceProcessingIO backend."""

import asyncio
import ctypes
import sys
from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from typing import Any

from .errors import AudioDeviceError, AudioFormatError, AudioStateError
from .types import AudioChunk, AudioFormat

_NATIVE_LIBRARY = (
    Path(__file__).resolve().parent / "_native" / "libLalkVoiceIO.dylib"
)
_CAPTURE_TIMEOUT_MS = 100


class MacOSVoiceProcessingBackend:
    """Duplex macOS audio backed by Apple's VoiceProcessingIO audio unit."""

    INPUT_FORMAT = AudioFormat(16_000, 1)
    OUTPUT_FORMAT = AudioFormat(48_000, 1)

    def __init__(self, *, block_ms: int) -> None:
        if block_ms <= 0:
            raise ValueError("block_ms must be greater than zero")

        self._block_frames = round(self.OUTPUT_FORMAT.sample_rate * block_ms / 1_000)
        self._capture_frames = round(self.INPUT_FORMAT.sample_rate * block_ms / 1_000)
        self._control_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._native_calls: set[asyncio.Task[int]] = set()

        self._library: Any | None = None
        self._handle: int | None = None
        self._started = False
        self._closed = False
        self._capture_active = False
        self._playback_generation = 0
        self._played_frames = 0

    @classmethod
    def is_available(cls) -> bool:
        """Return whether the native backend can be loaded on this machine."""

        return sys.platform == "darwin" and _NATIVE_LIBRARY.is_file()

    @property
    def input_format(self) -> AudioFormat:
        return self.INPUT_FORMAT

    @property
    def output_format(self) -> AudioFormat:
        return self.OUTPUT_FORMAT

    @property
    def played_frames(self) -> int:
        library = self._library
        handle = self._handle
        if self._closed or library is None or handle is None:
            return self._played_frames
        return int(library.lalk_voice_io_played_frames(handle))

    async def start(self) -> None:
        async with self._control_lock:
            if self._closed:
                raise AudioStateError("LocalAudio has already been closed")
            if self._started:
                return
            if sys.platform != "darwin":
                raise AudioDeviceError(
                    "macOS echo cancellation is only available on macOS"
                )

            try:
                library = _load_library(_NATIVE_LIBRARY)
            except (FileNotFoundError, OSError) as error:
                raise AudioDeviceError(str(error)) from error

            handle = library.lalk_voice_io_create()
            if not handle:
                raise AudioDeviceError("Unable to create macOS VoiceProcessingIO")

            self._library = library
            self._handle = handle
            try:
                result = await self._call_native(
                    library.lalk_voice_io_start,
                    handle,
                )
                if result != 0:
                    raise self._native_error("Unable to start macOS VoiceProcessingIO")
            except BaseException:
                if self._native_calls:
                    await asyncio.gather(
                        *tuple(self._native_calls), return_exceptions=True
                    )
                library.lalk_voice_io_stop(handle)
                library.lalk_voice_io_destroy(handle)
                self._library = None
                self._handle = None
                raise

            self._started = True

    async def capture(self) -> AsyncGenerator[AudioChunk, None]:
        self._ensure_started()
        if self._capture_active:
            raise AudioStateError("LocalAudio.capture() supports only one consumer")

        self._capture_active = True
        samples = (ctypes.c_int16 * self._capture_frames)()
        try:
            while True:
                library, handle = self._require_native()
                result = await self._call_native(
                    library.lalk_voice_io_read_capture,
                    handle,
                    samples,
                    self._capture_frames,
                    _CAPTURE_TIMEOUT_MS,
                )
                if self._closed:
                    return
                if result > 0:
                    data = ctypes.string_at(
                        samples, result * ctypes.sizeof(ctypes.c_int16)
                    )
                    yield AudioChunk(data=data, format=self.INPUT_FORMAT)
                elif result == 0:
                    continue
                elif result == -1 or self._closed:
                    return
                else:
                    raise self._native_error("macOS microphone capture failed")
        finally:
            self._capture_active = False

    async def write(self, chunk: AudioChunk) -> None:
        self._ensure_started()
        if chunk.format != self.OUTPUT_FORMAT:
            raise AudioFormatError(
                f"Playback requires {self.OUTPUT_FORMAT!r}, received {chunk.format!r}"
            )
        if not chunk.data:
            return

        generation = self._playback_generation
        block_bytes = self._block_frames * self.OUTPUT_FORMAT.frame_bytes
        async with self._write_lock:
            self._ensure_started()
            for offset in range(0, len(chunk.data), block_bytes):
                if generation != self._playback_generation:
                    return
                data = chunk.data[offset : offset + block_bytes]
                samples = (ctypes.c_int16 * (len(data) // 2)).from_buffer_copy(data)
                library, handle = self._require_native()
                result = await self._call_native(
                    library.lalk_voice_io_write_playback,
                    handle,
                    samples,
                    len(samples),
                )
                if result == 0:
                    return
                if result < 0:
                    raise self._native_error("macOS audio playback failed")

    async def wait_for_playback(self) -> None:
        self._ensure_started()
        library, handle = self._require_native()
        result = await self._call_native(
            library.lalk_voice_io_wait_playback,
            handle,
        )
        if result < 0:
            raise self._native_error("Unable to finish macOS audio playback")

    async def interrupt_playback(self) -> None:
        async with self._control_lock:
            self._ensure_started()
            self._playback_generation += 1
            library, handle = self._require_native()
            result = await self._call_native(
                library.lalk_voice_io_interrupt_playback,
                handle,
            )
            if result != 0:
                raise self._native_error("Unable to interrupt macOS audio playback")

    async def close(self) -> None:
        async with self._control_lock:
            if self._closed:
                return
            self._closed = True
            self._playback_generation += 1

            library = self._library
            handle = self._handle
            if library is None or handle is None:
                return

            if self._started:
                await asyncio.to_thread(library.lalk_voice_io_stop, handle)
                self._started = False
            if self._native_calls:
                await asyncio.gather(*tuple(self._native_calls), return_exceptions=True)

            self._played_frames = int(
                library.lalk_voice_io_played_frames(handle)
            )
            library.lalk_voice_io_destroy(handle)
            self._library = None
            self._handle = None

    async def _call_native(self, function: Callable[..., int], *args: object) -> int:
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        self._native_calls.add(task)
        task.add_done_callback(self._native_calls.discard)
        return await asyncio.shield(task)

    def _native_error(self, prefix: str) -> AudioDeviceError:
        library = self._library
        handle = self._handle
        if library is None or handle is None:
            return AudioDeviceError(prefix)

        buffer = ctypes.create_string_buffer(2_048)
        library.lalk_voice_io_copy_last_error(
            handle,
            buffer,
            len(buffer),
        )
        detail = buffer.value.decode("utf-8", "replace")
        return AudioDeviceError(f"{prefix}: {detail}" if detail else prefix)

    def _require_native(self) -> tuple[Any, int]:
        if self._library is None or self._handle is None:
            raise AudioStateError("macOS VoiceProcessingIO is unavailable")
        return self._library, self._handle

    def _ensure_started(self) -> None:
        if self._closed:
            raise AudioStateError("LocalAudio has been closed")
        if not self._started:
            raise AudioStateError("LocalAudio has not been started")


def _load_library(path: Path) -> ctypes.CDLL:
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing macOS VoiceProcessingIO library: {path}. "
            "Run scripts/build_macos_voice_processing.py first."
        )

    library = ctypes.CDLL(str(path))
    handle = ctypes.c_void_p
    int16_pointer = ctypes.POINTER(ctypes.c_int16)

    library.lalk_voice_io_create.argtypes = []
    library.lalk_voice_io_create.restype = handle
    library.lalk_voice_io_destroy.argtypes = [handle]
    library.lalk_voice_io_destroy.restype = None
    library.lalk_voice_io_start.argtypes = [handle]
    library.lalk_voice_io_start.restype = ctypes.c_int32
    library.lalk_voice_io_stop.argtypes = [handle]
    library.lalk_voice_io_stop.restype = None
    library.lalk_voice_io_read_capture.argtypes = [
        handle,
        int16_pointer,
        ctypes.c_int32,
        ctypes.c_int32,
    ]
    library.lalk_voice_io_read_capture.restype = ctypes.c_int32
    library.lalk_voice_io_write_playback.argtypes = [
        handle,
        int16_pointer,
        ctypes.c_int32,
    ]
    library.lalk_voice_io_write_playback.restype = ctypes.c_int32
    library.lalk_voice_io_played_frames.argtypes = [handle]
    library.lalk_voice_io_played_frames.restype = ctypes.c_uint64
    library.lalk_voice_io_wait_playback.argtypes = [handle]
    library.lalk_voice_io_wait_playback.restype = ctypes.c_int32
    library.lalk_voice_io_interrupt_playback.argtypes = [handle]
    library.lalk_voice_io_interrupt_playback.restype = ctypes.c_int32
    library.lalk_voice_io_copy_last_error.argtypes = [
        handle,
        ctypes.POINTER(ctypes.c_char),
        ctypes.c_int32,
    ]
    library.lalk_voice_io_copy_last_error.restype = ctypes.c_int32
    return library
