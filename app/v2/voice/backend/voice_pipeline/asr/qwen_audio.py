"""Qwen Audio bidirectional streaming speech recognition."""

import asyncio
import json
import ssl
import uuid
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Self

import certifi
import websockets
from websockets.exceptions import ConnectionClosed

from ..audio import AudioChunk, AudioFormat
from .errors import ASRError, ASRFormatError, ASRStateError
from .types import ASRResult, Transcript

_MODEL = "qwen-audio-3.0-asr-flash-streaming"
_INPUT_FORMAT = AudioFormat(sample_rate=16_000, channels=1)
_AUDIO_BATCH_BYTES = 3_200
_MAX_MESSAGE_SIZE = 10 * 1024 * 1024
_START_TIMEOUT = 15.0
_FINISH_TIMEOUT = 30.0


@dataclass(slots=True)
class _RecognitionState:
    input_bytes: int = 0
    output_characters: int = 0
    completed: bool = False
    billable_duration: int | float | None = None

    def result(self, audio_format: AudioFormat) -> ASRResult:
        usage = (
            {"duration": self.billable_duration}
            if self.billable_duration is not None
            else None
        )
        return ASRResult(
            input_audio_seconds=(
                self.input_bytes
                / audio_format.frame_bytes
                / audio_format.sample_rate
            ),
            output_characters=self.output_characters,
            completed=self.completed,
            provider_usage=usage,
        )


class _QwenAudioStream:
    """Move audio and transcripts for one Qwen Audio task."""

    def __init__(self, asr: "QwenAudioASR") -> None:
        loop = asyncio.get_running_loop()
        self._asr = asr
        self._audio: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._output: asyncio.Queue[Transcript] = asyncio.Queue()
        self._state = _RecognitionState()
        self._task = loop.create_task(
            asr._run_recognition(self._audio, self._output, self._state),
            name="qwen-audio-asr-task",
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
            name="qwen-audio-asr-output",
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
        """Queue one 16 kHz mono PCM chunk for Qwen Audio."""

        if self._task.done():
            await self._task
        if self._closed or self._input_finished:
            raise ASRStateError("Qwen Audio ASR input has already finished")
        if audio.format != self._asr.input_format:
            raise ASRFormatError(
                f"QwenAudioASR requires {self._asr.input_format!r}, "
                f"received {audio.format!r}"
            )
        if audio.data:
            self._state.input_bytes += len(audio.data)
            await self._audio.put(audio.data)

    async def finish(self) -> None:
        """End audio input and wait for task-finished."""

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


class QwenAudioASR:
    """Stream 16 kHz mono PCM to Qwen Audio and yield live transcripts."""

    @property
    def supports_interim_transcripts(self) -> bool:
        """Qwen Audio emits live partial transcripts."""

        return True

    def __init__(
        self,
        *,
        api_key: str,
        workspace_id: str | None = None,
        model: str = _MODEL,
        speech_noise_threshold: float | None = None,
        max_sentence_silence_ms: int | None = None,
        heartbeat: bool = False,
    ) -> None:
        """Store Alibaba Cloud settings without opening a connection."""

        if not api_key.strip():
            raise ValueError("api_key must not be empty")
        if not model.strip():
            raise ValueError("model must not be empty")
        if (
            speech_noise_threshold is not None
            and not -1.0 <= speech_noise_threshold <= 1.0
        ):
            raise ValueError("speech_noise_threshold must be between -1.0 and 1.0")
        if max_sentence_silence_ms is not None and not (
            200 <= max_sentence_silence_ms <= 6_000
        ):
            raise ValueError(
                "max_sentence_silence_ms must be between 200 and 6000"
            )

        self._api_key = api_key
        self._model = model
        self._speech_noise_threshold = speech_noise_threshold
        self._max_sentence_silence_ms = max_sentence_silence_ms
        self._heartbeat = heartbeat
        workspace_id = workspace_id.strip() if workspace_id else ""
        self._url = (
            f"wss://{workspace_id}.cn-beijing.maas.aliyuncs.com"
            "/api-ws/v1/inference"
            if workspace_id
            else "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
        )
        self._control_lock = asyncio.Lock()
        self._websocket: Any | None = None
        self._stream: _QwenAudioStream | None = None
        self._started = False
        self._closed = False

    @property
    def input_format(self) -> AudioFormat:
        """PCM format accepted by recognition streams."""

        return _INPUT_FORMAT

    async def __aenter__(self) -> Self:
        await self.start(_INPUT_FORMAT)
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()

    async def start(self, input_format: AudioFormat) -> None:
        """Open the persistent Qwen Audio WebSocket connection."""

        async with self._control_lock:
            if self._closed:
                raise ASRStateError("QwenAudioASR has already been closed")
            if input_format != _INPUT_FORMAT:
                raise ASRFormatError(
                    f"QwenAudioASR requires {_INPUT_FORMAT!r}, "
                    f"received {input_format!r}"
                )
            if self._started:
                return
            await self._connect()
            self._started = True

    def recognize(self) -> _QwenAudioStream:
        """Create one Qwen Audio duplex recognition task."""

        self._ensure_started()
        if self._stream is not None:
            raise ASRStateError("QwenAudioASR supports one active stream at a time")
        stream = _QwenAudioStream(self)
        self._stream = stream
        return stream

    async def close(self) -> None:
        """Cancel active recognition and close the provider connection."""

        async with self._control_lock:
            if self._closed:
                return
            self._closed = True
            self._started = False

            stream = self._stream
            if stream is not None:
                await stream.aclose()
            await self._disconnect()

    async def _run_recognition(
        self,
        audio: asyncio.Queue[bytes | None],
        output: asyncio.Queue[Transcript],
        state: _RecognitionState,
    ) -> None:
        sender: asyncio.Task[None] | None = None
        receiver: asyncio.Task[None] | None = None

        try:
            task_id = await self._open_task()
            sender = asyncio.create_task(
                self._send_audio(audio, task_id),
                name="qwen-audio-asr-audio",
            )
            receiver = asyncio.create_task(
                self._receive_transcripts(output, task_id, state),
                name="qwen-audio-asr-results",
            )

            done, _ = await asyncio.wait(
                {sender, receiver},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if receiver in done:
                await receiver
                if not sender.done():
                    raise ASRError("Qwen Audio ASR task ended before audio input")

            await sender
            async with asyncio.timeout(_FINISH_TIMEOUT):
                await receiver
            state.completed = True
        except asyncio.CancelledError:
            raise
        except ASRError:
            raise
        except Exception as error:
            raise ASRError(f"Qwen Audio ASR failed: {error}") from error
        finally:
            await self._stop_task(sender)
            await self._stop_task(receiver)
            if not state.completed:
                await self._drop_connection()

    async def _connect(self) -> None:
        websocket: Any | None = None
        try:
            websocket = await websockets.connect(
                self._url,
                ssl=ssl.create_default_context(cafile=certifi.where()),
                additional_headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "user-agent": "sage-voice",
                },
                max_size=_MAX_MESSAGE_SIZE,
                open_timeout=_START_TIMEOUT,
                close_timeout=5,
            )
        except asyncio.CancelledError:
            if websocket is not None:
                await websocket.close()
            raise
        except Exception as error:
            if websocket is not None:
                await websocket.close()
            raise ASRError(f"Unable to connect to Qwen Audio ASR: {error}") from error
        self._websocket = websocket

    async def _open_task(self) -> str:
        try:
            for attempt in range(2):
                if self._websocket is None:
                    await self._connect()
                websocket = self._require_websocket()
                task_id = uuid.uuid4().hex
                try:
                    await websocket.send(self._run_task_message(task_id))
                    async with asyncio.timeout(_START_TIMEOUT):
                        message = await self._receive_event(websocket)
                    self._raise_for_failure(message)
                    header = self._header(message)
                    if (
                        header.get("event") != "task-started"
                        or header.get("task_id") != task_id
                    ):
                        raise ASRError(
                            "Qwen Audio ASR returned an unexpected task-start event"
                        )
                    return task_id
                except (ConnectionClosed, OSError, TimeoutError):
                    await self._drop_connection()
                    if attempt:
                        raise
        except asyncio.CancelledError:
            await self._drop_connection()
            raise
        except Exception:
            await self._drop_connection()
            raise
        raise ASRError("Unable to start Qwen Audio ASR task")

    def _run_task_message(self, task_id: str) -> str:
        parameters: dict[str, Any] = {
            "format": "pcm",
            "sample_rate": _INPUT_FORMAT.sample_rate,
            "semantic_punctuation_enabled": False,
        }
        if self._speech_noise_threshold is not None:
            parameters["speech_noise_threshold"] = self._speech_noise_threshold
        if self._max_sentence_silence_ms is not None:
            parameters["max_sentence_silence"] = self._max_sentence_silence_ms
        if self._heartbeat:
            parameters["heartbeat"] = True

        return json.dumps(
            {
                "header": {
                    "action": "run-task",
                    "task_id": task_id,
                    "streaming": "duplex",
                },
                "payload": {
                    "task_group": "audio",
                    "task": "asr",
                    "function": "recognition",
                    "model": self._model,
                    "parameters": parameters,
                    "input": {},
                },
            },
            ensure_ascii=False,
        )

    async def _send_audio(
        self,
        audio: asyncio.Queue[bytes | None],
        task_id: str,
    ) -> None:
        websocket = self._require_websocket()
        buffered = bytearray()

        while True:
            chunk = await audio.get()
            if chunk is None:
                if buffered:
                    await websocket.send(bytes(buffered))
                await websocket.send(
                    json.dumps(
                        {
                            "header": {
                                "action": "finish-task",
                                "task_id": task_id,
                                "streaming": "duplex",
                            },
                            "payload": {"input": {}},
                        }
                    )
                )
                return

            buffered.extend(chunk)
            while len(buffered) >= _AUDIO_BATCH_BYTES:
                await websocket.send(bytes(buffered[:_AUDIO_BATCH_BYTES]))
                del buffered[:_AUDIO_BATCH_BYTES]

    async def _receive_transcripts(
        self,
        output: asyncio.Queue[Transcript],
        task_id: str,
        state: _RecognitionState,
    ) -> None:
        websocket = self._require_websocket()
        last_result: tuple[object, str, bool] | None = None

        while True:
            message = await self._receive_event(websocket)
            header = self._header(message)
            if header.get("task_id") != task_id:
                continue
            self._raise_for_failure(message)

            event = header.get("event")
            if event == "task-finished":
                return
            if event != "result-generated":
                continue

            duration = self._usage_duration(message)
            if duration is not None:
                previous = state.billable_duration or 0
                state.billable_duration = max(previous, duration)

            sentence = self._sentence(message)
            if sentence.get("heartbeat") is True:
                continue
            text = sentence.get("text")
            if not isinstance(text, str) or not text:
                continue
            is_final = sentence.get("sentence_end") is True
            transcript = Transcript(text=text, is_final=is_final)
            result_key = (sentence.get("sentence_id"), text, is_final)
            if result_key != last_result:
                await output.put(transcript)
                last_result = result_key
                if is_final:
                    state.output_characters += len(text)

    async def _disconnect(self) -> None:
        websocket = self._websocket
        self._websocket = None
        if websocket is not None:
            with suppress(ConnectionClosed, OSError, TimeoutError):
                await websocket.close()

    async def _drop_connection(self) -> None:
        await self._disconnect()

    @staticmethod
    async def _receive_event(websocket: Any) -> dict[str, Any]:
        try:
            raw_message = await websocket.recv()
            if isinstance(raw_message, bytes):
                raw_message = raw_message.decode("utf-8")
            message = json.loads(raw_message)
            if not isinstance(message, dict):
                raise TypeError("response must be a JSON object")
            return message
        except asyncio.CancelledError:
            raise
        except (ConnectionClosed, OSError, TimeoutError):
            raise
        except Exception as error:
            raise ASRError(f"Invalid Qwen Audio ASR response: {error}") from error

    @staticmethod
    def _header(message: dict[str, Any]) -> dict[str, Any]:
        header = message.get("header")
        return header if isinstance(header, dict) else {}

    @staticmethod
    def _payload(message: dict[str, Any]) -> dict[str, Any]:
        payload = message.get("payload")
        return payload if isinstance(payload, dict) else {}

    @classmethod
    def _sentence(cls, message: dict[str, Any]) -> dict[str, Any]:
        output = cls._payload(message).get("output")
        if not isinstance(output, dict):
            return {}
        sentence = output.get("sentence")
        return sentence if isinstance(sentence, dict) else {}

    @classmethod
    def _usage_duration(cls, message: dict[str, Any]) -> int | float | None:
        usage = cls._payload(message).get("usage")
        if not isinstance(usage, dict):
            return None
        duration = usage.get("duration")
        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or duration < 0
        ):
            return None
        return duration

    @classmethod
    def _raise_for_failure(cls, message: dict[str, Any]) -> None:
        header = cls._header(message)
        if header.get("event") != "task-failed":
            return
        detail = header.get("error_message") or "unknown error"
        code = header.get("error_code")
        raise ASRError(f"Qwen Audio ASR task failed: code={code}, detail={detail}")

    @staticmethod
    async def _stop_task(task: asyncio.Task[Any] | None) -> None:
        if task is None:
            return
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    def _require_websocket(self) -> Any:
        if self._websocket is None:
            raise ASRStateError("Qwen Audio ASR connection is unavailable")
        return self._websocket

    def _release_stream(self, stream: _QwenAudioStream) -> None:
        if self._stream is stream:
            self._stream = None

    def _ensure_started(self) -> None:
        if self._closed:
            raise ASRStateError("QwenAudioASR has been closed")
        if not self._started:
            raise ASRStateError("QwenAudioASR has not been started")
