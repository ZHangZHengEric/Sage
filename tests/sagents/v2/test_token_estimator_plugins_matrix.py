from __future__ import annotations

from types import SimpleNamespace

import pytest

from sagents.v2.context import (
    CallableTokenEstimator,
    JsonHeuristicTokenEstimator,
    TiktokenTokenEstimator,
    UnicodeHeuristicTokenEstimator,
)
from sagents.v2.model import ModelMessage
from sagents.v2.contracts.items import TextBlock


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
