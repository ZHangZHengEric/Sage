"""Official token-estimator plugin: optional OpenAI tiktoken encoding."""

from __future__ import annotations

from typing import Any

from sagents.v2.context.estimation import CachedMessageEstimator


class TiktokenTokenEstimator(CachedMessageEstimator):
    """Optional OpenAI tokenizer plugin with lazy dependency loading."""

    plugin_id = "sage.context.token-estimator.tiktoken"
    name = "Tiktoken token estimator"
    description = "Uses tiktoken encodings when the optional package is installed."
    estimator_id = "tiktoken"

    def __init__(
        self,
        *,
        model: str | None = None,
        encoding_name: str = "cl100k_base",
        encoder: Any | None = None,
        tokens_per_message: int = 6,
    ) -> None:
        if tokens_per_message < 0:
            raise ValueError("tokens_per_message cannot be negative")
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
        self._init_cache()

    def _cache_identity(self):
        return (id(self.encoder), self.tokens_per_message)

    def _text_tokens(self, value):
        return self.tokens_per_message + len(self.encoder.encode(value))
