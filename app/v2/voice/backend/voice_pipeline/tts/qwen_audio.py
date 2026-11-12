"""Qwen Audio bidirectional streaming speech synthesis."""

import asyncio
import json
import ssl
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Self

import certifi
import websockets
from websockets.exceptions import ConnectionClosed

from ..audio import AudioChunk, AudioFormat
from .errors import TTSError, TTSStateError
from .protocols import TextInput, TTSOutput, TTSStream
from .types import TTSResult, TTSTextMark

_MODEL = "qwen-audio-3.0-tts-flash"
_RESPONSE_TIMEOUT = 30.0
_CANCEL_TIMEOUT = 1.0
_SUPPORTED_SAMPLE_RATES = {8000, 16000, 22050, 24000, 44100, 48000}


@dataclass(slots=True)
class _SynthesisState:
    input_characters: int = 0
    audio_bytes: int = 0
    completed: bool = False
    provider_usage: dict[str, int | float] | None = None

    def result(self) -> TTSResult:
        usage = dict(self.provider_usage) if self.provider_usage is not None else None
        return TTSResult(
            input_characters=self.input_characters,
            audio_bytes=self.audio_bytes,
            completed=self.completed,
            provider_usage=usage,
        )


class _SynthesisStream(AsyncIterator[TTSOutput]):
    """Deliver one provider-owned synthesis task to an audio consumer."""

    def __init__(self, tts: "QwenAudioTTS", text: TextInput) -> None:
        loop = asyncio.get_running_loop()
        self._tts = tts
        self._output: asyncio.Queue[TTSOutput] = asyncio.Queue(maxsize=1)
        self._state = _SynthesisState()
        self._task = loop.create_task(
            tts._run_synthesis(text, self._output, self._state),
            name="qwen-audio-tts-session",
        )
        self._closed = False

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> TTSOutput:
        if self._closed:
            raise StopAsyncIteration
        if self._task.done() and self._output.empty():
            await self._finish()
            raise StopAsyncIteration

        receive = asyncio.create_task(self._output.get(), name="qwen-audio-tts-output")
        try:
            done, _ = await asyncio.wait(
                {receive, self._task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if receive in done:
                return receive.result()

            receive.cancel()
            await asyncio.gather(receive, return_exceptions=True)
            if self._closed:
                raise StopAsyncIteration
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

    async def aclose(self) -> None:
        """Cancel synthesis without canceling the consuming task."""

        if self._closed:
            return
        self._closed = True
        if not self._task.done():
            self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._tts._release_stream(self)

    async def result(self) -> TTSResult:
        """Wait for synthesis to stop and return collected usage."""

        try:
            await asyncio.shield(self._task)
        except asyncio.CancelledError:
            if not self._task.cancelled():
                raise
        return self._state.result()

    async def _finish(self) -> None:
        self._closed = True
        try:
            await self._task
        finally:
            self._tts._release_stream(self)


class QwenAudioTTS:
    """Stream PCM and playback marks from Qwen Audio TTS Flash."""

    def __init__(
        self,
        *,
        api_key: str,
        workspace_id: str | None = None,
        voice: str = "longanhuan_v3.6",
        sample_rate: int = 48_000,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key must not be empty")
        if not voice.strip():
            raise ValueError("voice must not be empty")
        if sample_rate not in _SUPPORTED_SAMPLE_RATES:
            raise ValueError(
                f"sample_rate must be one of {sorted(_SUPPORTED_SAMPLE_RATES)}"
            )
        self._api_key = api_key
        self._voice = voice
        workspace = workspace_id.strip() if workspace_id else ""
        host = (
            f"{workspace}.cn-beijing.maas.aliyuncs.com"
            if workspace
            else "dashscope.aliyuncs.com"
        )
        self._url = f"wss://{host}/api-ws/v1/inference"
        self._output_format = AudioFormat(sample_rate, 1)
        self._websocket: Any | None = None
        self._stream: _SynthesisStream | None = None
        self._control_lock = asyncio.Lock()
        self._started = False
        self._closed = False

    @property
    def output_format(self) -> AudioFormat:
        return self._output_format

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()

    async def start(self) -> None:
        async with self._control_lock:
            if self._closed:
                raise TTSStateError("QwenAudioTTS has been closed")
            if not self._started:
                await self._connect()
                self._started = True

    def synthesize(self, text: TextInput) -> TTSStream:
        if self._closed or not self._started:
            raise TTSStateError("QwenAudioTTS must be started before synthesis")
        if self._stream is not None:
            raise TTSStateError("QwenAudioTTS supports one active stream at a time")
        stream = _SynthesisStream(self, text)
        self._stream = stream
        return stream

    async def close(self) -> None:
        async with self._control_lock:
            if self._closed:
                return
            self._closed = True
            if self._stream is not None:
                await self._stream.aclose()
            await self._disconnect()
            self._started = False

    async def _connect(self) -> None:
        try:
            self._websocket = await websockets.connect(
                self._url,
                additional_headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "user-agent": "sage-voice",
                },
                ssl=ssl.create_default_context(cafile=certifi.where()),
                max_size=10 * 1024 * 1024,
                open_timeout=15,
                close_timeout=3,
            )
        except Exception as error:
            raise TTSError(f"Unable to connect to Qwen Audio TTS: {error}") from error

    async def _disconnect(self) -> None:
        websocket, self._websocket = self._websocket, None
        if websocket is not None:
            with suppress(ConnectionClosed, OSError, TimeoutError):
                await websocket.close()

    @staticmethod
    async def _send(websocket: Any, task_id: str, action: str, payload: dict) -> None:
        await websocket.send(
            json.dumps(
                {
                    "header": {
                        "action": action,
                        "task_id": task_id,
                        "streaming": "duplex",
                    },
                    "payload": payload,
                },
                ensure_ascii=False,
            )
        )

    async def _open_task(self, task_id: str) -> Any:
        # A pooled connection may have expired while no synthesis was active.
        for attempt in range(2):
            if self._websocket is None:
                await self._connect()
            websocket = self._websocket
            assert websocket is not None
            try:
                await self._send(
                    websocket,
                    task_id,
                    "run-task",
                    {
                        "task_group": "audio",
                        "task": "tts",
                        "function": "SpeechSynthesizer",
                        "model": _MODEL,
                        "parameters": {
                            "text_type": "PlainText",
                            "voice": self._voice,
                            "format": "pcm",
                            "sample_rate": self.output_format.sample_rate,
                            "word_timestamp_enabled": True,
                        },
                        "input": {},
                    },
                )
                async with asyncio.timeout(_RESPONSE_TIMEOUT):
                    message = json.loads(await websocket.recv())
                self._raise_for_failure(message)
                if (
                    message["header"]["event"] != "task-started"
                    or message["header"]["task_id"] != task_id
                ):
                    raise TTSError("Unexpected Qwen Audio TTS task-start event")
                return websocket
            except (ConnectionClosed, OSError, TimeoutError):
                await self._disconnect()
                if attempt:
                    raise
        raise TTSError("Unable to start Qwen Audio TTS task")

    async def _run_synthesis(
        self,
        text: TextInput,
        output: asyncio.Queue[TTSOutput],
        state: _SynthesisState,
    ) -> None:
        task_id = str(uuid.uuid4())
        sender: asyncio.Task | None = None
        receiver: asyncio.Task | None = None
        task_started = False
        task_finished = False
        try:
            websocket = await self._open_task(task_id)
            task_started = True
            sender = asyncio.create_task(
                self._send_text(websocket, task_id, text, state)
            )
            seen: set[tuple[int, int, int]] = set()
            marked_sentences: set[int] = set()
            buffered = bytearray()
            while True:
                receiver = asyncio.create_task(websocket.recv())
                if not sender.done():
                    async with asyncio.timeout(_RESPONSE_TIMEOUT):
                        done, _ = await asyncio.wait(
                            {sender, receiver},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                    if sender in done:
                        await sender
                if sender.done():
                    await sender
                async with asyncio.timeout(_RESPONSE_TIMEOUT):
                    raw = await receiver
                receiver = None
                if isinstance(raw, bytes):
                    state.audio_bytes += len(raw)
                    buffered.extend(raw)
                    aligned = len(buffered) & ~1
                    if aligned:
                        await output.put(
                            AudioChunk(bytes(buffered[:aligned]), self.output_format)
                        )
                        del buffered[:aligned]
                    continue
                message = json.loads(raw)
                if message["header"].get("task_id") != task_id:
                    continue
                self._raise_for_failure(message)
                payload = message.get("payload", {})
                usage = payload.get("usage", {})
                if "characters" in usage:
                    state.provider_usage = {"characters": usage["characters"]}
                event = message["header"]["event"]
                if event == "task-finished":
                    task_finished = True
                    await sender
                    if buffered:
                        raise TTSError("Qwen Audio TTS returned incomplete PCM sample")
                    state.completed = True
                    return
                if event != "result-generated":
                    continue
                result = payload.get("output", {})
                sentence = result.get("sentence", {})
                index = sentence.get("index", 0)
                for word in sentence.get("words", []):
                    key = (index, word["begin_index"], word["end_index"])
                    if key in seen or not word["text"]:
                        continue
                    seen.add(key)
                    marked_sentences.add(index)
                    await output.put(
                        TTSTextMark(
                            text=word["text"],
                            at_frame=round(
                                word["begin_time"]
                                * self.output_format.sample_rate
                                / 1000
                            ),
                        )
                    )
                if (
                    result.get("type") == "sentence-end"
                    and index not in marked_sentences
                ):
                    sentence_text = result.get("original_text", "")
                    if sentence_text:
                        marked_sentences.add(index)
                        await output.put(
                            TTSTextMark(
                                text=sentence_text,
                                at_frame=state.audio_bytes
                                // self.output_format.frame_bytes,
                            )
                        )
        except asyncio.CancelledError:
            await self._stop_task(sender)
            await self._stop_task(receiver)
            if task_started and not task_finished:
                await self._cancel_task(task_id)
            elif not task_finished:
                await self._disconnect()
            raise
        except Exception as error:
            await self._disconnect()
            if isinstance(error, TTSError):
                raise
            raise TTSError(f"Qwen Audio TTS failed: {error}") from error
        finally:
            await self._stop_task(sender)
            await self._stop_task(receiver)

    async def _send_text(
        self,
        websocket: Any,
        task_id: str,
        text: TextInput,
        state: _SynthesisState,
    ) -> None:
        async for part in self._text_parts(text):
            for offset in range(0, len(part), 20_000):
                chunk = part[offset : offset + 20_000]
                await self._send(
                    websocket, task_id, "continue-task", {"input": {"text": chunk}}
                )
                state.input_characters += len(chunk)
        await self._send(websocket, task_id, "finish-task", {"input": {}})

    @staticmethod
    async def _text_parts(text: TextInput) -> AsyncIterator[str]:
        if isinstance(text, str):
            yield text
        else:
            async for part in text:
                yield part

    async def _cancel_task(self, task_id: str) -> None:
        websocket = self._websocket
        if websocket is None:
            return
        try:
            async with asyncio.timeout(_CANCEL_TIMEOUT):
                await self._send(
                    websocket,
                    task_id,
                    "finish-task",
                    {"input": {"directive": "cancel"}},
                )
                while True:
                    raw = await websocket.recv()
                    if isinstance(raw, bytes):
                        continue
                    message = json.loads(raw)
                    self._raise_for_failure(message)
                    header = message["header"]
                    if (
                        header.get("task_id") == task_id
                        and header["event"] == "task-finished"
                    ):
                        return
        except Exception:
            await self._disconnect()

    @staticmethod
    def _raise_for_failure(message: dict) -> None:
        header = message["header"]
        if header["event"] == "task-failed":
            raise TTSError(
                f"Qwen Audio TTS failed: {header.get('error_code')}: "
                f"{header.get('error_message')}"
            )

    @staticmethod
    async def _stop_task(task: asyncio.Task | None) -> None:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _release_stream(self, stream: _SynthesisStream) -> None:
        if self._stream is stream:
            self._stream = None
