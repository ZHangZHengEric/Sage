#!/usr/bin/env python3
import asyncio
import io
import json
from pathlib import Path
import unittest
from contextlib import redirect_stdout
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

        self.assertEqual(events[0], {"type": "cli_phase", "phase": "planning"})
        self.assertEqual(events[1]["type"], "analysis")
        self.assertEqual(events[2], {"type": "cli_phase", "phase": "tool"})
        self.assertEqual(events[3]["type"], "cli_tool")
        self.assertEqual(events[3]["action"], "started")
        self.assertEqual(events[6]["type"], "cli_tool")
        self.assertEqual(events[6]["action"], "finished")
        self.assertEqual(events[7], {"type": "cli_phase", "phase": "assistant_text"})
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


if __name__ == "__main__":
    unittest.main()
