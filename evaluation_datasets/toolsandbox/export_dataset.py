"""Export offline official base scenarios; hold related task families together."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random

from evaluation_datasets.toolsandbox.runtime import ROOT, scenarios
from sagents.v2.optimization.dataset import OptimizationDataset


def family(name):
    # State-dependency and conversational variants must not leak across splits.
    for marker in ('_multiple_user_turn', '_cellular_off', '_wifi_off',
                   '_location_service_off', '_low_battery_mode',
                   '_insufficient_information', '_no_'):
        name = name.split(marker)[0]
    for suffix in ('_alt', '_implicit', '_canonicalize'):
        name = name.removesuffix(suffix)
    return name


def build_dataset(*, seed=20261023):
    selected = scenarios()
    from tool_sandbox.common.execution_context import DatabaseNamespace, RoleType
    families = sorted({family(name) for name in selected})
    random.Random(seed).shuffle(families)
    count = max(1, len(families) // 10)
    validation, test = set(families[:count]), set(families[count:2 * count])
    cases = []
    for name, s in selected.items():
        messages = s.starting_context.get_database(DatabaseNamespace.SANDBOX,
            get_all_history_snapshots=True, drop_sandbox_message_index=False).to_dicts()
        opening = [m['content'] for m in messages if m['sender'] == RoleType.USER
            and m['recipient'] == RoleType.AGENT
            and (m['visible_to'] is None or RoleType.AGENT in m['visible_to'])][-1]
        user_instructions = [m['content'] for m in messages if m['sender'] == RoleType.SYSTEM
            and m['recipient'] == RoleType.USER]
        cases.append({'id': 'toolsandbox-' + name, 'input': opening,
            'rubric': 'Use official milestone DAG and minefield evaluation. Score is official similarity; '
                'pass requires similarity 1. The user must not infer or reveal hidden evaluation targets.',
            'reference_answer': json.dumps({'format_version': 'toolsandbox.reference/v1', 'scenario': name}),
            'environment_context': {'scenario': name},
            'user_context': json.dumps({'instructions': user_instructions,
                'driver_adaptation': 'Follow the final scenario instructions. The opening is already sent. '
                'When the official user would call end_conversation, return can_continue=false instead. '
                'Do not call tools or claim knowledge outside those instructions.'}, ensure_ascii=False),
            'mode': 'dialogue', 'dialogue_completion': 'user', 'max_turns': 20,
            'split': 'test' if family(name) in test else 'validation' if family(name) in validation else 'training',
            'coverage_tags': [str(category) for category in s.categories]})
    return OptimizationDataset.model_validate({'name': 'ToolSandbox · offline base scenarios',
        'environment': {'mcp_servers': ['ToolSandbox']}, 'cases': cases})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'rsi.dataset.json')
    args = parser.parse_args()
    args.output.write_text(build_dataset().model_dump_json(indent=2) + '\n')


if __name__ == '__main__':
    main()
