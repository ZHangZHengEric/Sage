import json
import time
from types import SimpleNamespace

import pytest

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.utils.repeat_pattern import build_loop_signature, detect_repeat_pattern


def _assistant_text(content: str, message_id: str | None = None) -> MessageChunk:
    return MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content=content,
        message_id=message_id,
        message_type=MessageType.DO_SUBTASK_RESULT.value,
    )


def _assistant_tool_call(name: str, arguments: str) -> MessageChunk:
    return MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="",
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": arguments,
                },
            }
        ],
        message_type=MessageType.TOOL_CALL.value,
    )


def _assistant_tool_calls(tool_calls) -> MessageChunk:
    return MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="",
        tool_calls=tool_calls,
        message_type=MessageType.TOOL_CALL.value,
    )


def _assistant_tool_call_delta(
    *,
    call_id: str = "",
    index: int = 0,
    name: str = "",
    arguments: str = "",
) -> MessageChunk:
    return MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="",
        tool_calls=[
            SimpleNamespace(
                id=call_id,
                index=index,
                type="function",
                function=SimpleNamespace(name=name, arguments=arguments),
            )
        ],
        message_type=MessageType.TOOL_CALL.value,
    )


def _dict_tool_call(
    *,
    call_id: str = "call_1",
    name: str,
    arguments,
    index=None,
) -> dict:
    tool_call = {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments,
        },
    }
    if index is not None:
        tool_call["index"] = index
    return tool_call


def _tool_result(content: str, tool_name: str = "unknown_tool") -> MessageChunk:
    return MessageChunk(
        role=MessageRole.TOOL.value,
        content=content,
        tool_call_id="call_1",
        message_type=MessageType.TOOL_CALL_RESULT.value,
        metadata={"tool_name": tool_name},
    )


def _detect_steps_from_rounds(rounds, max_period: int = 8):
    """
    回放每一轮输出，返回触发重复模式检测的轮次（1-based）。
    """
    signatures = []
    hit_steps = []
    for idx, round_chunks in enumerate(rounds, start=1):
        signatures.append(build_loop_signature(round_chunks))
        pattern = detect_repeat_pattern(signatures, max_period=max_period)
        if pattern:
            hit_steps.append(idx)
    return hit_steps


def _event_signature(events: list[str]) -> str:
    return json.dumps(
        {
            "assistant_text": "",
            "tool_calls": [],
            "tool_results": [],
            "events": events,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def test_detect_repeat_pattern_aaaa():
    signatures = ["A", "A", "A", "A"]
    pattern = detect_repeat_pattern(signatures)
    assert pattern is not None
    assert pattern["period"] == 1
    assert pattern["cycles"] >= 3


def test_detect_repeat_pattern_aabbaabb():
    signatures = ["A", "A", "B", "B", "A", "A", "B", "B"]
    pattern = detect_repeat_pattern(signatures)
    assert pattern is not None
    assert pattern["period"] == 4
    assert pattern["cycles"] == 2


def test_detect_repeat_pattern_abbabb():
    signatures = ["A", "B", "B", "A", "B", "B"]
    pattern = detect_repeat_pattern(signatures)
    assert pattern is not None
    assert pattern["period"] == 3
    assert pattern["cycles"] == 2


def test_detect_repeat_pattern_ababab():
    signatures = ["A", "B", "A", "B", "A", "B"]
    pattern = detect_repeat_pattern(signatures)
    assert pattern is not None
    assert pattern["period"] == 2
    assert pattern["cycles"] == 3


def test_detect_repeat_pattern_abcabcabc():
    signatures = ["A", "B", "C", "A", "B", "C", "A", "B", "C"]
    pattern = detect_repeat_pattern(signatures)
    assert pattern is not None
    assert pattern["period"] == 3
    assert pattern["cycles"] == 3


def test_detect_repeat_pattern_abcaabca():
    signatures = ["A", "B", "C", "A", "A", "B", "C", "A"]
    pattern = detect_repeat_pattern(signatures)
    assert pattern is not None
    assert pattern["period"] == 4
    assert pattern["cycles"] == 2


def test_detect_repeat_pattern_adjacent_repeat_after_different_signature():
    signatures = [
        build_loop_signature([_assistant_text("先查一下今天的消息。")]),
        build_loop_signature(
            [_assistant_tool_call("web_search", '{"query":"智谱 02513 今天"}')]
        ),
        build_loop_signature(
            [_assistant_tool_call("web_search", '{"query":"智谱 02513 今天"}')]
        ),
    ]
    pattern = detect_repeat_pattern(signatures)
    assert pattern is not None
    assert pattern["period"] == 1
    assert pattern["cycles"] == 2


def test_detect_repeat_pattern_adjacent_pure_text_repeat_after_different_signature():
    signatures = [
        build_loop_signature([_assistant_text("先补充图片参考。")]),
        build_loop_signature(
            [
                _assistant_text(
                    "继续执行中：我下一步会先补产地酒层与都市母女两组关键参考，再进入第一批镜头生成。"
                )
            ]
        ),
        build_loop_signature(
            [
                _assistant_text(
                    "继续执行中：我下一步会先补产地酒层与都市母女两组关键参考，再进入第一批镜头生成。"
                )
            ]
        ),
    ]
    pattern = detect_repeat_pattern(signatures)
    assert pattern is not None
    assert pattern["period"] == 1
    assert pattern["cycles"] == 2


def test_no_false_positive_for_non_repeating_sequence():
    signatures = ["A", "B", "C", "D", "E", "F", "G"]
    pattern = detect_repeat_pattern(signatures)
    assert pattern is None


def test_no_false_positive_for_near_repeat_but_not_cycle():
    signatures = ["A", "B", "A", "C", "A", "B", "A", "D"]
    pattern = detect_repeat_pattern(signatures)
    assert pattern is None


def test_signature_includes_tool_calls_and_args():
    chunks_1 = [_assistant_tool_call("read_file", '{"path":"a.md","lines":100}')]
    chunks_2 = [_assistant_tool_call("read_file", '{"path":"a.md","lines":200}')]

    sig_1 = build_loop_signature(chunks_1)
    sig_2 = build_loop_signature(chunks_2)
    assert sig_1 != sig_2


def test_signature_includes_tool_result_content():
    chunks_1 = [_tool_result("result one", tool_name="read_file")]
    chunks_2 = [_tool_result("result two", tool_name="read_file")]

    sig_1 = build_loop_signature(chunks_1)
    sig_2 = build_loop_signature(chunks_2)
    assert sig_1 != sig_2


def test_signature_distinguishes_tool_name_even_same_args():
    chunks_1 = [_assistant_tool_call("read_file", '{"path":"a.md","lines":100}')]
    chunks_2 = [_assistant_tool_call("grep_file", '{"path":"a.md","lines":100}')]

    sig_1 = build_loop_signature(chunks_1)
    sig_2 = build_loop_signature(chunks_2)
    assert sig_1 != sig_2


def test_signature_coalesces_streamed_tool_call_deltas():
    chunks_1 = [
        _assistant_tool_call_delta(
            call_id="call_1",
            index=0,
            name="web_search",
            arguments='{"query":"智谱',
        ),
        _assistant_tool_call_delta(
            index=0,
            arguments=' 02513 今天","count":10',
        ),
        _assistant_tool_call_delta(
            index=0,
            arguments=',"recency_filter":"oneDay"}',
        ),
    ]
    chunks_2 = [
        _assistant_tool_call_delta(
            call_id="call_2",
            index=0,
            name="web_search",
            arguments='{"query":"智谱 02513 今天",',
        ),
        _assistant_tool_call_delta(
            index=0,
            arguments='"count":10,"recency_filter":"oneDay"}',
        ),
    ]

    assert build_loop_signature(chunks_1) == build_loop_signature(chunks_2)


@pytest.mark.parametrize(
    ("left_chunks", "right_chunks"),
    [
        pytest.param(
            [
                _assistant_tool_call(
                    "web_search",
                    '{"query":"智谱 02513 今天","count":10,"recency_filter":"oneDay"}',
                )
            ],
            [
                _assistant_tool_call(
                    "web_search",
                    '{"recency_filter":"oneDay","count":10,"query":"智谱 02513 今天"}',
                )
            ],
            id="dict-tool-call-json-key-order",
        ),
        pytest.param(
            [
                _assistant_tool_calls(
                    [
                        _dict_tool_call(
                            name="web_search",
                            arguments={
                                "query": "智谱 02513 今天",
                                "count": 10,
                                "recency_filter": "oneDay",
                            },
                        )
                    ]
                )
            ],
            [
                _assistant_tool_call(
                    "web_search",
                    '{"query":"智谱 02513 今天","count":10,"recency_filter":"oneDay"}',
                )
            ],
            id="dict-arguments-vs-json-string",
        ),
        pytest.param(
            [
                _assistant_tool_call_delta(
                    call_id="call_1",
                    index=0,
                    name="web_search",
                    arguments='{"query":"智谱',
                ),
                _assistant_tool_call_delta(
                    index=0,
                    arguments=' 02513 今天","count":10',
                ),
                _assistant_tool_call_delta(
                    index=0,
                    arguments=',"recency_filter":"oneDay"}',
                ),
            ],
            [
                _assistant_tool_call_delta(
                    call_id="call_2",
                    index=0,
                    name="web_search",
                    arguments='{"query":"智谱 02513 今天",',
                ),
                _assistant_tool_call_delta(
                    index=0,
                    arguments='"count":10,"recency_filter":"oneDay"}',
                ),
            ],
            id="object-streamed-different-splits",
        ),
        pytest.param(
            [
                _assistant_tool_call_delta(
                    index=0,
                    name="web_search",
                    arguments='{"query":"智谱 02513 今天"',
                ),
                _assistant_tool_call_delta(
                    index=0,
                    arguments=',"count":10}',
                ),
            ],
            [
                _assistant_tool_call_delta(
                    index=0,
                    name="web_search",
                    arguments='{"count":10,',
                ),
                _assistant_tool_call_delta(
                    index=0,
                    arguments='"query":"智谱 02513 今天"}',
                ),
            ],
            id="streamed-without-id-by-index",
        ),
        pytest.param(
            [
                _assistant_tool_calls(
                    [
                        _dict_tool_call(
                            call_id="call_a",
                            name="web_search",
                            arguments='{"query":"智谱"}',
                        ),
                        _dict_tool_call(
                            call_id="call_b",
                            name="fetch_webpages",
                            arguments='{"urls":["https://example.com"]}',
                        ),
                    ]
                )
            ],
            [
                _assistant_tool_calls(
                    [
                        _dict_tool_call(
                            call_id="call_x",
                            name="web_search",
                            arguments='{"query":"智谱"}',
                        ),
                        _dict_tool_call(
                            call_id="call_y",
                            name="fetch_webpages",
                            arguments='{"urls":["https://example.com"]}',
                        ),
                    ]
                )
            ],
            id="multi-tool-same-order-different-call-ids",
        ),
    ],
)
def test_signature_equivalence_matrix_for_tool_calls(left_chunks, right_chunks):
    assert build_loop_signature(left_chunks) == build_loop_signature(right_chunks)


@pytest.mark.parametrize(
    ("left_chunks", "right_chunks"),
    [
        pytest.param(
            [_assistant_tool_call("web_search", '{"query":"智谱"}')],
            [_assistant_tool_call("web_search", '{"query":"阿里"}')],
            id="same-tool-different-args",
        ),
        pytest.param(
            [_assistant_tool_call("web_search", '{"query":"智谱"}')],
            [_assistant_tool_call("memory_recall", '{"query":"智谱"}')],
            id="same-args-different-tool",
        ),
        pytest.param(
            [
                _assistant_tool_calls(
                    [
                        _dict_tool_call(
                            call_id="call_a",
                            name="web_search",
                            arguments='{"query":"智谱"}',
                        ),
                        _dict_tool_call(
                            call_id="call_b",
                            name="fetch_webpages",
                            arguments='{"urls":["https://example.com"]}',
                        ),
                    ]
                )
            ],
            [
                _assistant_tool_calls(
                    [
                        _dict_tool_call(
                            call_id="call_y",
                            name="fetch_webpages",
                            arguments='{"urls":["https://example.com"]}',
                        ),
                        _dict_tool_call(
                            call_id="call_x",
                            name="web_search",
                            arguments='{"query":"智谱"}',
                        ),
                    ]
                )
            ],
            id="multi-tool-order-is-significant",
        ),
        pytest.param(
            [
                _assistant_tool_call_delta(
                    call_id="call_1",
                    index=0,
                    name="web_search",
                    arguments='{"query":"智谱"}',
                )
            ],
            [
                _assistant_tool_call_delta(
                    call_id="call_2",
                    index=0,
                    name="web_search",
                    arguments='{"query":"智谱","count":10}',
                )
            ],
            id="streamed-same-tool-different-final-args",
        ),
    ],
)
def test_signature_distinction_matrix_for_tool_calls(left_chunks, right_chunks):
    assert build_loop_signature(left_chunks) != build_loop_signature(right_chunks)


def test_signature_distinguishes_tool_result_tool_name():
    chunks_1 = [_tool_result("same content", tool_name="read_file")]
    chunks_2 = [_tool_result("same content", tool_name="grep_file")]

    sig_1 = build_loop_signature(chunks_1)
    sig_2 = build_loop_signature(chunks_2)
    assert sig_1 != sig_2


def test_signature_normalizes_assistant_text_whitespace():
    chunks_1 = [_assistant_text("让我读取 技术架构报告 的前100行")]
    chunks_2 = [_assistant_text("让我读取  技术架构报告   的前100行")]

    sig_1 = build_loop_signature(chunks_1)
    sig_2 = build_loop_signature(chunks_2)
    assert sig_1 == sig_2


def test_replay_detects_abab_text_loop():
    rounds = [
        [_assistant_text("让我读取技术架构报告的前 100 行：")],  # A
        [_assistant_text("我先读取目录，再继续。")],  # B
        [_assistant_text("让我读取技术架构报告的前 100 行：")],  # A
        [_assistant_text("我先读取目录，再继续。")],  # B
    ]
    hit_steps = _detect_steps_from_rounds(rounds)
    assert hit_steps and hit_steps[0] == 4


def test_replay_detects_adjacent_text_loop_on_second_repeat():
    rounds = [
        [_assistant_text("我先补齐图片参考。")],
        [
            _assistant_text(
                "继续执行中：我下一步会先补产地酒层与都市母女两组关键参考，再进入第一批镜头生成。"
            )
        ],
        [
            _assistant_text(
                "继续执行中：我下一步会先补产地酒层与都市母女两组关键参考，再进入第一批镜头生成。"
            )
        ],
    ]
    hit_steps = _detect_steps_from_rounds(rounds)
    assert hit_steps == [3]


@pytest.mark.parametrize(
    ("rounds", "expected_first_hit"),
    [
        pytest.param(
            [
                [_assistant_text("A")],
                [_assistant_text("A")],
            ],
            2,
            id="text-aa",
        ),
        pytest.param(
            [
                [_assistant_text("A")],
                [_assistant_text("B")],
                [_assistant_text("A")],
                [_assistant_text("B")],
            ],
            4,
            id="text-abab",
        ),
        pytest.param(
            [
                [_assistant_text("A")],
                [_assistant_tool_call("turn_status", '{"status":"continue_work"}')],
                [_assistant_text("A")],
                [_assistant_tool_call("turn_status", '{"status":"continue_work"}')],
            ],
            4,
            id="mixed-text-tool-abab",
        ),
        pytest.param(
            [
                [_assistant_tool_call("turn_status", '{"status":"continue_work"}')],
                [_assistant_tool_call("turn_status", '{"status":"continue_work"}')],
            ],
            2,
            id="tool-aa",
        ),
    ],
)
def test_repeat_detection_matrix_for_text_tool_and_mixed_rounds(
    rounds, expected_first_hit
):
    hit_steps = _detect_steps_from_rounds(rounds)
    assert hit_steps and hit_steps[0] == expected_first_hit


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        pytest.param(
            [
                "assistant_text:A",
                "tool_call:read",
                "assistant_text:A",
                "tool_call:read",
            ],
            {"mode": "event", "period": 2, "cycles": 2, "span": 4},
            id="text-tool-text-tool",
        ),
        pytest.param(
            [
                "assistant_text:A",
                "tool_call:read",
                "tool_result:read",
                "assistant_text:A",
                "tool_call:read",
                "tool_result:read",
            ],
            {"mode": "event", "period": 2, "cycles": 2, "span": 4},
            id="text-call-result-cycle-ignores-results",
        ),
        pytest.param(
            list("abcdefgabcdefg"),
            {"mode": "event", "period": 7, "cycles": 2, "span": 14},
            id="long-event-cycle",
        ),
    ],
)
def test_event_level_repeat_detection_matrix(events, expected):
    pattern = detect_repeat_pattern([_event_signature(events)])
    assert pattern is not None
    for key, value in expected.items():
        assert pattern[key] == value


def test_event_level_detects_partial_reentry_without_special_casing_tokens():
    pattern = detect_repeat_pattern([_event_signature(list("abcdefgabc"))])

    assert pattern is not None
    assert pattern["mode"] == "event"
    assert pattern["suffix_duplicate"] is True
    assert pattern["period"] == 3
    assert pattern["substring_length"] == 3
    assert pattern["previous_occurrences"] == 1


@pytest.mark.parametrize(
    ("events", "expected", "requires_suffix"),
    [
        pytest.param(
            ["A", "B", "C", "A", "B"],
            {"mode": "event", "period": 2, "substring_length": 2},
            True,
            id="non-adjacent-tail-ab",
        ),
        pytest.param(
            ["A", "B", "C", "D", "A", "B", "C", "D"],
            {"mode": "event", "period": 4, "cycles": 2},
            False,
            id="adjacent-tail-abcd",
        ),
        pytest.param(
            ["read:a", "write:b", "plan:c", "read:a", "write:b"],
            {"mode": "event", "period": 2, "substring_length": 2},
            True,
            id="tool-like-units-tail-repeat",
        ),
    ],
)
def test_suffix_duplicate_substring_matrix(events, expected, requires_suffix):
    pattern = detect_repeat_pattern([_event_signature(events)])

    assert pattern is not None
    if requires_suffix:
        assert pattern["suffix_duplicate"] is True
    for key, value in expected.items():
        assert pattern[key] == value


def test_suffix_duplicate_requires_new_tail_not_stale_middle_duplicate():
    pattern = detect_repeat_pattern([_event_signature(["A", "B", "A", "B", "C"])])

    assert pattern is None


def test_build_loop_signature_preserves_real_text_tool_event_order():
    signature = build_loop_signature(
        [
            _assistant_text("A"),
            _assistant_tool_calls(
                [
                    _dict_tool_call(
                        call_id="call_a", name="read_file", arguments='{"path":"a.md"}'
                    )
                ]
            ),
            _assistant_text("A"),
            _assistant_tool_calls(
                [
                    _dict_tool_call(
                        call_id="call_b", name="read_file", arguments='{"path":"a.md"}'
                    )
                ]
            ),
        ]
    )

    pattern = detect_repeat_pattern([signature])

    assert pattern is not None
    assert pattern["mode"] == "event"
    assert pattern["period"] == 2
    assert pattern["cycles"] == 2


def test_tool_call_projection_detects_repeated_params_through_text_noise():
    signatures = [
        build_loop_signature(
            [
                _assistant_text("我先重新查一下。"),
                _assistant_tool_call("web_search", '{"query":"Sage loop detection"}'),
            ]
        ),
        build_loop_signature(
            [
                _assistant_text("换个说法继续确认。"),
                _assistant_tool_call("web_search", '{"query":"Sage loop detection"}'),
            ]
        ),
    ]

    pattern = detect_repeat_pattern(signatures)

    assert pattern is not None
    assert pattern["mode"] == "tool_call"
    assert pattern["period"] == 1
    assert pattern["cycles"] == 2


def test_event_detection_ignores_varying_tool_results_for_same_call_params():
    signatures = [
        build_loop_signature(
            [
                _assistant_tool_call(
                    "fetch_webpages", '{"urls":["https://example.com"]}'
                ),
                _tool_result(
                    "request_id=aaa elapsed=10ms same substantive result",
                    "fetch_webpages",
                ),
            ]
        ),
        build_loop_signature(
            [
                _assistant_tool_call(
                    "fetch_webpages", '{"urls":["https://example.com"]}'
                ),
                _tool_result(
                    "request_id=bbb elapsed=20ms same substantive result",
                    "fetch_webpages",
                ),
            ]
        ),
    ]

    pattern = detect_repeat_pattern(signatures)

    assert pattern is not None
    assert pattern["mode"] == "event"
    assert pattern["period"] == 1
    assert pattern["cycles"] == 2


def test_tool_call_signature_masks_known_volatile_argument_fields():
    chunks_1 = [
        _assistant_tool_call(
            "execute_shell_command",
            '{"command":"ls","request_id":"req-1","trace_id":"trace-a"}',
        )
    ]
    chunks_2 = [
        _assistant_tool_call(
            "execute_shell_command",
            '{"trace_id":"trace-b","request_id":"req-2","command":"ls"}',
        )
    ]

    assert build_loop_signature(chunks_1) == build_loop_signature(chunks_2)


def test_replay_detects_tool_call_cycle():
    # A: read_file(100), B: read_file(200), 循环出现
    rounds = [
        [_assistant_tool_call("read_file", '{"path":"report.md","lines":100}')],
        [_assistant_tool_call("read_file", '{"path":"report.md","lines":200}')],
        [_assistant_tool_call("read_file", '{"path":"report.md","lines":100}')],
        [_assistant_tool_call("read_file", '{"path":"report.md","lines":200}')],
    ]
    hit_steps = _detect_steps_from_rounds(rounds)
    assert hit_steps and hit_steps[0] == 4


def test_replay_detects_repeated_streamed_tool_call_with_same_args():
    rounds = [
        [_assistant_text("先查一下今天的消息。")],
        [
            _assistant_tool_call_delta(
                call_id="call_1",
                index=0,
                name="web_search",
                arguments='{"query":"智谱 02513 今天","count":',
            ),
            _assistant_tool_call_delta(
                index=0,
                arguments='10,"recency_filter":"oneDay"}',
            ),
        ],
        [
            _assistant_tool_call_delta(
                call_id="call_2",
                index=0,
                name="web_search",
                arguments='{"query":"智谱 02513 今天",',
            ),
            _assistant_tool_call_delta(
                index=0,
                arguments='"count":10,"recency_filter":"oneDay"}',
            ),
        ],
    ]
    hit_steps = _detect_steps_from_rounds(rounds)
    assert hit_steps == [3]


def test_streamed_text_deltas_with_same_message_id_are_single_event():
    signature = build_loop_signature(
        [
            _assistant_text("ha", message_id="msg-1"),
            _assistant_text("ha", message_id="msg-1"),
            _assistant_text("ha", message_id="msg-1"),
            _assistant_text("ha", message_id="msg-1"),
        ]
    )

    assert detect_repeat_pattern([signature]) is None


def test_streamed_text_deltas_detect_obvious_five_repeat():
    signature = build_loop_signature(
        [
            _assistant_text("ha", message_id="msg-1"),
            _assistant_text("ha", message_id="msg-1"),
            _assistant_text("ha", message_id="msg-1"),
            _assistant_text("ha", message_id="msg-1"),
            _assistant_text("ha", message_id="msg-1"),
        ]
    )

    pattern = detect_repeat_pattern([signature])

    assert pattern is not None
    assert pattern["mode"] == "event"
    assert pattern["period"] == 1
    assert pattern["cycles"] == 5


def test_streamed_tool_call_aliases_late_id_to_existing_index():
    chunks = [
        _assistant_tool_call_delta(
            index=0,
            name="web_search",
            arguments='{"query":"Sage"',
        ),
        _assistant_tool_call_delta(
            call_id="call_late",
            index=0,
            arguments=',"count":10}',
        ),
    ]
    complete = [_assistant_tool_call("web_search", '{"query":"Sage","count":10}')]

    assert build_loop_signature(chunks) == build_loop_signature(complete)


def test_replay_not_detected_for_progressive_tool_plan():
    rounds = [
        [_assistant_tool_call("read_file", '{"path":"report.md","lines":50}')],
        [_tool_result("ok-50", tool_name="read_file")],
        [_assistant_tool_call("read_file", '{"path":"report.md","lines":100}')],
        [_tool_result("ok-100", tool_name="read_file")],
        [_assistant_tool_call("summarize", '{"source":"report.md","level":"brief"}')],
        [_tool_result("summary-ready", tool_name="summarize")],
    ]
    hit_steps = _detect_steps_from_rounds(rounds)
    assert hit_steps == []


def test_build_loop_signature_performance():
    round_chunks = [
        _assistant_text("让我读取技术架构报告的前 100 行："),
        _assistant_tool_call("read_file", '{"path":"report.md","lines":100}'),
        _tool_result("ok", tool_name="read_file"),
    ]
    start = time.perf_counter()
    for _ in range(5000):
        _ = build_loop_signature(round_chunks)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"build_loop_signature too slow: {elapsed:.4f}s"


def test_repeat_pattern_detection_performance():
    signatures = ["A", "B", "B"] * 8

    start = time.perf_counter()
    for _ in range(5000):
        pattern = detect_repeat_pattern(signatures, max_period=8)
        assert pattern is not None
    elapsed = time.perf_counter() - start

    # 经验阈值：本地与 CI 上应远低于该值，超限说明算法复杂度异常
    assert elapsed < 1.0, f"repeat pattern detection too slow: {elapsed:.4f}s"
