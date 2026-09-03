from __future__ import annotations

from types import SimpleNamespace

import pytest

from sagents.v2.context import (
    CallableTokenEstimator,
    JsonHeuristicTokenEstimator,
    TiktokenTokenEstimator,
    UnicodeHeuristicTokenEstimator,
)
from sagents.v2.contracts.items import ImageBlock, TextBlock
from sagents.v2.model import ModelMessage


MESSAGES = (
    ModelMessage(role="system", content=(TextBlock(text="Be exact."),)),
    ModelMessage(role="user", content=(TextBlock(text="解释一下 Sage v2"),)),
)


@pytest.mark.parametrize(
    "estimator",
    [
        JsonHeuristicTokenEstimator(),
        UnicodeHeuristicTokenEstimator(),
        CallableTokenEstimator("fixed-test", lambda messages: len(messages) * 11),
    ],
)
def test_builtin_and_custom_estimators_return_non_negative_counts(estimator):
    assert estimator.estimate(MESSAGES) > 0


def test_tiktoken_adapter_can_use_an_injected_encoder_without_optional_dependency():
    encoder = SimpleNamespace(encode=lambda value: value.split())
    estimator = TiktokenTokenEstimator(encoder=encoder, tokens_per_message=2)

    assert estimator.estimate(MESSAGES) >= 4


@pytest.mark.parametrize(
    "estimator",
    [
        JsonHeuristicTokenEstimator(),
        UnicodeHeuristicTokenEstimator(),
        TiktokenTokenEstimator(
            encoder=SimpleNamespace(encode=lambda value: list(value)),
            tokens_per_message=2,
        ),
    ],
)
def test_data_uri_image_bytes_are_not_counted_as_prompt_text(estimator):
    def estimate(payload_size: int) -> int:
        return estimator.estimate(
            (
                ModelMessage(
                    role="user",
                    content=(
                        TextBlock(text="Describe this image."),
                        ImageBlock(
                            uri="data:image/png;base64," + ("A" * payload_size),
                            mime_type="image/png",
                        ),
                    ),
                ),
            )
        )

    assert estimate(32) == estimate(2_000_000)
    assert 4_096 <= estimate(2_000_000) < 10_000


def test_low_detail_image_uses_a_smaller_bounded_token_reserve():
    estimator = JsonHeuristicTokenEstimator()
    image_uri = "data:image/png;base64," + ("A" * 2_000_000)
    automatic = estimator.estimate(
        (
            ModelMessage(
                role="user",
                content=(ImageBlock(uri=image_uri, mime_type="image/png"),),
            ),
        )
    )
    low = estimator.estimate(
        (
            ModelMessage(
                role="user",
                content=(
                    ImageBlock(
                        uri=image_uri,
                        mime_type="image/png",
                        detail="low",
                    ),
                ),
            ),
        )
    )

    assert automatic - low == 4_096 - 256


def test_large_text_remains_subject_to_normal_token_estimation():
    estimator = JsonHeuristicTokenEstimator()
    estimate = estimator.estimate(
        (
            ModelMessage(
                role="user",
                content=(TextBlock(text="A" * 2_000_000),),
            ),
        )
    )

    assert estimate > 400_000
