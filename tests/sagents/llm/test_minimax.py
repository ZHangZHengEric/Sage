from types import SimpleNamespace

from sagents.llm.minimax import MiniMaxStreamNormalizer


def _chunk(*, content=None, reasoning_details=None, reasoning_content=None):
    delta = SimpleNamespace(
        content=content,
        reasoning_details=reasoning_details,
        reasoning_content=reasoning_content,
    )
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def test_minimax_stream_normalizer_converts_cumulative_snapshots_to_deltas() -> None:
    normalizer = MiniMaxStreamNormalizer()

    first_reasoning = normalizer.normalize(
        _chunk(reasoning_details=[{"type": "reasoning.text", "text": "先分析"}])
    )
    second_reasoning = normalizer.normalize(
        _chunk(reasoning_details=[{"type": "reasoning.text", "text": "先分析，再回答"}])
    )
    first_content = normalizer.normalize(_chunk(content="答"))
    second_content = normalizer.normalize(_chunk(content="答案"))

    assert first_reasoning.choices[0].delta.reasoning_content == "先分析"
    assert second_reasoning.choices[0].delta.reasoning_content == "，再回答"
    assert first_content.choices[0].delta.content == "答"
    assert second_content.choices[0].delta.content == "案"


def test_minimax_stream_normalizer_accepts_already_incremental_gateway_chunks() -> None:
    normalizer = MiniMaxStreamNormalizer()

    first = normalizer.normalize(_chunk(content="Hello"))
    second = normalizer.normalize(_chunk(content=" world"))

    assert first.choices[0].delta.content == "Hello"
    assert second.choices[0].delta.content == " world"
