"""
Unit tests for sagents.utils.sandbox._stdout_echo.

覆盖范围：
- echo_enabled 各种 env var 取值组合
- echo_chunk / echo_header / echo_footer 的输出格式与开关行为
- _safe_write 的异常吞咽
- run_with_streaming_stdout：基本成功 / 非零 rc / stderr 隔离 / 超时 partial output
  / cwd / env / echo 开关 / 大输出（多 chunk）/ 二进制非 UTF-8 字节兜底
"""
import os
import subprocess
import sys
import time
from typing import List

import pytest

from sagents.utils.sandbox import _stdout_echo
from sagents.utils.sandbox._stdout_echo import (
    echo_chunk,
    echo_enabled,
    echo_footer,
    echo_header,
    run_with_streaming_stdout,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_echo_env(monkeypatch):
    """每个用例开始前，清空 SAGE_ECHO_SHELL_OUTPUT，避免被外部环境污染。"""
    monkeypatch.delenv("SAGE_ECHO_SHELL_OUTPUT", raising=False)


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ---------------------------------------------------------------------------
# echo_enabled
# ---------------------------------------------------------------------------

class TestEchoEnabled:
    def test_default_when_unset_is_enabled(self, monkeypatch):
        monkeypatch.delenv("SAGE_ECHO_SHELL_OUTPUT", raising=False)
        assert echo_enabled() is True

    @pytest.mark.parametrize(
        "value",
        ["1", "true", "TRUE", "True", "yes", "YES", "on", "ON", " 1 ", "anything-else"],
    )
    def test_enabled_values(self, monkeypatch, value):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", value)
        assert echo_enabled() is True, f"value={value!r} 应被视为开启"

    @pytest.mark.parametrize(
        "value",
        ["0", "false", "FALSE", "False", "no", "NO", "off", "OFF", "", "  "],
    )
    def test_disabled_values(self, monkeypatch, value):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", value)
        assert echo_enabled() is False, f"value={value!r} 应被视为关闭"


# ---------------------------------------------------------------------------
# echo_chunk / echo_header / echo_footer
# ---------------------------------------------------------------------------

class TestEchoChunk:
    def test_writes_to_stdout_when_enabled(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "1")
        echo_chunk("hello world\n")
        out = capsys.readouterr().out
        assert out == "hello world\n"

    def test_silent_when_disabled(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "0")
        echo_chunk("must not appear")
        assert capsys.readouterr().out == ""

    def test_empty_string_is_noop(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "1")
        echo_chunk("")
        assert capsys.readouterr().out == ""

    def test_none_is_noop(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "1")
        # 类型注解是 str，但代码用 `if not text` 兜底；显式传 None 不应抛
        echo_chunk(None)  # type: ignore[arg-type]
        assert capsys.readouterr().out == ""

    def test_swallows_stdout_write_exception(self, monkeypatch):
        """sys.stdout.write 抛异常时，echo_chunk 必须静默吞掉，不能影响主流程。"""
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "1")

        class _BrokenStdout:
            def write(self, _):
                raise RuntimeError("disk full")

            def flush(self):
                raise RuntimeError("disk full")

        monkeypatch.setattr(sys, "stdout", _BrokenStdout())
        # 不应抛
        echo_chunk("payload")

    def test_unicode_passthrough(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "1")
        echo_chunk("中文 🚀 emoji\n")
        assert capsys.readouterr().out == "中文 🚀 emoji\n"


class TestEchoHeader:
    def test_default_format(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "1")
        echo_header("ls -la")
        assert capsys.readouterr().out == "\n$ ls -la\n"

    def test_silent_when_disabled(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "0")
        echo_header("ls -la")
        assert capsys.readouterr().out == ""

    def test_truncates_long_command(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "1")
        long_cmd = "x" * 800
        echo_header(long_cmd)
        out = capsys.readouterr().out
        # 头/尾各一个 \n + "$ " 前缀 + 500 个字符 + " …"
        assert out.startswith("\n$ ") and out.endswith(" …\n")
        body = out[len("\n$ "):-len(" …\n")]
        assert body == "x" * 500

    def test_empty_command_still_emits_marker(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "1")
        echo_header("")
        assert capsys.readouterr().out == "\n$ \n"

    def test_custom_tag(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "1")
        echo_header("pwd", tag=">>>")
        assert capsys.readouterr().out == "\n>>> pwd\n"


class TestEchoFooter:
    def test_with_int_rc(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "1")
        echo_footer(0)
        assert capsys.readouterr().out == "↪ rc=0\n"

    def test_with_nonzero_rc(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "1")
        echo_footer(137)
        assert capsys.readouterr().out == "↪ rc=137\n"

    def test_with_none_rc(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "1")
        echo_footer(None)
        assert capsys.readouterr().out == "↪ rc=?\n"

    def test_silent_when_disabled(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "0")
        echo_footer(0)
        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# run_with_streaming_stdout
# ---------------------------------------------------------------------------

class TestRunWithStreamingStdout:
    def test_simple_success_returns_rc_stdout(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "1")
        rc, out, err = run_with_streaming_stdout(
            ["/bin/sh", "-c", "echo hello"], timeout=5
        )
        assert rc == 0
        assert out == "hello\n"
        assert err == ""
        # 同时也实时回显到 stdout
        captured = capsys.readouterr().out
        assert "hello\n" in captured

    def test_nonzero_returncode_does_not_raise(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "0")
        rc, out, err = run_with_streaming_stdout(
            ["/bin/sh", "-c", "echo bye; exit 7"], timeout=5
        )
        assert rc == 7
        assert out == "bye\n"
        assert err == ""

    def test_stderr_captured_separately_and_not_echoed(self, monkeypatch, capsys):
        """stderr 必须独立捕获，且不会被 echo 到本进程 stdout。"""
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "1")
        rc, out, err = run_with_streaming_stdout(
            ["/bin/sh", "-c", "echo on-out; echo on-err 1>&2; exit 0"],
            timeout=5,
        )
        assert rc == 0
        assert out == "on-out\n"
        assert err == "on-err\n"
        echoed = capsys.readouterr().out
        # 只有 stdout 被回显
        assert "on-out\n" in echoed
        assert "on-err" not in echoed

    def test_echo_disabled_does_not_write_to_stdout(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "0")
        rc, out, _ = run_with_streaming_stdout(
            ["/bin/sh", "-c", "echo silent"], timeout=5
        )
        assert rc == 0
        assert out == "silent\n"
        # 关闭后不应往 stdout 回显
        assert capsys.readouterr().out == ""

    def test_cwd_takes_effect(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "0")
        target = tmp_path / "subdir"
        target.mkdir()
        rc, out, _ = run_with_streaming_stdout(
            ["/bin/sh", "-c", "pwd"], cwd=str(target), timeout=5
        )
        assert rc == 0
        # macOS 下 /tmp 会被解析成 /private/tmp，做 realpath 比较
        assert os.path.realpath(out.strip()) == os.path.realpath(str(target))

    def test_env_takes_effect(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "0")
        rc, out, _ = run_with_streaming_stdout(
            ["/bin/sh", "-c", "echo $MY_TEST_VAR"],
            env={"MY_TEST_VAR": "abc123", "PATH": os.environ.get("PATH", "")},
            timeout=5,
        )
        assert rc == 0
        assert out == "abc123\n"

    def test_timeout_raises_with_partial_output(self, monkeypatch, capsys):
        """超时必须抛 TimeoutExpired，且把已收集到的 stdout 带回来。"""
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "1")
        start = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired) as exc_info:
            run_with_streaming_stdout(
                ["/bin/sh", "-c", "echo before; sleep 5; echo after"],
                timeout=0.5,
            )
        elapsed = time.monotonic() - start
        # 应该在 ~0.5s 杀掉，绝不该跑满 5s
        assert elapsed < 3.0, f"超时未生效，跑了 {elapsed:.2f}s"
        te = exc_info.value
        # partial output 已经包含 before
        partial = te.output or ""
        assert "before" in partial
        assert "after" not in partial

    def test_large_output_streams_in_chunks(self, monkeypatch, capsys):
        """跨多个 4KB chunk 的大输出，应该完整捕获且实时回显。"""
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "1")
        # 生成 ~30KB 输出
        rc, out, err = run_with_streaming_stdout(
            ["/bin/sh", "-c", "yes 'line' 2>/dev/null | head -n 5000"],
            timeout=10,
        )
        assert rc == 0
        lines = out.splitlines()
        assert len(lines) == 5000
        assert all(line == "line" for line in lines)
        # echo 也覆盖完整
        echoed = capsys.readouterr().out
        assert echoed.count("line\n") == 5000

    def test_invalid_utf8_does_not_crash(self, monkeypatch, capsys):
        """非 UTF-8 字节应被 errors='replace' 兜底，不抛异常。"""
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "1")
        # printf '\xff\xfe\xfd' → 3 个非法 UTF-8 字节
        rc, out, err = run_with_streaming_stdout(
            ["/bin/sh", "-c", r"printf '\xff\xfe\xfd'"],
            timeout=5,
        )
        assert rc == 0
        # 三个字节都被替换为 U+FFFD（一个或多个）
        assert "\ufffd" in out

    def test_ordering_preserves_command_output_then_echo(self, monkeypatch, capsys):
        """同一行命令输出，echo 顺序应当与捕获顺序一致（按到达顺序流式）。"""
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "1")
        rc, out, _ = run_with_streaming_stdout(
            ["/bin/sh", "-c", "echo A; echo B; echo C"], timeout=5
        )
        assert out == "A\nB\nC\n"
        echoed = capsys.readouterr().out
        # 多个 chunk 合并后仍保持 A B C 顺序
        idx_a, idx_b, idx_c = echoed.find("A"), echoed.find("B"), echoed.find("C")
        assert 0 <= idx_a < idx_b < idx_c

    def test_no_timeout_runs_to_completion(self, monkeypatch, capsys):
        """timeout=None 时不应启用 deadline 分支，命令正常跑完。"""
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "0")
        rc, out, _ = run_with_streaming_stdout(
            ["/bin/sh", "-c", "echo done"], timeout=None
        )
        assert rc == 0
        assert out == "done\n"

    def test_streaming_actually_arrives_before_process_exit(self, monkeypatch, capsys):
        """关键的"实时性"断言：在子进程结束前，前半段 stdout 就已经被 echo 出来。

        通过 monkeypatch 拦截 _stdout_echo.echo_chunk，在每次回调时打 timestamp，
        然后比较第一次 chunk 到达时间与命令总耗时的差值。
        """
        monkeypatch.setenv("SAGE_ECHO_SHELL_OUTPUT", "1")
        events: List[tuple] = []  # (t_relative, chunk)
        original_echo = _stdout_echo.echo_chunk

        def _spy(chunk):
            events.append((time.monotonic(), chunk))
            return original_echo(chunk)

        monkeypatch.setattr(_stdout_echo, "echo_chunk", _spy)

        t0 = time.monotonic()
        rc, out, _ = run_with_streaming_stdout(
            ["/bin/sh", "-c", "echo first; sleep 0.6; echo second"],
            timeout=5,
        )
        total = time.monotonic() - t0

        assert rc == 0
        assert out == "first\nsecond\n"
        assert events, "至少应该收到一次 echo_chunk 回调"

        # 第一次 chunk 必须在命令真正结束前就到达
        first_chunk_at = events[0][0] - t0
        assert first_chunk_at < total - 0.2, (
            f"first chunk 在 {first_chunk_at:.2f}s 才到达，"
            f"总耗时 {total:.2f}s，未达到流式效果"
        )
        # 且第一次到达的 chunk 必含 'first' 而不含 'second'
        assert "first" in events[0][1] and "second" not in events[0][1]
