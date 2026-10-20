"""Print the public settings tool catalog without starting an App or Run."""

from __future__ import annotations

import argparse
import json

from sagents.v2.tool import builtin_tool_definitions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent-mode",
        choices=("all", "simple", "team", "fibre", "flow"),
        default="all",
    )
    parser.add_argument("--language", default=None)
    options = parser.parse_args()
    definitions = builtin_tool_definitions(
        agent_mode=options.agent_mode, language=options.language
    )
    print(
        json.dumps(
            [
                {
                    "name": value.name,
                    "description": value.description,
                    "inputSchema": value.input_schema,
                }
                for value in definitions
            ],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
