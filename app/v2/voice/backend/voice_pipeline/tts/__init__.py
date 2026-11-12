"""Text-to-speech interfaces and implementations."""

from .errors import TTSError, TTSStateError
from .protocols import TTS, TextInput, TTSOutput, TTSStream
from .qwen_audio import QwenAudioTTS
from .text import StreamingTextProcessor, TextSegmenter
from .types import TTSResult, TTSTextMark
from .volcengine import VolcengineTTS

__all__ = [
    "QwenAudioTTS",
    "TTS",
    "TTSError",
    "TTSOutput",
    "TTSResult",
    "TTSStateError",
    "TTSStream",
    "TTSTextMark",
    "StreamingTextProcessor",
    "TextInput",
    "TextSegmenter",
    "VolcengineTTS",
]
