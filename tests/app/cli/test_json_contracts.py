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
            Path(__file__).resolve().parent / "fixtures" / "stream_contract_round_trip.jsonl"
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
        self.assertEqual(events[0]["requested_skills"], ["search_memory"])
        self.assertEqual(events[0]["has_prior_messages"], False)
        self.assertEqual(events[0]["prior_message_count"], 0)
        self.assertIsNone(events[0]["session_summary"])
        self.assertEqual(events[1], {"type": "cli_phase", "phase": "planning"})
        self.assertEqual(events[2]["type"], "analysis")
        self.assertEqual(events[3], {"type": "cli_phase", "phase": "tool"})
        self.assertEqual(events[4]["type"], "cli_tool")
        self.assertEqual(events[4]["action"], "started")
        self.assertEqual(events[7]["type"], "cli_tool")
        self.assertEqual(events[7]["action"], "finished")
        self.assertEqual(events[8], {"type": "cli_phase", "phase": "assistant_text"})
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

        with patch.object(cli_service, "write_cli_config_file", return_value=fake_result):
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
            ["provider", "verify", "--json", "--model", "demo-chat", "--base-url", "https://example.com/v1"]
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
            with patch.object(cli_service, "verify_cli_provider", return_value=fake_result):
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

    def test_agent_config_string_skill_is_not_split_into_characters(self):
        request = cli_service.build_run_request(
            task="inspect repo",
            user_id="user-demo",
            available_skills=["review"],
            agent_config={"availableSkills": "docs"},
        )

        self.assertEqual(request.available_skills, ["docs", "review"])


if __name__ == "__main__":
    unittest.main()
