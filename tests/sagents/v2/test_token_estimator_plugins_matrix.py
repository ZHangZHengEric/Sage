from __future__ import annotations

from types import SimpleNamespace

import pytest

from sagents.v2.context import (
    CallableTokenEstimator,
    JsonHeuristicTokenEstimator,
    TiktokenTokenEstimator,
    TokenEstimatorDescriptor,
    TokenEstimatorRegistry,
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


def test_registry_exposes_availability_and_creates_selected_builtin():
    registry = TokenEstimatorRegistry()
    descriptors = {value.estimator_id: value for value in registry.descriptors()}

    assert set(descriptors) == {
        "json-heuristic",
        "tiktoken",
        "unicode-heuristic",
    }
    assert descriptors["json-heuristic"].available is True
    estimator = registry.create(
        "json-heuristic", {"bytes_per_token": 3.5, "message_overhead": 4}
    )
    assert isinstance(estimator, JsonHeuristicTokenEstimator)


def test_registry_accepts_application_owned_plugin_factory():
    registry = TokenEstimatorRegistry(include_builtins=False)
    registry.register(
        TokenEstimatorDescriptor(
            estimator_id="tenant-tokenizer",
            name="Tenant tokenizer",
            value="Counts tokens through the tenant-owned tokenizer.",
        ),
        lambda config: CallableTokenEstimator(
            "tenant-tokenizer", lambda messages: config["tokens"]
        ),
    )

    assert registry.create("tenant-tokenizer", {"tokens": 17}).estimate(MESSAGES) == 17


def test_registry_rejects_duplicate_and_unknown_plugins():
    registry = TokenEstimatorRegistry()
    descriptor = TokenEstimatorDescriptor(
        estimator_id="json-heuristic", name="duplicate", value="duplicate"
    )
    with pytest.raises(ValueError, match="already registered"):
        registry.register(descriptor, lambda config: JsonHeuristicTokenEstimator())
    with pytest.raises(ValueError, match="unknown token estimator"):
        registry.create("missing")
