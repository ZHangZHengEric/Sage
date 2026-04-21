#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli.main import _collect_event_tool_names, _empty_stats, _record_stats_event


class TestStatsToolDetection(unittest.TestCase):
    def test_collects_tool_name_from_skill_tag(self):
        event = {
            "role": "assistant",
            "content": "<skill>\nsearch_memory\n</skill>\n<skill_input>\n{\"query\": \"foo\"}\n</skill_input>",
        }
        names = _collect_event_tool_names(event)
        self.assertEqual(names, ["search_memory"])

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


if __name__ == "__main__":
    unittest.main()
