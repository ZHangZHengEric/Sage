#!/usr/bin/env python3
import asyncio
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import app.cli.main as cli_main
import app.cli.service as cli_service


class TestCliJsonContracts(unittest.TestCase):
    def test_stream_contract_fixture_uses_supported_event_types(self):
        fixture_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "stream_contract_round_trip.jsonl"
        )
        events = [
            json.loads(line)
            for line in fixture_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        self.assertEqual(events[0]["type"], "cli_session")
        self.assertEqual(events[0]["command_mode"], "run")
        self.assertEqual(events[0]["session_state"], "new")
        self.assertEqual(events[0]["session_id"], "session-demo")
        self.assertEqual(events[0]["workspace_source"], "explicit")
        self.assertEqual(events[0]["agent_name"], "Demo Agent")
        self.assertEqual(events[0]["requested_skills"], ["search_memory"])
        self.assertEqual(events[0]["has_prior_messages"], False)
        self.assertEqual(events[0]["prior_message_count"], 0)
        self.assertIsNone(events[0]["session_summary"])
        self.assertEqual(
            events[0]["goal"],
            {"objective": "Ship the terminal goal MVP", "status": "active"},
        )
        self.assertEqual(events[1], {"type": "cli_phase", "phase": "planning"})
        self.assertEqual(events[2]["type"], "analysis")
        self.assertEqual(events[3], {"type": "cli_phase", "phase": "tool"})
        self.assertEqual(events[4]["type"], "cli_tool")
        self.assertEqual(events[4]["action"], "started")
        self.assertEqual(events[7]["type"], "cli_tool")
        self.assertEqual(events[7]["action"], "finished")
        self.assertEqual(events[8], {"type": "cli_phase", "phase": "assistant_text"})
        session_events = [event for event in events if event["type"] == "cli_session"]
        self.assertEqual(session_events[-1]["type"], "cli_session")
        self.assertEqual(session_events[-1]["session_state"], "existing")
        self.assertEqual(session_events[-1]["prior_message_count"], 2)
        self.assertEqual(events[-1]["type"], "cli_stats")
        self.assertEqual(events[-1]["tool_steps"][0]["tool_name"], "read_file")
        self.assertEqual(events[-1]["phase_timings"][0]["phase"], "planning")

    def test_doctor_command_json_outputs_structured_payload(self):
        args = cli_main.build_argument_parser().parse_args(["doctor", "--json"])
        fake_info = {
            "status": "ok",
            "env_file": "/tmp/.sage_env",
            "dependencies": {"dotenv": True},
        }

        with patch.object(cli_service, "collect_doctor_info", return_value=fake_info):
            with patch.object(cli_service, "probe_default_provider") as probe:
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = asyncio.run(cli_main._doctor_command(args))

        self.assertEqual(exit_code, 0)
        self.assertFalse(probe.called)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["env_file"], "/tmp/.sage_env")
        self.assertEqual(payload["dependencies"]["dotenv"], True)

    def test_config_init_command_json_outputs_result(self):
        args = cli_main.build_argument_parser().parse_args(
            ["config", "init", "--json", "--path", "/tmp/demo.env", "--force"]
        )
        fake_result = {
            "path": "/tmp/demo.env",
            "template": "minimal-local",
            "overwritten": True,
            "next_steps": ["Run `sage doctor`."],
        }

        with patch.object(
            cli_service, "write_cli_config_file", return_value=fake_result
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli_main._config_init_command(args)

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["path"], "/tmp/demo.env")
        self.assertEqual(payload["template"], "minimal-local")
        self.assertEqual(payload["overwritten"], True)
        self.assertEqual(payload["next_steps"], ["Run `sage doctor`."])

    def test_provider_verify_command_json_outputs_verification_payload(self):
        args = cli_main.build_argument_parser().parse_args(
            [
                "provider",
                "verify",
                "--json",
                "--model",
                "demo-chat",
                "--base-url",
                "https://example.com/v1",
            ]
        )
        fake_result = {
            "status": "ok",
            "message": "Provider verification succeeded",
            "sources": {"base_url": "cli", "model": "cli"},
            "provider": {
                "id": "",
                "name": "demo",
                "model": "demo-chat",
                "base_url": "https://example.com/v1",
                "is_default": False,
                "api_key_preview": "(hidden)",
            },
        }

        async def _run():
            with patch.object(
                cli_service, "verify_cli_provider", return_value=fake_result
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = await cli_main._provider_command(args)
            return exit_code, stdout.getvalue()

        exit_code, output = asyncio.run(_run())
        self.assertEqual(exit_code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["message"], "Provider verification succeeded")
        self.assertEqual(payload["provider"]["model"], "demo-chat")
        self.assertEqual(payload["sources"]["base_url"], "cli")

    def test_agent_config_file_populates_cli_request(self):
        config = {
            "name": "Coding Agent",
            "agentMode": "simple",
            "memoryType": "session",
            "maxLoopCount": 80,
            "deepThinking": True,
            "moreSuggest": True,
            "forceSummary": True,
            "availableSubAgentIds": ["agent-reviewer"],
            "availableTools": ["grep", "file_read"],
            "availableSkills": ["docs"],
            "systemContext": {"role": "coding"},
            "systemPrefix": "You are a coding agent.",
            "availableWorkflows": {"review": ["inspect", "verify"]},
            "llmConfig": {"model": "demo-model", "maxTokens": 2048, "temperature": 0.1},
            "contextBudgetConfig": {"recent_turns": 4},
            "extraMcpConfig": {"demo": {"url": "http://localhost:8000/mcp"}},
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "agent.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            loaded = cli_service.load_agent_config_file(str(config_path))
            request = cli_service.build_run_request(
                task="inspect repo",
                user_id="user-demo",
                agent_config=loaded,
            )

        self.assertEqual(request.agent_name, "Coding Agent")
        self.assertEqual(request.agent_mode, "simple")
        self.assertEqual(request.max_loop_count, 80)
        self.assertEqual(request.available_tools, ["grep", "file_read"])
        self.assertEqual(request.available_skills, ["docs"])
        self.assertEqual(request.available_sub_agent_ids, ["agent-reviewer"])
        self.assertEqual(request.more_suggest, True)
        self.assertEqual(request.force_summary, True)
        self.assertEqual(request.system_context, {"role": "coding"})
        self.assertEqual(request.system_prefix, "You are a coding agent.")
        self.assertEqual(request.available_workflows, {"review": ["inspect", "verify"]})
        self.assertEqual(request.llm_model_config["model"], "demo-model")
        self.assertEqual(request.llm_model_config["max_tokens"], 2048)
        self.assertEqual(request.context_budget_config, {"recent_turns": 4})
        self.assertEqual(
            request.extra_mcp_config,
            {"demo": {"url": "http://localhost:8000/mcp"}},
        )
        self.assertEqual(request.memory_type, "session")
        self.assertTrue(
            request.messages[0].content.startswith(
                "<enable_deep_thinking>true</enable_deep_thinking>"
            )
        )

    def test_agent_config_coding_alias_loads_bundled_preset(self):
        loaded = cli_service.load_agent_config_file(" coding ")

        self.assertEqual(loaded["name"], "Sage Coding Agent")
        self.assertIn("grep", loaded["availableTools"])
        self.assertEqual(loaded["systemContext"], {})
        prompt = loaded["systemPrefix"]
        self.assertIn("AGENTS.md", prompt)
        self.assertIn("git log", prompt)
        self.assertIn("file_update", prompt)
        self.assertIn("Frontend and TUI work", prompt)
        self.assertIn("line numbers", prompt)
        self.assertNotIn("codingAgentPrompt", json.dumps(loaded))

    def test_bundled_coding_agent_config_requires_workspace(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.validate_agent_config_workspace(
                agent_config="coding",
                workspace=None,
            )

        self.assertIn("requires `--workspace`", str(context.exception))

    def test_custom_agent_config_does_not_require_workspace(self):
        cli_service.validate_agent_config_workspace(
            agent_config="/tmp/custom-agent-config.json",
            workspace=None,
        )

    def test_agent_config_coding_preset_builds_request(self):
        loaded = cli_service.load_agent_config_file("coding")
        request = cli_service.build_run_request(
            task="inspect repo",
            user_id="user-demo",
            agent_config=loaded,
        )

        self.assertEqual(request.agent_name, "Sage Coding Agent")
        self.assertEqual(request.agent_mode, "simple")
        self.assertEqual(request.max_loop_count, 30)
        self.assertIn("grep", request.available_tools)
        self.assertEqual(request.llm_model_config["max_tokens"], 4096)
        self.assertFalse(
            request.messages[0].content.startswith("<enable_deep_thinking>")
        )

    def test_agent_config_blank_path_is_rejected(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.load_agent_config_file("   ")

        self.assertEqual(str(context.exception), "Agent config path is empty.")

    def test_agent_config_non_object_is_rejected(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.build_run_request(
                task="inspect repo",
                user_id="user-demo",
                agent_config=["not", "an", "object"],
            )

        self.assertIn("JSON object", str(context.exception))

    def test_agent_config_read_errors_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "agent.json"
            config_path.write_text("{}", encoding="utf-8")
            with patch("builtins.open", side_effect=OSError("permission denied")):
                with self.assertRaises(cli_service.CLIError) as context:
                    cli_service.load_agent_config_file(str(config_path))

        self.assertIn("Failed to read agent config file", str(context.exception))

    def test_agent_id_and_agent_config_are_mutually_exclusive(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.validate_agent_selection_options(
                agent_id="agent_demo",
                agent_config="coding",
            )

        self.assertIn("not both", str(context.exception))

    def test_blank_agent_id_is_rejected(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.validate_agent_selection_options(
                agent_id="   ",
                agent_config=None,
            )

        self.assertIn("Agent id is empty", str(context.exception))

    def test_build_request_normalizes_agent_id(self):
        request = cli_service.build_run_request(
            task="inspect repo",
            user_id="user-demo",
            agent_id="  agent_demo  ",
        )

        self.assertEqual(request.agent_id, "agent_demo")

    def test_build_request_rejects_blank_agent_id(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.build_run_request(
                task="inspect repo",
                user_id="user-demo",
                agent_id="   ",
            )

        self.assertIn("Agent id is empty", str(context.exception))

    def test_build_request_rejects_agent_id_with_agent_config(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.build_run_request(
                task="inspect repo",
                user_id="user-demo",
                agent_id="agent_demo",
                agent_config={"name": "Coding Agent"},
            )

        self.assertIn("not both", str(context.exception))

    def test_run_command_rejects_agent_id_and_agent_config_before_runtime(self):
        with patch(
            "app.cli.service.validate_cli_runtime_requirements"
        ) as runtime_check:
            stderr = io.StringIO()
            with patch("sys.stderr", stderr):
                exit_code = cli_main.main(
                    [
                        "run",
                        "--agent-id",
                        "agent_demo",
                        "--agent-config",
                        "coding",
                        "inspect repo",
                    ]
                )

        self.assertEqual(exit_code, 1)
        runtime_check.assert_not_called()
        self.assertIn("Use either `--agent-id` or `--agent-config`", stderr.getvalue())

    def test_run_command_rejects_coding_agent_config_without_workspace_before_runtime(
        self,
    ):
        with patch(
            "app.cli.service.validate_cli_runtime_requirements"
        ) as runtime_check:
            stderr = io.StringIO()
            with patch("sys.stderr", stderr):
                exit_code = cli_main.main(
                    [
                        "run",
                        "--agent-config",
                        "coding",
                        "inspect repo",
                    ]
                )

        self.assertEqual(exit_code, 1)
        runtime_check.assert_not_called()
        self.assertIn("requires `--workspace`", stderr.getvalue())

    def test_run_command_loads_agent_config_before_runtime(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            missing_config = Path(tmp_dir) / "does-not-exist-agent-config.json"
            with patch(
                "app.cli.service.validate_cli_runtime_requirements"
            ) as runtime_check:
                stderr = io.StringIO()
                with patch("sys.stderr", stderr):
                    exit_code = cli_main.main(
                        [
                            "run",
                            "--agent-config",
                            str(missing_config),
                            "inspect repo",
                        ]
                    )

        self.assertEqual(exit_code, 1)
        runtime_check.assert_not_called()
        self.assertIn("Agent config file does not exist", stderr.getvalue())

    def test_agent_config_file_drops_blank_llm_values(self):
        request = cli_service.build_run_request(
            task="inspect repo",
            user_id="user-demo",
            agent_config={
                "llmConfig": {
                    "model": "",
                    "baseUrl": "",
                    "apiKey": None,
                    "temperature": 0.1,
                },
            },
        )

        self.assertEqual(request.llm_model_config, {"temperature": 0.1})

    def test_agent_config_invalid_llm_config_is_rejected(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.build_run_request(
                task="inspect repo",
                user_id="user-demo",
                agent_config={"llmConfig": "demo-model"},
            )

        self.assertIn("llmConfig", str(context.exception))

    def test_agent_config_invalid_object_field_is_rejected(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.build_run_request(
                task="inspect repo",
                user_id="user-demo",
                agent_config={"systemContext": ["not", "an", "object"]},
            )

        self.assertIn("systemContext", str(context.exception))

    def test_agent_config_invalid_workflow_items_are_rejected(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.build_run_request(
                task="inspect repo",
                user_id="user-demo",
                agent_config={"availableWorkflows": {"review": ["inspect", 123]}},
            )

        self.assertIn("availableWorkflows.review", str(context.exception))

    def test_agent_config_invalid_extra_mcp_items_are_rejected(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.build_run_request(
                task="inspect repo",
                user_id="user-demo",
                agent_config={"extraMcpConfig": {"demo": "http://localhost:8000/mcp"}},
            )

        self.assertIn("extraMcpConfig.demo", str(context.exception))

    def test_agent_config_invalid_string_field_is_rejected(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.build_run_request(
                task="inspect repo",
                user_id="user-demo",
                agent_config={"systemPrefix": ["not", "a", "string"]},
            )

        self.assertIn("systemPrefix", str(context.exception))

    def test_agent_config_invalid_agent_mode_is_rejected(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.build_run_request(
                task="inspect repo",
                user_id="user-demo",
                agent_config={"agentMode": "parallel"},
            )

        self.assertIn("agentMode", str(context.exception))

    def test_agent_config_agent_mode_is_normalized(self):
        request = cli_service.build_run_request(
            task="inspect repo",
            user_id="user-demo",
            agent_config={"agentMode": " Multi "},
        )

        self.assertEqual(request.agent_mode, "multi")

    def test_cli_agent_mode_overrides_config_and_is_normalized(self):
        request = cli_service.build_run_request(
            task="inspect repo",
            user_id="user-demo",
            agent_mode=" Fibre ",
            agent_config={"agentMode": "multi"},
        )

        self.assertEqual(request.agent_mode, "fibre")

    def test_cli_invalid_agent_mode_is_rejected(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.build_run_request(
                task="inspect repo",
                user_id="user-demo",
                agent_mode="parallel",
            )

        self.assertIn("Invalid agent mode", str(context.exception))

    def test_agent_config_bool_loop_count_is_rejected(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.build_run_request(
                task="inspect repo",
                user_id="user-demo",
                agent_config={"maxLoopCount": True},
            )

        self.assertIn("maxLoopCount", str(context.exception))

    def test_cli_bool_loop_count_is_rejected(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.build_run_request(
                task="inspect repo",
                user_id="user-demo",
                max_loop_count=True,
            )

        self.assertIn("Invalid max loop count", str(context.exception))

    def test_cli_non_integer_loop_count_is_rejected(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.build_run_request(
                task="inspect repo",
                user_id="user-demo",
                max_loop_count=3.5,
            )

        self.assertIn("Invalid max loop count", str(context.exception))

    def test_agent_config_non_integer_loop_count_is_rejected(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.build_run_request(
                task="inspect repo",
                user_id="user-demo",
                agent_config={"maxLoopCount": 3.5},
            )

        self.assertIn("maxLoopCount", str(context.exception))

    def test_agent_config_invalid_bool_field_is_rejected(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.build_run_request(
                task="inspect repo",
                user_id="user-demo",
                agent_config={"deepThinking": "true"},
            )

        self.assertIn("deepThinking", str(context.exception))

    def test_agent_config_invalid_custom_sub_agents_are_rejected(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.build_run_request(
                task="inspect repo",
                user_id="user-demo",
                agent_config={"customSubAgents": ["not-an-object"]},
            )

        self.assertIn("customSubAgents", str(context.exception))

    def test_agent_config_custom_sub_agents_require_name(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.build_run_request(
                task="inspect repo",
                user_id="user-demo",
                agent_config={"customSubAgents": [{"agentId": "reviewer"}]},
            )

        self.assertIn("customSubAgents[0].name", str(context.exception))

    def test_agent_config_custom_sub_agents_normalize_aliases(self):
        request = cli_service.build_run_request(
            task="inspect repo",
            user_id="user-demo",
            agent_config={
                "customSubAgents": [
                    {
                        "agentId": "reviewer",
                        "name": "Reviewer",
                        "systemPrompt": "Review changes.",
                        "description": "Reviews diffs",
                        "availableTools": ["grep", "file_read"],
                        "availableSkills": "docs",
                        "availableWorkflows": {"review": ["inspect"]},
                        "systemContext": {"role": "review"},
                    }
                ]
            },
        )

        self.assertEqual(len(request.custom_sub_agents), 1)
        sub_agent = request.custom_sub_agents[0]
        self.assertEqual(sub_agent.agent_id, "reviewer")
        self.assertEqual(sub_agent.name, "Reviewer")
        self.assertEqual(sub_agent.system_prompt, "Review changes.")
        self.assertEqual(sub_agent.description, "Reviews diffs")
        self.assertEqual(sub_agent.available_tools, ["grep", "file_read"])
        self.assertEqual(sub_agent.available_skills, ["docs"])
        self.assertEqual(sub_agent.available_workflows, {"review": ["inspect"]})
        self.assertEqual(sub_agent.system_context, {"role": "review"})

    def test_agent_config_string_skill_is_not_split_into_characters(self):
        request = cli_service.build_run_request(
            task="inspect repo",
            user_id="user-demo",
            available_skills=["review"],
            agent_config={"availableSkills": "docs"},
        )

        self.assertEqual(request.available_skills, ["docs", "review"])

    def test_agent_config_string_list_fields_accept_single_string(self):
        request = cli_service.build_run_request(
            task="inspect repo",
            user_id="user-demo",
            agent_config={
                "availableTools": " grep ",
                "availableKnowledgeBases": "kb-demo",
                "availableSubAgentIds": "agent-reviewer",
            },
        )

        self.assertEqual(request.available_tools, ["grep"])
        self.assertEqual(request.available_knowledge_bases, ["kb-demo"])
        self.assertEqual(request.available_sub_agent_ids, ["agent-reviewer"])

    def test_agent_config_string_list_fields_reject_invalid_items(self):
        with self.assertRaises(cli_service.CLIError) as context:
            cli_service.build_run_request(
                task="inspect repo",
                user_id="user-demo",
                agent_config={"availableTools": ["grep", 123]},
            )

        self.assertIn("availableTools", str(context.exception))


if __name__ == "__main__":
    unittest.main()
