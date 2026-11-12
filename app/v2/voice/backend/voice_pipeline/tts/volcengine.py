"""Volcengine bidirectional streaming text-to-speech."""

import asyncio
import json
import logging
import ssl
import uuid
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Self

import certifi
import websockets
from websockets.exceptions import ConnectionClosed

from ..audio import AudioChunk, AudioFormat
from ._vendor.volcengine import (
    EventType,
    Message,
    MsgType,
    cancel_session,
    finish_connection,
    finish_session,
    receive_message,
    start_connection,
    start_session,
    task_request,
)
from .errors import TTSError, TTSStateError
from .protocols import TextInput, TTSOutput, TTSStream
from .types import TTSResult, TTSTextMark

_URL = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
_MAX_MESSAGE_SIZE = 10 * 1024 * 1024
_RESPONSE_TIMEOUT = 30.0
_CANCEL_TIMEOUT = 1.0
_SUPPORTED_SAMPLE_RATES = frozenset(
    {8_000, 16_000, 22_050, 24_000, 32_000, 44_100, 48_000}
)

logging.getLogger(receive_message.__module__).setLevel(logging.WARNING)


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


@dataclass(frozen=True, slots=True)
class _SubtitleWord:
    text: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True, slots=True)
class _Subtitle:
    text: str
    words: tuple[_SubtitleWord, ...]


class _SynthesisStream(AsyncIterator[TTSOutput]):
    """Deliver one provider-owned synthesis task to an audio consumer."""

    def __init__(self, tts: "VolcengineTTS", text: TextInput) -> None:
        loop = asyncio.get_running_loop()
        self._tts = tts
        self._output: asyncio.Queue[TTSOutput] = asyncio.Queue(maxsize=1)
        self._state = _SynthesisState()
        self._task = loop.create_task(
            tts._run_synthesis(text, self._output, self._state),
            name="volcengine-tts-session",
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

        receive = asyncio.create_task(self._output.get(), name="volcengine-tts-output")
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


class VolcengineTTS:
    """Stream PCM audio and word-aligned playback marks from Volcengine TTS."""

    def __init__(
        self,
        *,
        api_key: str,
        voice: str = "zh_female_vv_uranus_bigtts",
        resource_id: str = "seed-tts-2.0",
        sample_rate: int = 48_000,
    ) -> None:
        """Store provider settings without opening a connection."""

        if not api_key.strip():
            raise ValueError("api_key must not be empty")
        if not voice.strip():
            raise ValueError("voice must not be empty")
        if not resource_id.strip():
            raise ValueError("resource_id must not be empty")
        if sample_rate not in _SUPPORTED_SAMPLE_RATES:
            supported = ", ".join(str(rate) for rate in sorted(_SUPPORTED_SAMPLE_RATES))
            raise ValueError(f"sample_rate must be one of: {supported}")

        self._api_key = api_key
        self._voice = voice
        self._resource_id = resource_id
        self._output_format = AudioFormat(sample_rate=sample_rate, channels=1)

        self._control_lock = asyncio.Lock()
        self._websocket: Any | None = None
        self._stream: _SynthesisStream | None = None
        self._started = False
        self._closed = False

    @property
    def output_format(self) -> AudioFormat:
        """Format of audio yielded by :meth:`synthesize`."""

        return self._output_format

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()

    async def start(self) -> None:
        """Open and initialize the persistent provider connection."""

        async with self._control_lock:
            if self._closed:
                raise TTSStateError("VolcengineTTS has already been closed")
            if self._started:
                return
            await self._connect()
            self._started = True

    def synthesize(self, text: TextInput) -> TTSStream:
        """Send text chunks and stream synthesis output from one provider session."""

        self._ensure_started()
        if self._stream is not None:
            raise TTSStateError("VolcengineTTS supports one active synthesis at a time")

        stream = _SynthesisStream(self, text)
        self._stream = stream
        return stream

    async def _run_synthesis(
        self,
        text: TextInput,
        output: asyncio.Queue[TTSOutput],
        state: _SynthesisState,
    ) -> None:
        session_id: str | None = None
        sender: asyncio.Task[None] | None = None
        receiver: asyncio.Task[Message] | None = None
        audio = bytearray()
        sentence_audio_start_frame = 0
        sentence_start_seen = False
        subtitle_seen = False
        sentence_fallbacks: list[TTSTextMark] = []
        seen_marks: set[TTSTextMark] = set()

        try:
            session_id = await self._open_session()
            sender = asyncio.create_task(
                self._send_text(text, session_id, state),
                name="volcengine-tts-text",
            )
            receiver = self._create_receive_task()

            while True:
                waiters: set[asyncio.Task[Any]] = {receiver}
                if not sender.done():
                    waiters.add(sender)
                done, _ = await asyncio.wait(
                    waiters, return_when=asyncio.FIRST_COMPLETED
                )

                if sender in done:
                    await sender
                if receiver not in done:
                    continue

                message = receiver.result()
                receiver = None
                if message.session_id and message.session_id != session_id:
                    receiver = self._create_receive_task()
                    continue
                self._raise_for_error(message)

                if message.type == MsgType.AudioOnlyServer:
                    if message.payload:
                        state.audio_bytes += len(message.payload)
                        audio.extend(message.payload)
                        aligned_length = len(audio) & ~1
                        if aligned_length:
                            chunk = bytes(audio[:aligned_length])
                            del audio[:aligned_length]
                            await output.put(AudioChunk(chunk, self._output_format))
                elif message.event == EventType.TTSSentenceStart:
                    sentence_audio_start_frame = (
                        state.audio_bytes // self._output_format.frame_bytes
                    )
                    sentence_start_seen = True
                elif message.event == EventType.TTSSentenceEnd:
                    sentence_text = self._parse_event_text(message.payload)
                    if sentence_text:
                        sentence_fallbacks.append(
                            TTSTextMark(
                                text=sentence_text,
                                at_frame=(
                                    state.audio_bytes // self._output_format.frame_bytes
                                ),
                            )
                        )
                elif message.event == EventType.TTSSubtitle:
                    subtitle = self._parse_subtitle(message.payload)
                    if subtitle is not None:
                        subtitle_seen = True
                        audio_start_frame = self._subtitle_audio_start_frame(
                            subtitle,
                            sentence_audio_start_frame=sentence_audio_start_frame,
                            sentence_start_seen=sentence_start_seen,
                            received_frames=(
                                state.audio_bytes // self._output_format.frame_bytes
                            ),
                        )
                        for mark in self._subtitle_marks(
                            subtitle,
                            audio_start_frame=audio_start_frame,
                        ):
                            if mark in seen_marks:
                                continue
                            seen_marks.add(mark)
                            await output.put(mark)
                elif message.event == EventType.SessionFinished:
                    if not subtitle_seen:
                        for fallback in sentence_fallbacks:
                            await output.put(fallback)
                    await sender
                    state.provider_usage = self._parse_usage(message.payload)
                    state.completed = True
                    if audio:
                        audio.append(0)
                        await output.put(AudioChunk(bytes(audio), self._output_format))
                    return
                elif message.event == EventType.SessionCanceled:
                    raise TTSError("Volcengine TTS session was canceled unexpectedly")

                receiver = self._create_receive_task()
        except asyncio.CancelledError:
            raise
        except TTSError:
            raise
        except Exception as error:
            raise TTSError(f"Volcengine TTS synthesis failed: {error}") from error
        finally:
            await self._stop_task(receiver)
            await self._stop_task(sender)
            if session_id is not None and not state.completed:
                await self._cancel_session(session_id)

    async def close(self) -> None:
        """Cancel active synthesis and close the provider connection."""

        async with self._control_lock:
            if self._closed:
                return
            self._closed = True
            self._started = False

            stream = self._stream
            if stream is not None:
                await stream.aclose()

            await self._disconnect()

    async def _connect(self) -> None:
        websocket: Any | None = None
        try:
            websocket = await websockets.connect(
                _URL,
                ssl=ssl.create_default_context(cafile=certifi.where()),
                additional_headers={
                    "X-Api-Key": self._api_key,
                    "X-Api-Resource-Id": self._resource_id,
                    "X-Api-Connect-Id": str(uuid.uuid4()),
                    "X-Control-Require-Usage-Tokens-Return": "*",
                },
                max_size=_MAX_MESSAGE_SIZE,
                open_timeout=15,
                close_timeout=5,
            )
            await start_connection(websocket)
            await self._expect(
                websocket,
                EventType.ConnectionStarted,
                timeout_seconds=15,
            )
        except asyncio.CancelledError:
            if websocket is not None:
                await websocket.close()
            raise
        except Exception as error:
            if websocket is not None:
                await websocket.close()
            raise TTSError(f"Unable to connect to Volcengine TTS: {error}") from error

        self._websocket = websocket

    async def _open_session(self) -> str:
        try:
            for attempt in range(2):
                if self._websocket is None:
                    await self._connect()
                websocket = self._require_websocket()
                session_id = str(uuid.uuid4())
                payload = self._payload(EventType.StartSession)
                try:
                    await start_session(websocket, payload, session_id)
                    message = await self._expect(
                        websocket,
                        EventType.SessionStarted,
                        timeout_seconds=15,
                    )
                    if message.session_id and message.session_id != session_id:
                        raise TTSError("Volcengine TTS started an unexpected session")
                    return session_id
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

        raise TTSError("Unable to start Volcengine TTS session")

    async def _send_text(
        self,
        text: TextInput,
        session_id: str,
        state: _SynthesisState,
    ) -> None:
        websocket = self._require_websocket()
        async for part in self._text_parts(text):
            if not part.strip():
                continue
            payload = json.dumps(
                {
                    "event": EventType.TaskRequest,
                    "req_params": {
                        **self._request_params(),
                        "text": part,
                    },
                },
                ensure_ascii=False,
            ).encode()
            await task_request(websocket, payload, session_id)
            state.input_characters += len(part)
        await finish_session(websocket, session_id)

    async def _cancel_session(self, session_id: str) -> None:
        websocket = self._websocket
        if websocket is None:
            return

        try:
            await cancel_session(websocket, session_id)
            async with asyncio.timeout(_CANCEL_TIMEOUT):
                while True:
                    message = await self._receive(websocket)
                    if message.session_id and message.session_id != session_id:
                        continue
                    if message.event == EventType.SessionCanceled:
                        return
                    self._raise_for_error(message)
        except (ConnectionClosed, OSError, TimeoutError, TTSError):
            await self._drop_connection()

    async def _disconnect(self) -> None:
        websocket = self._websocket
        self._websocket = None
        if websocket is None:
            return

        with suppress(ConnectionClosed, OSError, TimeoutError, TTSError):
            await finish_connection(websocket)
            await self._expect(
                websocket,
                EventType.ConnectionFinished,
                timeout_seconds=2,
            )
        with suppress(ConnectionClosed, OSError, TimeoutError):
            await websocket.close()

    async def _drop_connection(self) -> None:
        websocket = self._websocket
        self._websocket = None
        if websocket is not None:
            with suppress(Exception):
                await websocket.close()

    async def _expect(
        self,
        websocket: Any,
        event: EventType,
        *,
        timeout_seconds: float,
    ) -> Message:
        message = await self._receive(
            websocket,
            timeout_seconds=timeout_seconds,
        )
        self._raise_for_error(message)
        if message.type != MsgType.FullServerResponse or message.event != event:
            raise TTSError(
                "Unexpected Volcengine TTS response: "
                f"{message.type.name}/{message.event!s}; "
                f"expected FullServerResponse/{event.name}"
            )
        return message

    @staticmethod
    def _raise_for_error(message: Message) -> None:
        if message.type != MsgType.Error and message.event not in {
            EventType.ConnectionFailed,
            EventType.SessionFailed,
        }:
            return
        detail = message.payload.decode("utf-8", "replace")
        raise TTSError(
            f"Volcengine TTS request failed: event={message.event}, "
            f"code={message.error_code}, detail={detail}"
        )

    @staticmethod
    def _parse_usage(payload: bytes) -> dict[str, int | float] | None:
        if not payload:
            return None
        try:
            response = json.loads(payload)
            if not isinstance(response, dict):
                return None
            usage = response.get("usage")
            if not isinstance(usage, dict):
                return None
            text_words = usage.get("text_words")
            if text_words is None or isinstance(text_words, bool):
                return None
            return {"text_words": int(text_words)}
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    def _create_receive_task(self) -> asyncio.Task[Message]:
        websocket = self._require_websocket()
        return asyncio.create_task(
            self._receive(websocket, timeout_seconds=_RESPONSE_TIMEOUT),
            name="volcengine-tts-audio",
        )

    @staticmethod
    async def _receive(
        websocket: Any,
        *,
        timeout_seconds: float | None = None,
    ) -> Message:
        try:
            if timeout_seconds is None:
                return await receive_message(websocket)
            async with asyncio.timeout(timeout_seconds):
                return await receive_message(websocket)
        except asyncio.CancelledError:
            raise
        except (ConnectionClosed, OSError, TimeoutError, TTSError):
            raise
        except Exception as error:
            raise TTSError(f"Invalid Volcengine TTS response: {error}") from error

    @staticmethod
    async def _stop_task(task: asyncio.Task[Any] | None) -> None:
        if task is None:
            return
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    def _payload(self, event: EventType) -> bytes:
        return json.dumps(
            {
                "event": event,
                "req_params": self._request_params(),
            },
            ensure_ascii=False,
        ).encode()

    def _request_params(self) -> dict[str, Any]:
        return {
            "speaker": self._voice,
            "audio_params": {
                "format": "pcm",
                "sample_rate": self._output_format.sample_rate,
                "enable_subtitle": True,
            },
        }

    @staticmethod
    def _parse_event_text(payload: bytes) -> str:
        try:
            value = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            return ""
        if not isinstance(value, dict):
            return ""
        text = value.get("text")
        return text if isinstance(text, str) else ""

    @staticmethod
    def _parse_subtitle(payload: bytes) -> _Subtitle | None:
        try:
            value = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            return None
        if not isinstance(value, dict):
            return None

        text = value.get("text")
        raw_words = value.get("words")
        if not isinstance(text, str) or not text or not isinstance(raw_words, list):
            return None

        words: list[_SubtitleWord] = []
        for raw_word in raw_words:
            if not isinstance(raw_word, dict):
                return None
            word = raw_word.get("word")
            start = raw_word.get("startTime")
            end = raw_word.get("endTime")
            if (
                not isinstance(word, str)
                or not word
                or not isinstance(start, (int, float))
                or isinstance(start, bool)
                or not isinstance(end, (int, float))
                or isinstance(end, bool)
                or start < 0
                or end < start
            ):
                return None
            words.append(_SubtitleWord(word, float(start), float(end)))

        return _Subtitle(text, tuple(words))

    def _subtitle_marks(
        self,
        subtitle: _Subtitle,
        *,
        audio_start_frame: int = 0,
    ) -> list[TTSTextMark]:
        if not subtitle.words:
            return []

        marks: list[TTSTextMark] = []
        cursor = 0
        for word in subtitle.words:
            index = subtitle.text.find(word.text, cursor)
            if index < 0:
                return []
            prefix = subtitle.text[cursor:index]
            duration = max(word.end_seconds - word.start_seconds, 0.0)
            for character_index, character in enumerate(word.text):
                marks.append(
                    TTSTextMark(
                        text=(prefix if character_index == 0 else "") + character,
                        at_frame=(
                            audio_start_frame
                            + round(
                                (
                                    word.start_seconds
                                    + duration * character_index / len(word.text)
                                )
                                * self._output_format.sample_rate
                            )
                        ),
                    )
                )
            cursor = index + len(word.text)

        remaining = subtitle.text[cursor:]
        if remaining:
            marks.append(
                TTSTextMark(
                    text=remaining,
                    at_frame=(
                        audio_start_frame
                        + round(
                            subtitle.words[-1].end_seconds
                            * self._output_format.sample_rate
                        )
                    ),
                )
            )
        return marks

    def _subtitle_audio_start_frame(
        self,
        subtitle: _Subtitle,
        *,
        sentence_audio_start_frame: int,
        sentence_start_seen: bool,
        received_frames: int,
    ) -> int:
        if sentence_start_seen:
            return sentence_audio_start_frame

        duration_frames = round(
            subtitle.words[-1].end_seconds * self._output_format.sample_rate
        )
        if sentence_audio_start_frame + duration_frames > received_frames:
            return max(received_frames - duration_frames, 0)
        return sentence_audio_start_frame

    @staticmethod
    async def _text_parts(text: TextInput) -> AsyncIterator[str]:
        if isinstance(text, str):
            yield text
            return
        if not isinstance(text, AsyncIterable):
            raise TypeError(
                "text must be a string or an asynchronous iterable of strings"
            )
        async for part in text:
            if not isinstance(part, str):
                raise TypeError("text stream items must be strings")
            yield part

    def _require_websocket(self) -> Any:
        if self._websocket is None:
            raise TTSStateError("Volcengine TTS connection is unavailable")
        return self._websocket

    def _release_stream(self, stream: _SynthesisStream) -> None:
        if self._stream is stream:
            self._stream = None

    def _ensure_started(self) -> None:
        if self._closed:
            raise TTSStateError("VolcengineTTS has been closed")
        if not self._started:
            raise TTSStateError("VolcengineTTS has not been started")
