"""Local Smart Turn v3.2 inference using ONNX Runtime."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

import numpy as np

from ..audio import AudioChunk, AudioFormat
from ._whisper_features import compute_whisper_log_mel_features
from .errors import (
    TurnDetectionError,
    TurnDetectionFormatError,
    TurnDetectionStateError,
)
from .types import TurnAnalysis

_INPUT_FORMAT = AudioFormat(16_000)
_MAX_SAMPLES = _INPUT_FORMAT.sample_rate * 8


class SmartTurnV3:
    """Classify semantic turn completion with the Smart Turn v3.2 ONNX model."""

    def __init__(self, *, model_path: str | Path | None = None) -> None:
        """Store model configuration without loading ONNX Runtime resources."""

        self._model_path = Path(model_path) if model_path is not None else None
        self._executor: ThreadPoolExecutor | None = None
        self._session: Any | None = None
        self._started = False
        self._closed = False

    async def start(self, input_format: AudioFormat) -> None:
        """Load the model on one dedicated inference thread."""

        if self._closed:
            raise TurnDetectionStateError("SmartTurnV3 has already been closed")
        if self._started:
            if input_format != _INPUT_FORMAT:
                raise TurnDetectionStateError(
                    f"SmartTurnV3 is already running with {_INPUT_FORMAT!r}"
                )
            return
        self._validate_format(input_format)

        executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="lalk-smart-turn",
        )
        try:
            session = await asyncio.get_running_loop().run_in_executor(
                executor,
                self._load_session,
            )
        except asyncio.CancelledError:
            await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)
            raise
        except Exception as error:
            await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)
            raise TurnDetectionError(
                f"Unable to load Smart Turn v3.2 model: {error}"
            ) from error

        self._executor = executor
        self._session = session
        self._started = True

    async def analyze(self, audio: AudioChunk) -> TurnAnalysis:
        """Analyze the last eight seconds of one complete user-turn snapshot."""

        self._ensure_started()
        if audio.format != _INPUT_FORMAT:
            raise TurnDetectionFormatError(
                f"SmartTurnV3 requires {_INPUT_FORMAT!r}, received {audio.format!r}"
            )

        executor = self._require_executor()
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                executor,
                self._predict,
                audio.data,
            )
            return result
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise TurnDetectionError(
                f"Unable to analyze audio with SmartTurnV3: {error}"
            ) from error

    async def close(self) -> None:
        """Release the model and its inference worker."""

        if self._closed:
            return
        self._closed = True
        self._started = False
        self._session = None
        executor = self._executor
        self._executor = None
        if executor is not None:
            await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)

    def _load_session(self) -> Any:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        if self._model_path is not None:
            return ort.InferenceSession(str(self._model_path), sess_options=options)

        resource = files(f"{__package__}.data").joinpath("smart-turn-v3.2-cpu.onnx")
        with as_file(resource) as model_path:
            return ort.InferenceSession(str(model_path), sess_options=options)

    def _predict(self, data: bytes) -> TurnAnalysis:
        session = self._require_session()
        samples = np.frombuffer(data, dtype="<i2").astype(np.float32)
        samples *= 1.0 / 32_768.0
        if samples.size > _MAX_SAMPLES:
            samples = samples[-_MAX_SAMPLES:]
        elif samples.size < _MAX_SAMPLES:
            samples = np.pad(samples, (_MAX_SAMPLES - samples.size, 0))

        features = compute_whisper_log_mel_features(samples)
        outputs = session.run(None, {"input_features": features[None, ...]})
        probability = float(outputs[0][0].item())
        return TurnAnalysis(complete=probability > 0.5, probability=probability)

    @staticmethod
    def _validate_format(input_format: AudioFormat) -> None:
        if input_format != _INPUT_FORMAT:
            raise TurnDetectionFormatError(
                f"SmartTurnV3 requires {_INPUT_FORMAT!r}, received {input_format!r}"
            )

    def _ensure_started(self) -> None:
        if self._closed:
            raise TurnDetectionStateError("SmartTurnV3 has been closed")
        if not self._started:
            raise TurnDetectionStateError("SmartTurnV3 has not been started")

    def _require_executor(self) -> ThreadPoolExecutor:
        if self._executor is None:
            raise TurnDetectionStateError("SmartTurnV3 inference worker is unavailable")
        return self._executor

    def _require_session(self) -> Any:
        if self._session is None:
            raise TurnDetectionStateError("SmartTurnV3 model is unavailable")
        return self._session
