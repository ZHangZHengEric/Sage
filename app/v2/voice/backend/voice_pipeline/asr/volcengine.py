"""Volcengine Seed ASR bidirectional streaming speech recognition."""

import asyncio
import gzip
import json
import ssl
import struct
import uuid
from dataclasses import dataclass
from typing import Any, Self

import certifi
import websockets

from ..audio import AudioChunk, AudioFormat
from .errors import ASRError, ASRFormatError, ASRStateError
from .types import ASRResult, Transcript

_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
_RESOURCE_ID = "volc.seedasr.sauc.duration"
_INPUT_FORMAT = AudioFormat(16_000)
_AUDIO_BATCH_BYTES = 3_200  # 100 ms of 16 kHz mono PCM16 audio.
_FINISH_TIMEOUT = 30.0


def _encode_frame(payload: bytes, *, audio: bool = False, last: bool = False) -> bytes:
    body = gzip.compress(payload)
    header = bytes(
        (
            0x11,
            (0x20 if audio else 0x10) | (2 if last else 0),
            0x01 if audio else 0x11,
            0,
        )
    )
    return header + struct.pack(">I", len(body)) + body


def _decode_frame(data: bytes) -> tuple[dict[str, Any], bool]:
    """Decode the response envelope, including optional sequence and event fields."""
    if len(data) < 4:
        raise ASRError("Truncated Volcengine ASR header")
    offset = (data[0] & 15) * 4
    kind, flags = data[1] >> 4, data[1] & 15
    if offset < 4 or kind not in (9, 15):
        raise ASRError("Invalid Volcengine ASR response header")
    if flags & 1:
        offset += 4
    if flags & 4:
        offset += 4
    code = None
    if kind == 15:
        code = struct.unpack_from(">I", data, offset)[0]
        offset += 4
    size = struct.unpack_from(">I", data, offset)[0]
    body = data[offset + 4 :]
    if len(body) != size:
        raise ASRError("Truncated Volcengine ASR payload")
    compression = data[2] & 15
    if compression == 1:
        body = gzip.decompress(body)
    elif compression != 0:
        raise ASRError("Unsupported Volcengine ASR compression")
    payload = json.loads(body)
    if code is not None:
        raise ASRError(f"Volcengine ASR error {code}: {payload}")
    if not isinstance(payload, dict):
        raise ASRError("Volcengine ASR response must be a JSON object")
    return payload, bool(flags & 2)


@dataclass(slots=True)
class _RecognitionState:
    input_bytes: int = 0
    output_characters: int = 0
    completed: bool = False

    def result(self, audio_format: AudioFormat) -> ASRResult:
        return ASRResult(
            input_audio_seconds=(
                self.input_bytes / audio_format.frame_bytes / audio_format.sample_rate
            ),
            output_characters=self.output_characters,
            completed=self.completed,
        )


class _VolcengineStream:
    """Move audio and transcripts for one Volcengine task."""

    def __init__(self, asr: "VolcengineASR") -> None:
        loop = asyncio.get_running_loop()
        self._asr = asr
        self._audio: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._output: asyncio.Queue[Transcript] = asyncio.Queue()
        self._state = _RecognitionState()
        self._task = loop.create_task(
            asr._run_recognition(self._audio, self._output, self._state),
            name="volcengine-asr-task",
        )
        self._input_finished = False
        self._closed = False

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> Transcript:
        if self._closed:
            raise StopAsyncIteration
        if self._task.done() and self._output.empty():
            await self._finish()
            raise StopAsyncIteration

        receive = asyncio.create_task(
            self._output.get(),
            name="volcengine-asr-output",
        )
        try:
            done, _ = await asyncio.wait(
                {receive, self._task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if receive in done:
                return receive.result()

            receive.cancel()
            await asyncio.gather(receive, return_exceptions=True)
            if not self._output.empty():
                return self._output.get_nowait()

            await self._finish()
            raise StopAsyncIteration
        except asyncio.CancelledError:
            await self.aclose()
            raise
        finally:
            if not receive.done():
                receive.cancel()
                await asyncio.gather(receive, return_exceptions=True)

    async def write(self, audio: AudioChunk) -> None:
        """Queue one 16 kHz mono PCM chunk for Volcengine."""

        if self._task.done():
            await self._task
        if self._closed or self._input_finished:
            raise ASRStateError("Volcengine ASR input has already finished")
        if audio.format != self._asr.input_format:
            raise ASRFormatError(
                f"VolcengineASR requires {self._asr.input_format!r}, "
                f"received {audio.format!r}"
            )
        if audio.data:
            self._state.input_bytes += len(audio.data)
            await self._audio.put(audio.data)

    async def finish(self) -> None:
        """End audio input and wait for the final response frame."""

        if self._closed:
            return
        if not self._input_finished:
            self._input_finished = True
            await self._audio.put(None)
        await asyncio.shield(self._task)

    async def aclose(self) -> None:
        """Cancel recognition without cancelling the consuming task."""

        if self._closed:
            return
        self._closed = True
        if not self._task.done():
            self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._asr._release_stream(self)

    async def result(self) -> ASRResult:
        """Wait for recognition to stop and return collected usage."""

        try:
            await asyncio.shield(self._task)
        except asyncio.CancelledError:
            if not self._task.cancelled():
                raise
        return self._state.result(self._asr.input_format)

    async def _finish(self) -> None:
        self._closed = True
        try:
            await self._task
        finally:
            self._asr._release_stream(self)


class VolcengineASR:
    """Stream PCM to Seed ASR; each recognition owns its WebSocket connection."""

    def __init__(self, *, api_key: str, resource_id: str = _RESOURCE_ID) -> None:
        if not api_key.strip():
            raise ValueError("api_key must not be empty")
        if not resource_id.strip():
            raise ValueError("resource_id must not be empty")
        self._api_key = api_key
        self._resource_id = resource_id
        self._started = False
        self._closed = False
        self._stream: _VolcengineStream | None = None

    @property
    def input_format(self) -> AudioFormat:
        return _INPUT_FORMAT

    @property
    def supports_interim_transcripts(self) -> bool:
        return True

    async def __aenter__(self) -> Self:
        await self.start(_INPUT_FORMAT)
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()

    async def start(self, input_format: AudioFormat) -> None:
        if self._closed:
            raise ASRStateError("VolcengineASR has already been closed")
        if input_format != _INPUT_FORMAT:
            raise ASRFormatError(
                f"VolcengineASR requires {_INPUT_FORMAT!r}, received {input_format!r}"
            )
        self._started = True

    def recognize(self) -> _VolcengineStream:
        if self._closed or not self._started:
            raise ASRStateError("VolcengineASR is not started or has been closed")
        if self._stream is not None:
            raise ASRStateError("VolcengineASR supports one active stream at a time")
        self._stream = _VolcengineStream(self)
        return self._stream

    async def close(self) -> None:
        self._closed = True
        self._started = False
        if self._stream is not None:
            await self._stream.aclose()

    def _release_stream(self, stream: _VolcengineStream) -> None:
        if self._stream is stream:
            self._stream = None

    async def _run_recognition(
        self,
        audio: asyncio.Queue[bytes | None],
        output: asyncio.Queue[Transcript],
        state: _RecognitionState,
    ) -> None:
        tasks: list[asyncio.Task[None]] = []
        try:
            async with websockets.connect(
                _URL,
                additional_headers={
                    "X-Api-Key": self._api_key,
                    "X-Api-Resource-Id": self._resource_id,
                    "X-Api-Request-Id": str(uuid.uuid4()),
                },
                ssl=ssl.create_default_context(cafile=certifi.where()),
                open_timeout=15,
                close_timeout=5,
                max_size=10 * 1024 * 1024,
            ) as websocket:
                request = {
                    "user": {"uid": "sage-voice"},
                    "audio": {
                        "format": "pcm",
                        "codec": "raw",
                        "rate": 16000,
                        "bits": 16,
                        "channel": 1,
                    },
                    "request": {
                        "model_name": "bigmodel",
                        "enable_nonstream": True,
                        "show_utterances": True,
                        "result_type": "single",
                    },
                }
                await websocket.send(_encode_frame(json.dumps(request).encode()))
                sender = asyncio.create_task(self._send_audio(websocket, audio))
                receiver = asyncio.create_task(
                    self._receive_transcripts(websocket, output, state)
                )
                tasks.extend((sender, receiver))
                try:
                    done, _ = await asyncio.wait(
                        tasks, return_when=asyncio.FIRST_COMPLETED
                    )
                    if receiver in done:
                        await receiver
                        if not sender.done():
                            raise ASRError("Volcengine ASR ended before audio input")
                    await sender
                    async with asyncio.timeout(_FINISH_TIMEOUT):
                        await receiver
                    state.completed = True
                finally:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except ASRError:
            raise
        except Exception as error:
            raise ASRError(f"Volcengine ASR failed: {error}") from error

    @staticmethod
    async def _send_audio(websocket: Any, audio: asyncio.Queue[bytes | None]) -> None:
        buffered = bytearray()
        while True:
            chunk = await audio.get()
            if chunk is None:
                await websocket.send(
                    _encode_frame(bytes(buffered), audio=True, last=True)
                )
                return
            buffered.extend(chunk)
            while len(buffered) >= _AUDIO_BATCH_BYTES:
                await websocket.send(
                    _encode_frame(bytes(buffered[:_AUDIO_BATCH_BYTES]), audio=True)
                )
                del buffered[:_AUDIO_BATCH_BYTES]

    @staticmethod
    async def _receive_transcripts(
        websocket: Any,
        output: asyncio.Queue[Transcript],
        state: _RecognitionState,
    ) -> None:
        last_interim: str | None = None
        while True:
            payload, last = _decode_frame(await websocket.recv())
            for utterance in payload.get("result", {}).get("utterances", []):
                text = utterance["text"]
                final = utterance["definite"]
                if not text:
                    continue
                if final:
                    last_interim = None
                    state.output_characters += len(text)
                elif text == last_interim:
                    continue
                else:
                    last_interim = text
                await output.put(Transcript(text=text, is_final=final))
            if last:
                return
