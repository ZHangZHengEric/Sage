#!/usr/bin/env python3
import asyncio
import unittest
from unittest.mock import patch

from app.cli.main import (
    CHAT_INPUT_PROMPT,
    CHAT_COMMAND_HELP,
    _collect_event_file_paths,
    _collect_event_tool_names,
    _emit_chat_exit_summary,
    _emit_stream_idle_notice,
    _emit_stream_idle_notice_for_state,
    _empty_render_state,
    _empty_stats,
    _stream_request,
    _print_plain_event,
    _record_stats_event,
    _render_assistant_content_delta,
)


class TestStatsToolDetection(unittest.TestCase):
    def test_chat_input_prompt_uses_sage_branding(self):
        self.assertEqual(CHAT_INPUT_PROMPT, "Sage> ")

    def test_chat_help_mentions_resume_and_history_commands(self):
        self.assertIn("sage resume <session_id>", CHAT_COMMAND_HELP)
        self.assertIn("sage sessions", CHAT_COMMAND_HELP)
        self.assertIn("sage sessions inspect latest", CHAT_COMMAND_HELP)

    def test_collects_tool_name_from_skill_tag(self):
        event = {
            "role": "assistant",
            "content": "<skill>\nsearch_memory\n</skill>\n<skill_input>\n{\"query\": \"foo\"}\n</skill_input>",
        }
        names = _collect_event_tool_names(event)
        self.assertEqual(names, ["search_memory"])

    def test_collects_tool_name_from_dsml_invoke_tag(self):
        event = {
            "role": "assistant",
            "content": "<｜DSML｜tool_calls>\n<｜DSML｜invoke name=\"ExecuteCommand\">",
        }
        names = _collect_event_tool_names(event)
        self.assertEqual(names, ["ExecuteCommand"])

    def test_collects_file_path_from_dsml_filewrite_tag(self):
        event = {
            "role": "assistant",
            "content": (
                "<｜DSML｜tool_calls>\n"
                "<｜DSML｜invoke name=\"FileWrite\">\n"
                "<｜DSML｜parameter name=\"file_path\" string=\"true\">"
                "/tmp/demo.py"
                "</｜DSML｜parameter>\n"
                "</｜DSML｜invoke>\n"
                "</｜DSML｜tool_calls>"
            ),
        }
        paths = _collect_event_file_paths(event)
        self.assertEqual(paths, ["/tmp/demo.py"])

    def test_records_tool_name_from_split_skill_stream(self):
        stats = _empty_stats(request=type("Request", (), {"session_id": None, "user_id": None, "agent_id": None, "agent_mode": "simple", "available_skills": [], "max_loop_count": 50})(), workspace=None)

        first_event = {
            "role": "assistant",
            "content": "<skill>\nsearch_memory\n</skill>\n<skill_input>\n",
        }
        second_event = {
            "role": "assistant",
            "content": "{\"query\": \"foo\"}\n</skill_input>\n<skill_result>\n<result>[]</result>\n</skill_result>",
        }

        _record_stats_event(stats, first_event, 0.0)
        _record_stats_event(stats, second_event, 0.0)

        self.assertEqual(stats["tools"], ["search_memory"])

    def test_render_assistant_content_hides_split_skill_markup(self):
        render_state = _empty_render_state()

        first_delta = _render_assistant_content_delta(
            render_state,
            "我先查一下。\n<skill>\nsearch_memory\n</skill>\n<skill_input>\n",
        )
        second_delta = _render_assistant_content_delta(
            render_state,
            "{\"query\": \"foo\"}\n</skill_input>\n<skill_result>\n<result>[]</result>\n</skill_result>\n查完了。",
        )

        self.assertEqual(first_delta, "我先查一下。")
        self.assertEqual(second_delta, "\n查完了。")

    def test_render_assistant_content_hides_dsml_block(self):
        render_state = _empty_render_state()

        first_delta = _render_assistant_content_delta(
            render_state,
            "开始处理。\n<｜DSML｜tool_calls>\n<｜DSML｜invoke name=\"ExecuteCommand\">",
        )
        second_delta = _render_assistant_content_delta(
            render_state,
            "<｜DSML｜parameter name=\"command\" string=\"true\">python3 --version</｜DSML｜parameter></｜DSML｜invoke></｜DSML｜tool_calls>\n处理完成。",
        )

        self.assertEqual(first_delta, "开始处理。")
        self.assertEqual(second_delta, "\n处理完成。")

    def test_render_assistant_content_preserves_inline_tag_examples(self):
        render_state = _empty_render_state()

        delta = _render_assistant_content_delta(
            render_state,
            "例如可以输出 `<skill>search_memory</skill>` 这样的标签示例。",
        )

        self.assertEqual(delta, "例如可以输出 `<skill>search_memory</skill>` 这样的标签示例。")

    def test_print_plain_event_emits_file_write_path_once(self):
        from io import StringIO
        from unittest.mock import patch

        render_state = _empty_render_state()
        event = {
            "role": "assistant",
            "content": (
                "<｜DSML｜tool_calls>\n"
                "<｜DSML｜invoke name=\"FileWrite\">\n"
                "<｜DSML｜parameter name=\"file_path\" string=\"true\">"
                "/tmp/demo.py"
                "</｜DSML｜parameter>\n"
                "</｜DSML｜invoke>\n"
                "</｜DSML｜tool_calls>"
            ),
        }

        stderr = StringIO()
        with patch("sys.stderr", stderr):
            _print_plain_event(event, render_state)
            _print_plain_event(event, render_state)

        self.assertEqual(stderr.getvalue().count("[file] wrote to: /tmp/demo.py"), 1)

    def test_emit_stream_idle_notice_format(self):
        from io import StringIO
        from unittest.mock import patch

        stderr = StringIO()
        with patch("sys.stderr", stderr):
            _emit_stream_idle_notice(4.2)

        self.assertIn("[working] still running (4.2s since last event)", stderr.getvalue())

    def test_emit_stream_idle_notice_prefers_tool_context(self):
        from io import StringIO
        from unittest.mock import patch

        stderr = StringIO()
        render_state = _empty_render_state()
        render_state["last_tool_name"] = "WriteFile"

        with patch("sys.stderr", stderr):
            _emit_stream_idle_notice_for_state(render_state, 5.0)

        self.assertIn("[working] waiting for WriteFile (5.0s since last event)", stderr.getvalue())

    def test_emit_stream_idle_notice_prefers_assistant_generation_context(self):
        from io import StringIO
        from unittest.mock import patch

        stderr = StringIO()
        render_state = _empty_render_state()
        render_state["last_visible_phase"] = "assistant_text"

        with patch("sys.stderr", stderr):
            _emit_stream_idle_notice_for_state(render_state, 3.5)

        self.assertIn("[working] generating response (3.5s since last event)", stderr.getvalue())

    def test_visible_assistant_text_clears_previous_tool_wait_context(self):
        from io import StringIO
        from unittest.mock import patch

        render_state = _empty_render_state()
        event = {
            "role": "assistant",
            "content": "继续输出正文。",
        }
        render_state["last_tool_name"] = "WriteFile"
        render_state["last_visible_phase"] = "tool"

        with patch("sys.stdout", StringIO()):
            _print_plain_event(event, render_state)

        stderr = StringIO()
        with patch("sys.stderr", stderr):
            _emit_stream_idle_notice_for_state(render_state, 4.0)

        self.assertIsNone(render_state["last_tool_name"])
        self.assertEqual(stderr.getvalue(), "")

    def test_idle_notice_is_suppressed_after_visible_assistant_output(self):
        from io import StringIO
        from unittest.mock import patch

        render_state = _empty_render_state()
        render_state["last_visible_phase"] = "assistant_text"
        render_state["assistant_emitted"] = "你好！"

        stderr = StringIO()
        with patch("sys.stderr", stderr):
            _emit_stream_idle_notice_for_state(render_state, 6.0)

        self.assertEqual(stderr.getvalue(), "")

    def test_emit_chat_exit_summary_prints_resume_hint(self):
        from io import StringIO
        from unittest.mock import patch

        stderr = StringIO()
        with patch("sys.stderr", stderr):
            _emit_chat_exit_summary("session-123", json_output=False)

        output = stderr.getvalue()
        self.assertIn("session_id: session-123", output)
        self.assertIn("resume: sage resume session-123", output)
        self.assertIn("history: sage sessions", output)

    def test_emit_chat_exit_summary_skips_json_output(self):
        from io import StringIO
        from unittest.mock import patch

        stderr = StringIO()
        with patch("sys.stderr", stderr):
            _emit_chat_exit_summary("session-123", json_output=True)

        self.assertEqual(stderr.getvalue(), "")


class TestStreamRequestIdlePolling(unittest.IsolatedAsyncioTestCase):
    async def test_stream_request_does_not_cancel_slow_stream_on_idle_poll(self):
        async def fake_run_request_stream(_request, workspace=None):
            del workspace
            await asyncio.sleep(1.2)
            yield {
                "role": "assistant",
                "content": "hello",
            }
            yield {
                "type": "stream_end",
            }

        request = type(
            "Request",
            (),
            {
                "session_id": "session-test",
                "user_id": "user-test",
                "agent_id": None,
                "agent_mode": "simple",
                "available_skills": [],
                "max_loop_count": 50,
            },
        )()

        from io import StringIO

        stdout = StringIO()
        stderr = StringIO()
        with (
            patch("app.cli.service.run_request_stream", fake_run_request_stream),
            patch("sys.stdout", stdout),
            patch("sys.stderr", stderr),
        ):
            result = await _stream_request(request, json_output=False, stats_output=False, workspace=None)

        self.assertEqual(result, 0)
        self.assertIn("hello", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
