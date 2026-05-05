#!/usr/bin/env python3
import asyncio
import unittest
from contextlib import asynccontextmanager
from io import StringIO
from argparse import Namespace
from unittest.mock import patch

import app.cli.main as cli_main
from common.schemas.goal import GoalMutation
from app.cli.commands.session import _handle_goal_command
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
    _finalize_stats,
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

    def test_goal_command_shorthand_sets_goal_objective_and_returns_task(self):
        args = Namespace(
            goal_objective=None,
            goal_status=None,
            clear_goal=False,
        )

        with patch("sys.stdout", new=StringIO()) as stdout:
            task = _handle_goal_command(
                "/goal ship the runtime goal contract",
                args,
                session_summary=None,
            )

        self.assertEqual(task, "ship the runtime goal contract")
        self.assertEqual(args.goal_objective, "ship the runtime goal contract")
        self.assertEqual(args.goal_status, "active")
        self.assertFalse(args.clear_goal)
        self.assertIn("goal set: ship the runtime goal contract", stdout.getvalue())

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

    def test_records_structured_tool_steps_from_tool_events(self):
        stats = _empty_stats(
            request=type(
                "Request",
                (),
                {
                    "session_id": None,
                    "user_id": None,
                    "agent_id": None,
                    "agent_mode": "simple",
                    "available_skills": [],
                    "max_loop_count": 50,
                },
            )(),
            workspace=None,
        )

        _record_stats_event(
            stats,
            {
                "type": "tool_call",
                "timestamp": 10.0,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "read_file",
                            "arguments": "{\"path\":\"/tmp/demo.txt\"}",
                        },
                    }
                ],
            },
            0.0,
        )
        _record_stats_event(
            stats,
            {
                "type": "tool_result",
                "role": "tool",
                "timestamp": 10.12,
                "tool_call_id": "call_1",
                "metadata": {"tool_name": "read_file"},
            },
            0.0,
        )

        self.assertEqual(len(stats["tool_steps"]), 1)
        self.assertEqual(stats["tool_steps"][0]["step"], 1)
        self.assertEqual(stats["tool_steps"][0]["tool_name"], "read_file")
        self.assertEqual(stats["tool_steps"][0]["status"], "completed")
        self.assertEqual(stats["tool_steps"][0]["started_at"], 10.0)
        self.assertEqual(stats["tool_steps"][0]["finished_at"], 10.12)
        self.assertAlmostEqual(stats["tool_steps"][0]["duration_ms"], 120.0)

    def test_token_usage_tool_steps_override_local_inference(self):
        stats = _empty_stats(
            request=type(
                "Request",
                (),
                {
                    "session_id": None,
                    "user_id": None,
                    "agent_id": None,
                    "agent_mode": "simple",
                    "available_skills": [],
                    "max_loop_count": 50,
                },
            )(),
            workspace=None,
        )

        _record_stats_event(
            stats,
            {
                "type": "tool_call",
                "timestamp": 10.0,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }
                ],
            },
            0.0,
        )
        _record_stats_event(
            stats,
            {
                "type": "token_usage",
                "metadata": {
                    "token_usage": {
                        "total_info": {
                            "prompt_tokens": 10,
                            "completion_tokens": 20,
                            "total_tokens": 30,
                        }
                    },
                    "tool_steps": [
                        {
                            "step": 7,
                            "tool_name": "grep",
                            "tool_call_id": "call_7",
                            "status": "completed",
                            "started_at": 11.0,
                            "finished_at": 11.08,
                            "duration_ms": 80.0,
                        }
                    ],
                },
            },
            0.0,
        )

        self.assertEqual(stats["prompt_tokens"], 10)
        self.assertEqual(stats["completion_tokens"], 20)
        self.assertEqual(stats["total_tokens"], 30)
        self.assertEqual(stats["tool_steps"][0]["step"], 7)
        self.assertEqual(stats["tool_steps"][0]["tool_name"], "grep")

    def test_records_phase_timings_across_planning_tool_and_assistant_output(self):
        stats = _empty_stats(
            request=type(
                "Request",
                (),
                {
                    "session_id": None,
                    "user_id": None,
                    "agent_id": None,
                    "agent_mode": "simple",
                    "available_skills": [],
                    "max_loop_count": 50,
                },
            )(),
            workspace=None,
        )

        _record_stats_event(
            stats,
            {"type": "analysis", "role": "assistant", "content": "先分析一下。", "timestamp": 10.0},
            0.0,
        )
        _record_stats_event(
            stats,
            {
                "type": "tool_call",
                "timestamp": 10.3,
                "tool_calls": [{"id": "call_1", "function": {"name": "read_file", "arguments": "{}"}}],
            },
            0.0,
        )
        _record_stats_event(
            stats,
            {"type": "text", "role": "assistant", "content": "处理完成。", "timestamp": 11.1},
            0.0,
        )
        _finalize_stats(stats, finished_at=11.5)

        self.assertEqual([item["phase"] for item in stats["phase_timings"]], [
            "planning",
            "tool",
            "assistant_text",
        ])
        self.assertAlmostEqual(stats["phase_timings"][0]["duration_ms"], 300.0)
        self.assertAlmostEqual(stats["phase_timings"][1]["duration_ms"], 800.0)
        self.assertAlmostEqual(stats["phase_timings"][2]["duration_ms"], 400.0)

    def test_token_usage_phase_timings_override_local_inference(self):
        stats = _empty_stats(
            request=type(
                "Request",
                (),
                {
                    "session_id": None,
                    "user_id": None,
                    "agent_id": None,
                    "agent_mode": "simple",
                    "available_skills": [],
                    "max_loop_count": 50,
                },
            )(),
            workspace=None,
        )

        _record_stats_event(
            stats,
            {"type": "analysis", "role": "assistant", "content": "先分析一下。", "timestamp": 10.0},
            0.0,
        )
        _record_stats_event(
            stats,
            {
                "type": "token_usage",
                "metadata": {
                    "phase_timings": [
                        {
                            "phase": "planning",
                            "started_at": 9.9,
                            "finished_at": 10.6,
                            "duration_ms": 700.0,
                            "segment_count": 1,
                        }
                    ]
                },
            },
            0.0,
        )
        _finalize_stats(stats, finished_at=11.0)

        self.assertEqual(len(stats["phase_timings"]), 1)
        self.assertEqual(stats["phase_timings"][0]["phase"], "planning")
        self.assertEqual(stats["phase_timings"][0]["duration_ms"], 700.0)

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
    async def test_stream_request_emits_cli_session_event_in_json_mode(self):
        async def fake_run_request_stream(_request, workspace=None):
            del workspace
            yield {
                "type": "assistant",
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
                "agent_id": "agent-demo",
                "agent_mode": "simple",
                "available_skills": ["search_memory"],
                "max_loop_count": 50,
            },
        )()

        from io import StringIO
        import json

        stdout = StringIO()
        stderr = StringIO()
        with (
            patch("app.cli.service.run_request_stream", fake_run_request_stream),
            patch("sys.stdout", stdout),
            patch("sys.stderr", stderr),
        ):
            result = await _stream_request(
                request,
                json_output=True,
                stats_output=False,
                workspace="/tmp/demo-workspace",
                command_mode="resume",
                session_summary={
                    "session_id": "session-test",
                    "title": "Demo session",
                    "message_count": 4,
                },
            )

        self.assertEqual(result, 0)
        events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip().startswith("{")]
        self.assertEqual(
            events[0],
            {
                "type": "cli_session",
                "command_mode": "resume",
                "session_state": "existing",
                "session_id": "session-test",
                "user_id": "user-test",
                "agent_id": "agent-demo",
                "agent_mode": "simple",
                "workspace": "/tmp/demo-workspace",
                "workspace_source": "explicit",
                "requested_skills": ["search_memory"],
                "max_loop_count": 50,
                "goal": None,
                "goal_transition": None,
                "has_prior_messages": True,
                "prior_message_count": 4,
                "session_summary": {
                    "session_id": "session-test",
                    "title": "Demo session",
                    "message_count": 4,
                },
            },
        )
        self.assertEqual(events[1], {"type": "cli_phase", "phase": "assistant_text"})
        self.assertEqual(events[2]["type"], "assistant")

    async def test_stream_request_generates_session_id_before_cli_session_event(self):
        async def fake_run_request_stream(_request, workspace=None):
            del workspace
            yield {
                "type": "assistant",
                "role": "assistant",
                "content": "hello",
                "session_id": _request.session_id,
            }
            yield {
                "type": "stream_end",
            }

        request = type(
            "Request",
            (),
            {
                "session_id": None,
                "user_id": "user-test",
                "agent_id": None,
                "agent_mode": "simple",
                "available_skills": [],
                "max_loop_count": 50,
            },
        )()

        from io import StringIO
        import json

        stdout = StringIO()
        stderr = StringIO()
        with (
            patch("app.cli.service.run_request_stream", fake_run_request_stream),
            patch("sys.stdout", stdout),
            patch("sys.stderr", stderr),
        ):
            result = await _stream_request(
                request,
                json_output=True,
                stats_output=True,
                workspace=None,
                command_mode="run",
            )

        self.assertEqual(result, 0)
        events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip().startswith("{")]
        self.assertEqual(events[0]["type"], "cli_session")
        self.assertEqual(events[0]["command_mode"], "run")
        self.assertEqual(events[0]["session_state"], "new")
        self.assertEqual(events[0]["workspace_source"], "default")
        self.assertEqual(events[0]["has_prior_messages"], False)
        self.assertEqual(events[0]["prior_message_count"], 0)
        self.assertIsNone(events[0]["session_summary"])
        self.assertIsNone(events[0]["goal"])
        self.assertIsNone(events[0]["goal_transition"])
        self.assertIsInstance(events[0]["session_id"], str)
        self.assertTrue(events[0]["session_id"])
        self.assertEqual(request.session_id, events[0]["session_id"])
        self.assertEqual(events[-1]["type"], "cli_stats")
        self.assertEqual(events[-1]["session_id"], events[0]["session_id"])

    async def test_stream_request_emits_goal_payload_in_cli_session_event(self):
        async def fake_run_request_stream(_request, workspace=None):
            del workspace
            yield {
                "type": "assistant",
                "role": "assistant",
                "content": "working",
            }
            yield {"type": "stream_end"}

        request = type(
            "Request",
            (),
            {
                "session_id": "session-goal",
                "user_id": "user-test",
                "agent_id": None,
                "agent_mode": "simple",
                "available_skills": [],
                "max_loop_count": 50,
                "goal": GoalMutation(
                    objective="Ship the runtime goal contract",
                    status="active",
                ),
            },
        )()

        from io import StringIO
        import json

        stdout = StringIO()
        with (
            patch("app.cli.service.run_request_stream", fake_run_request_stream),
            patch("sys.stdout", stdout),
            patch("sys.stderr", StringIO()),
            patch("app.cli.runtime.stream.STREAM_IDLE_NOTICE_SECONDS", 0.5),
            patch("app.cli.runtime.stream.STREAM_IDLE_REPEAT_SECONDS", 0.5),
        ):
            result = await _stream_request(
                request,
                json_output=True,
                stats_output=False,
                workspace=None,
                command_mode="run",
            )

        self.assertEqual(result, 0)
        events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip().startswith("{")]
        self.assertEqual(
            events[0]["goal"],
            {
                "objective": "Ship the runtime goal contract",
                "status": "active",
            },
        )
        self.assertIsNone(events[0]["goal_transition"])
        self.assertEqual(events[1]["type"], "cli_goal")
        self.assertEqual(events[1]["source"], "session_start")
        self.assertEqual(events[1]["goal"]["status"], "active")

    async def test_stream_request_emits_cli_notice_when_json_stream_is_idle(self):
        async def fake_run_request_stream(_request, workspace=None):
            del workspace
            await asyncio.sleep(0.01)
            yield {
                "type": "assistant",
                "role": "assistant",
                "content": "hello",
            }
            yield {"type": "stream_end"}

        request = type(
            "Request",
            (),
            {
                "session_id": "session-idle-notice",
                "user_id": "user-test",
                "agent_id": None,
                "agent_mode": "simple",
                "available_skills": [],
                "max_loop_count": 50,
                "goal": None,
            },
        )()

        from io import StringIO
        import json
        original_wait_for = asyncio.wait_for
        first_poll = {"value": True}

        async def fake_wait_for(awaitable, timeout):
            if first_poll["value"]:
                first_poll["value"] = False
                raise asyncio.TimeoutError
            return await original_wait_for(awaitable, timeout)

        stdout = StringIO()
        with (
            patch("app.cli.service.run_request_stream", fake_run_request_stream),
            patch("sys.stdout", stdout),
            patch("sys.stderr", StringIO()),
            patch("app.cli.runtime.stream.asyncio.wait_for", fake_wait_for),
            patch("app.cli.runtime.stream.STREAM_IDLE_NOTICE_SECONDS", 0.0),
            patch("app.cli.runtime.stream.STREAM_IDLE_REPEAT_SECONDS", 0.0),
        ):
            result = await _stream_request(
                request,
                json_output=True,
                stats_output=False,
                workspace=None,
                command_mode="run",
            )

        self.assertEqual(result, 0)
        payload = stdout.getvalue()
        self.assertIn('"type": "cli_notice"', payload)
        events = [json.loads(line) for line in payload.splitlines() if line.strip().startswith("{")]
        notice_event = next((event for event in events if event.get("type") == "cli_notice"), None)
        self.assertIsNotNone(notice_event)
        notice_event = notice_event
        self.assertEqual(notice_event["session_id"], "session-idle-notice")
        self.assertEqual(notice_event["source"], "idle_poll")
        self.assertIn("[working]", notice_event["content"])

    async def test_stream_request_emits_refreshed_cli_session_after_completion(self):
        async def fake_run_request_stream(_request, workspace=None):
            del workspace
            yield {
                "type": "assistant",
                "role": "assistant",
                "content": "done",
            }
            yield {"type": "stream_end"}

        request = type(
            "Request",
            (),
            {
                "session_id": "session-goal-refresh",
                "user_id": "user-test",
                "agent_id": "agent-demo",
                "agent_mode": "simple",
                "available_skills": [],
                "max_loop_count": 50,
                "goal": GoalMutation(
                    objective="Ship the runtime goal contract",
                    status="active",
                ),
            },
        )()

        from io import StringIO
        import json

        stdout = StringIO()
        with (
            patch("app.cli.service.run_request_stream", fake_run_request_stream),
            patch(
                "app.cli.service.get_session_summary",
                return_value={
                    "session_id": "session-goal-refresh",
                    "title": "Goal refresh demo",
                    "message_count": 2,
                    "goal": {
                        "objective": "Ship the runtime goal contract",
                        "status": "completed",
                    },
                    "goal_transition": {
                        "type": "completed",
                        "objective": "Ship the runtime goal contract",
                        "status": "completed",
                    },
                },
            ),
            patch("sys.stdout", stdout),
            patch("sys.stderr", StringIO()),
        ):
            result = await _stream_request(
                request,
                json_output=True,
                stats_output=False,
                workspace=None,
                command_mode="run",
            )

        self.assertEqual(result, 0)
        events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip().startswith("{")]
        session_events = [event for event in events if event.get("type") == "cli_session"]
        goal_events = [event for event in events if event.get("type") == "cli_goal"]
        self.assertEqual(len(session_events), 2)
        self.assertEqual(len(goal_events), 2)
        self.assertEqual(session_events[0]["session_state"], "new")
        self.assertEqual(session_events[0]["goal"]["status"], "active")
        self.assertEqual(session_events[1]["session_state"], "existing")
        self.assertEqual(session_events[1]["goal"]["status"], "completed")
        self.assertEqual(session_events[1]["goal_transition"]["type"], "completed")
        self.assertEqual(session_events[1]["prior_message_count"], 2)
        self.assertEqual(goal_events[-1]["source"], "session_refresh")
        self.assertEqual(goal_events[-1]["goal"]["status"], "completed")
        self.assertEqual(goal_events[-1]["goal_transition"]["type"], "completed")

    async def test_stream_request_emits_dedicated_cli_goal_event_for_runtime_goal_updates(self):
        async def fake_run_request_stream(_request, workspace=None):
            del workspace
            yield {
                "type": "tool_result",
                "metadata": {"tool_name": "turn_status"},
                "content": "completed turn_status",
                "goal": {
                    "objective": "Ship the runtime goal contract",
                    "status": "completed",
                },
                "goal_transition": {
                    "type": "completed",
                    "objective": "Ship the runtime goal contract",
                    "status": "completed",
                },
                "goal_outcome": {
                    "action": "completed",
                    "objective": "Ship the runtime goal contract",
                    "reason": "ok",
                },
            }
            yield {"type": "stream_end"}

        request = type(
            "Request",
            (),
            {
                "session_id": "session-goal-event",
                "user_id": "user-test",
                "agent_id": None,
                "agent_mode": "simple",
                "available_skills": [],
                "max_loop_count": 50,
                "goal": None,
            },
        )()

        from io import StringIO
        import json

        stdout = StringIO()
        with (
            patch("app.cli.service.run_request_stream", fake_run_request_stream),
            patch("sys.stdout", stdout),
            patch("sys.stderr", StringIO()),
        ):
            result = await _stream_request(
                request,
                json_output=True,
                stats_output=False,
                workspace=None,
                command_mode="run",
            )

        self.assertEqual(result, 0)
        events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip().startswith("{")]
        goal_events = [event for event in events if event.get("type") == "cli_goal"]
        runtime_goal_event = next(
            event for event in goal_events if event.get("source") == "tool_result"
        )
        self.assertEqual(runtime_goal_event["goal"]["status"], "completed")
        self.assertEqual(runtime_goal_event["goal_transition"]["type"], "completed")
        self.assertEqual(runtime_goal_event["goal_outcome"]["action"], "completed")

    async def test_stream_request_idle_notice_prefers_recent_session_warning(self):
        async def fake_run_request_stream(_request, workspace=None):
            del workspace
            await asyncio.sleep(0.01)
            yield {"type": "stream_end"}

        request = type(
            "Request",
            (),
            {
                "session_id": "session-warning-notice",
                "user_id": "user-test",
                "agent_id": None,
                "agent_mode": "simple",
                "available_skills": [],
                "max_loop_count": 50,
                "goal": None,
            },
        )()

        from datetime import datetime
        from io import StringIO
        import json
        import os
        import tempfile

        original_wait_for = asyncio.wait_for
        first_poll = {"value": True}

        async def fake_wait_for(awaitable, timeout):
            if first_poll["value"]:
                first_poll["value"] = False
                raise asyncio.TimeoutError
            return await original_wait_for(awaitable, timeout)

        with tempfile.TemporaryDirectory() as tempdir:
            session_dir = os.path.join(tempdir, request.session_id)
            os.makedirs(session_dir, exist_ok=True)
            session_log = os.path.join(session_dir, f"session_{request.session_id}.log")
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
            with open(session_log, "w", encoding="utf-8") as handle:
                handle.write(
                    f"{timestamp} - WARNING - [agent/agent_base.py:425] - ToolSuggestionAgent: 遇到网络连接错误，等待 2 秒后重试 (1/8): Connection error.\n"
                )

            stdout = StringIO()
            with (
                patch("app.cli.service.run_request_stream", fake_run_request_stream),
                patch("sys.stdout", stdout),
                patch("sys.stderr", StringIO()),
                patch("app.cli.runtime.stream.asyncio.wait_for", fake_wait_for),
                patch("app.cli.runtime.stream.STREAM_IDLE_NOTICE_SECONDS", 0.0),
                patch("app.cli.runtime.stream.STREAM_IDLE_REPEAT_SECONDS", 0.0),
                patch.dict("os.environ", {"SAGE_SESSION_DIR": tempdir}, clear=False),
            ):
                result = await _stream_request(
                    request,
                    json_output=True,
                    stats_output=False,
                    workspace=None,
                    command_mode="chat",
                )

        self.assertEqual(result, 0)
        events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip().startswith("{")]
        notice_event = next((event for event in events if event.get("type") == "cli_notice"), None)
        self.assertIsNotNone(notice_event)
        self.assertIn("ToolSuggestionAgent", notice_event["content"])
        self.assertIn("Connection error.", notice_event["content"])

    async def test_run_command_normalizes_workspace_before_stream_request(self):
        args = cli_main.build_argument_parser().parse_args(["run", "--workspace", "./demo", "hello"])
        captured = {}

        @asynccontextmanager
        async def fake_cli_runtime(*, verbose=False):
            del verbose
            yield object()

        async def fake_build_request(_args, task):
            captured["build_workspace"] = _args.workspace
            captured["task"] = task
            return type(
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

        async def fake_stream_request(request, json_output, stats_output, workspace=None, *, command_mode="run", session_summary=None):
            del request, json_output, stats_output, session_summary
            captured["stream_workspace"] = workspace
            captured["command_mode"] = command_mode
            return 0

        with (
            patch("app.cli.service.validate_cli_runtime_requirements"),
            patch("app.cli.service.validate_cli_request_options", return_value="/tmp/demo"),
            patch("app.cli.service.cli_runtime", fake_cli_runtime),
            patch("app.cli.main._build_request", fake_build_request),
            patch("app.cli.main._stream_request", fake_stream_request),
        ):
            result = await cli_main._run_command(args)

        self.assertEqual(result, 0)
        self.assertEqual(args.workspace, "/tmp/demo")
        self.assertEqual(captured["build_workspace"], "/tmp/demo")
        self.assertEqual(captured["stream_workspace"], "/tmp/demo")
        self.assertEqual(captured["command_mode"], "run")

    async def test_chat_command_normalizes_workspace_before_stream_request(self):
        args = cli_main.build_argument_parser().parse_args(["chat", "--workspace", "./demo", "--json"])
        captured = {}

        @asynccontextmanager
        async def fake_cli_runtime(*, verbose=False):
            del verbose
            yield object()

        async def fake_build_request(_args, task):
            captured["build_workspace"] = _args.workspace
            captured["task"] = task
            return type(
                "Request",
                (),
                {
                    "session_id": _args.session_id,
                    "user_id": "user-test",
                    "agent_id": None,
                    "agent_mode": "simple",
                    "available_skills": [],
                    "max_loop_count": 50,
                },
            )()

        async def fake_stream_request(request, json_output, stats_output, workspace=None, *, command_mode="chat", session_summary=None):
            del request, json_output, stats_output
            captured["stream_workspace"] = workspace
            captured["command_mode"] = command_mode
            captured["session_summary"] = session_summary
            return 0

        with (
            patch("app.cli.service.validate_cli_runtime_requirements"),
            patch("app.cli.service.validate_cli_request_options", return_value="/tmp/demo"),
            patch("app.cli.service.cli_runtime", fake_cli_runtime),
            patch("app.cli.main._build_request", fake_build_request),
            patch("app.cli.main._stream_request", fake_stream_request),
            patch("app.cli.main._read_chat_prompt", side_effect=["hello", "/exit"]),
        ):
            result = await cli_main._chat_command(args, command_mode="chat")

        self.assertEqual(result, 0)
        self.assertEqual(args.workspace, "/tmp/demo")
        self.assertEqual(captured["build_workspace"], "/tmp/demo")
        self.assertEqual(captured["stream_workspace"], "/tmp/demo")
        self.assertEqual(captured["command_mode"], "chat")
        self.assertIsNone(captured["session_summary"])

    async def test_chat_command_suppresses_prompt_text_in_json_mode(self):
        args = cli_main.build_argument_parser().parse_args(["chat", "--json"])
        prompt_calls = []

        @asynccontextmanager
        async def fake_cli_runtime(*, verbose=False):
            del verbose
            yield object()

        def fake_read_chat_prompt(prompt_text):
            prompt_calls.append(prompt_text)
            return "/exit"

        async def fake_stream_request(
            request,
            json_output,
            stats_output,
            workspace=None,
            *,
            command_mode="chat",
            session_summary=None,
        ):
            del request, json_output, stats_output, workspace, command_mode, session_summary
            return 0

        with (
            patch("app.cli.service.validate_cli_runtime_requirements"),
            patch("app.cli.service.validate_cli_request_options", return_value=None),
            patch("app.cli.service.cli_runtime", fake_cli_runtime),
        ):
            result = await cli_main._chat_command_impl(
                args,
                command_mode="chat",
                build_request_fn=cli_main._build_request,
                stream_request_fn=fake_stream_request,
                read_chat_prompt_fn=fake_read_chat_prompt,
                emit_chat_exit_summary_fn=cli_main._emit_chat_exit_summary,
                print_session_summary_fn=cli_main._print_session_summary,
                chat_command_help=cli_main.CHAT_COMMAND_HELP,
                chat_input_prompt=cli_main.CHAT_INPUT_PROMPT,
            )

        self.assertEqual(result, 0)
        self.assertEqual(prompt_calls, [""])

    async def test_chat_command_goal_command_queues_one_shot_goal_mutation(self):
        args = cli_main.build_argument_parser().parse_args(["chat", "--json"])
        captured = {}

        @asynccontextmanager
        async def fake_cli_runtime(*, verbose=False):
            del verbose
            yield object()

        async def fake_build_request(_args, task):
            captured["goal_objective"] = getattr(_args, "goal_objective", None)
            captured["goal_status"] = getattr(_args, "goal_status", None)
            captured["task"] = task
            return type(
                "Request",
                (),
                {
                    "session_id": _args.session_id,
                    "user_id": "user-test",
                    "agent_id": None,
                    "agent_mode": "simple",
                    "available_skills": [],
                    "max_loop_count": 50,
                },
            )()

        async def fake_stream_request(request, json_output, stats_output, workspace=None, *, command_mode="chat", session_summary=None):
            del request, json_output, stats_output, workspace, command_mode, session_summary
            return 0

        with (
            patch("app.cli.service.validate_cli_runtime_requirements"),
            patch("app.cli.service.validate_cli_request_options", return_value=None),
            patch("app.cli.service.cli_runtime", fake_cli_runtime),
            patch("app.cli.main._build_request", fake_build_request),
            patch("app.cli.main._stream_request", fake_stream_request),
            patch("app.cli.main._read_chat_prompt", side_effect=["/goal set ship the runtime goal contract", "hello", "/exit"]),
        ):
            result = await cli_main._chat_command(args, command_mode="chat")

        self.assertEqual(result, 0)
        self.assertEqual(captured["task"], "hello")
        self.assertEqual(captured["goal_objective"], "ship the runtime goal contract")
        self.assertEqual(captured["goal_status"], "active")
        self.assertIsNone(args.goal_objective)
        self.assertIsNone(args.goal_status)
        self.assertFalse(args.clear_goal)

    async def test_chat_command_fetches_session_summary_inside_cli_runtime(self):
        args = cli_main.build_argument_parser().parse_args(
            ["chat", "--json", "--session-id", "local-000001"]
        )
        runtime_active = {"value": False}
        summary_calls = []

        @asynccontextmanager
        async def fake_cli_runtime(*, verbose=False):
            del verbose
            runtime_active["value"] = True
            try:
                yield object()
            finally:
                runtime_active["value"] = False

        async def fake_get_session_summary(*, session_id, user_id=None):
            summary_calls.append((session_id, user_id, runtime_active["value"]))
            return None

        def fake_read_chat_prompt(_prompt_text):
            return "/exit"

        with (
            patch("app.cli.service.validate_cli_runtime_requirements"),
            patch("app.cli.service.validate_cli_request_options", return_value=None),
            patch("app.cli.service.cli_runtime", fake_cli_runtime),
            patch("app.cli.service.get_session_summary", fake_get_session_summary),
        ):
            result = await cli_main._chat_command_impl(
                args,
                command_mode="chat",
                build_request_fn=cli_main._build_request,
                stream_request_fn=cli_main._stream_request,
                read_chat_prompt_fn=fake_read_chat_prompt,
                emit_chat_exit_summary_fn=cli_main._emit_chat_exit_summary,
                print_session_summary_fn=cli_main._print_session_summary,
                chat_command_help=cli_main.CHAT_COMMAND_HELP,
                chat_input_prompt=cli_main.CHAT_INPUT_PROMPT,
            )

        self.assertEqual(result, 0)
        self.assertEqual(summary_calls, [("local-000001", "default_user", True)])

    def test_resume_chat_prints_continuing_goal_hint(self):
        args = cli_main.build_argument_parser().parse_args(["resume", "session-123"])

        @asynccontextmanager
        async def fake_cli_runtime(*, verbose=False):
            del verbose
            yield object()

        @asynccontextmanager
        async def fake_cli_db_runtime(*, verbose=False):
            del verbose
            yield object()

        async def _run():
            stdout = StringIO()
            stderr = StringIO()
            with (
                patch("app.cli.service.validate_cli_runtime_requirements"),
                patch("app.cli.service.validate_cli_request_options", return_value=None),
                patch("app.cli.service.cli_runtime", fake_cli_runtime),
                patch("app.cli.service.cli_db_runtime", fake_cli_db_runtime),
                patch(
                    "app.cli.service.get_session_summary",
                    return_value={
                        "session_id": "session-123",
                        "title": "resume demo",
                        "message_count": 4,
                        "goal": {
                            "objective": "ship the runtime goal contract",
                            "status": "paused",
                        },
                    },
                ),
                patch("app.cli.main._read_chat_prompt", side_effect=["/exit"]),
                patch("sys.stdout", stdout),
                patch("sys.stderr", stderr),
            ):
                result = await cli_main._resume_command(args)
            return result, stdout.getvalue()

        result, output = asyncio.run(_run())
        self.assertEqual(result, 0)
        self.assertIn("continuing goal: ship the runtime goal contract (paused)", output)

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

    async def test_stream_request_emits_cli_phase_events_in_json_mode(self):
        async def fake_run_request_stream(_request, workspace=None):
            del workspace
            yield {
                "type": "analysis",
                "role": "assistant",
                "content": "先分析一下",
            }
            yield {
                "type": "assistant",
                "role": "assistant",
                "content": "开始回答",
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
        import json

        stdout = StringIO()
        stderr = StringIO()
        with (
            patch("app.cli.service.run_request_stream", fake_run_request_stream),
            patch("sys.stdout", stdout),
            patch("sys.stderr", stderr),
        ):
            result = await _stream_request(
                request,
                json_output=True,
                stats_output=False,
                workspace=None,
                command_mode="chat",
            )

        self.assertEqual(result, 0)
        events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip().startswith("{")]
        self.assertEqual(events[0]["type"], "cli_session")
        self.assertEqual(events[0]["command_mode"], "chat")
        self.assertEqual(events[0]["session_state"], "new")
        self.assertEqual(events[0]["has_prior_messages"], False)
        self.assertEqual(events[0]["prior_message_count"], 0)
        self.assertIsNone(events[0]["session_summary"])
        self.assertEqual(events[1], {"type": "cli_phase", "phase": "planning"})
        self.assertEqual(events[2]["type"], "analysis")
        self.assertEqual(events[3], {"type": "cli_phase", "phase": "assistant_text"})
        self.assertEqual(events[4]["type"], "assistant")

    async def test_stream_request_emits_cli_tool_events_in_json_mode(self):
        async def fake_run_request_stream(_request, workspace=None):
            del workspace
            yield {
                "type": "tool_call",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }
                ],
            }
            yield {
                "type": "tool_result",
                "role": "tool",
                "tool_call_id": "call_1",
                "metadata": {"tool_name": "read_file"},
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
        import json

        stdout = StringIO()
        stderr = StringIO()
        with (
            patch("app.cli.service.run_request_stream", fake_run_request_stream),
            patch("sys.stdout", stdout),
            patch("sys.stderr", stderr),
        ):
            result = await _stream_request(
                request,
                json_output=True,
                stats_output=False,
                workspace=None,
                command_mode="run",
            )

        self.assertEqual(result, 0)
        events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip().startswith("{")]
        cli_tool_events = [event for event in events if event.get("type") == "cli_tool"]
        self.assertEqual(events[0]["type"], "cli_session")
        self.assertEqual(events[0]["command_mode"], "run")
        self.assertEqual(events[0]["session_state"], "new")
        self.assertEqual(events[0]["has_prior_messages"], False)
        self.assertEqual(events[0]["prior_message_count"], 0)
        self.assertEqual(
            cli_tool_events,
            [
                {
                    "type": "cli_tool",
                    "action": "started",
                    "step": 1,
                    "tool_name": "read_file",
                    "tool_call_id": "call_1",
                    "status": "running",
                },
                {
                    "type": "cli_tool",
                    "action": "finished",
                    "step": 1,
                    "tool_name": "read_file",
                    "tool_call_id": "call_1",
                    "status": "completed",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
