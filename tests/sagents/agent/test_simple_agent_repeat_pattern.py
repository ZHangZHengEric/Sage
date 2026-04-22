import time
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.utils.repeat_pattern import build_loop_signature, detect_repeat_pattern


def _assistant_text(content: str) -> MessageChunk:
    return MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content=content,
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
        [_assistant_text("我先读取目录，再继续。")],            # B
        [_assistant_text("让我读取技术架构报告的前 100 行：")],  # A
        [_assistant_text("我先读取目录，再继续。")],            # B
    ]
    hit_steps = _detect_steps_from_rounds(rounds)
    assert hit_steps and hit_steps[0] == 4


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
