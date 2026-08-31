"""Replaceable token-estimation plugins used by context budget policies."""

from __future__ import annotations

import json
import math
import unicodedata
from collections.abc import Callable
from typing import Any, Protocol
from sagents.v2.model.contracts import ModelMessage


class TokenEstimator(Protocol):
    """Synchronous, side-effect-free estimator used on every projection pass."""

    def estimate(self, messages: tuple[ModelMessage, ...]) -> int: ...


class JsonHeuristicTokenEstimator:
    """Conservative provider-neutral estimate of the complete wire structure."""

    estimator_id = "json-heuristic"

    def __init__(self, *, bytes_per_token: float = 4.0, message_overhead: int = 6):
        if bytes_per_token <= 0:
            raise ValueError("bytes_per_token must be positive")
        if message_overhead < 0:
            raise ValueError("message_overhead cannot be negative")
        self.bytes_per_token = bytes_per_token
        self.message_overhead = message_overhead

    def estimate(self, messages: tuple[ModelMessage, ...]) -> int:
        total = 0
        for message in messages:
            encoded = json.dumps(
                message.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            total += self.message_overhead + math.ceil(
                len(encoded) / self.bytes_per_token
            )
        return total


class UnicodeHeuristicTokenEstimator:
    """Text-oriented estimate that treats CJK and symbol-heavy text conservatively.

    This plugin is useful when JSON byte length overestimates ASCII-heavy prompts
    but a model-specific tokenizer cannot be installed.  Tool schemas and message
    metadata are still included through their deterministic JSON representation.
    """

    estimator_id = "unicode-heuristic"

    def __init__(
        self,
        *,
        ascii_chars_per_token: float = 4.0,
        non_ascii_chars_per_token: float = 1.5,
        message_overhead: int = 6,
    ) -> None:
        if ascii_chars_per_token <= 0 or non_ascii_chars_per_token <= 0:
            raise ValueError("characters-per-token values must be positive")
        self.ascii_chars_per_token = ascii_chars_per_token
        self.non_ascii_chars_per_token = non_ascii_chars_per_token
        self.message_overhead = message_overhead

    def estimate(self, messages: tuple[ModelMessage, ...]) -> int:
        total = 0
        for message in messages:
            value = json.dumps(
                message.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            ascii_count = 0
            non_ascii_weight = 0.0
            for character in value:
                if character.isascii():
                    ascii_count += 1
                    continue
                category = unicodedata.category(character)
                non_ascii_weight += 1.25 if category.startswith("S") else 1.0
            total += self.message_overhead
            total += math.ceil(ascii_count / self.ascii_chars_per_token)
            total += math.ceil(non_ascii_weight / self.non_ascii_chars_per_token)
        return total


class TiktokenTokenEstimator:
    """Optional OpenAI tokenizer plugin with lazy dependency loading."""

    estimator_id = "tiktoken"

    def __init__(
        self,
        *,
        model: str | None = None,
        encoding_name: str = "cl100k_base",
        encoder: Any | None = None,
        tokens_per_message: int = 6,
    ) -> None:
        if encoder is None:
            try:
                import tiktoken
            except ImportError as exc:
                raise RuntimeError(
                    "tiktoken estimator requires the optional 'tiktoken' package"
                ) from exc
            if model is not None:
                try:
                    encoder = tiktoken.encoding_for_model(model)
                except KeyError:
                    encoder = tiktoken.get_encoding(encoding_name)
            else:
                encoder = tiktoken.get_encoding(encoding_name)
        self.encoder = encoder
        self.tokens_per_message = tokens_per_message

    def estimate(self, messages: tuple[ModelMessage, ...]) -> int:
        return sum(
            self.tokens_per_message
            + len(
                self.encoder.encode(
                    json.dumps(
                        message.model_dump(mode="json"),
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    )
                )
            )
            for message in messages
        )


class CallableTokenEstimator:
    """Adapter for application-owned tokenizers without a Sage dependency."""

    def __init__(
        self,
        estimator_id: str,
        callback: Callable[[tuple[ModelMessage, ...]], int],
    ) -> None:
        self.estimator_id = estimator_id
        self.callback = callback

    def estimate(self, messages: tuple[ModelMessage, ...]) -> int:
        value = int(self.callback(messages))
        if value < 0:
            raise ValueError("token estimator cannot return a negative value")
        return value
