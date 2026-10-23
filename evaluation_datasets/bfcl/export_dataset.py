"""Convert official multi-turn tasks; keep related category variants together."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from evaluation_datasets.bfcl.runtime import ROOT, CATEGORIES, tasks
from sagents.v2.optimization.dataset import OptimizationDataset


def build_dataset(*, categories=('base',), seed=20261023):
    if not categories or not set(categories) <= set(CATEGORIES):
        raise ValueError('Supported categories: base, miss_param, long_context')
    # Variant i in every category describes the same task family. Never split it.
    families = sorted({t['id'].rsplit('_', 1)[1] for t in tasks().values()}, key=int)
    random.Random(seed).shuffle(families)
    validation, test = set(families[:20]), set(families[20:40])
    cases = []
    for category in categories:
        for t in tasks().values():
            if t['id'].rsplit('_', 1)[0] != 'multi_turn_' + category:
                continue
            script = ['\n'.join(m['content'] for m in turn if m['role'] == 'user') for turn in t['question']]
            family = t['id'].rsplit('_', 1)[1]
            cases.append({'id': 'bfcl-' + t['id'], 'input': script[0],
                'rubric': 'Official BFCL per-turn state and cumulative execution-response checks; binary success.',
                'reference_answer': json.dumps({'format_version': 'bfcl.reference/v1', 'task_id': t['id']}),
                'environment_context': {'task_id': t['id']},
                'user_context': json.dumps({'protocol': 'fixed-user-script/v1', 'messages': script,
                    'instructions': 'The opening messages[0] was already sent. After each target response, '
                    'send the next message verbatim, exactly once, in order. Do not add answers, hints, '
                    'or extra turns. After the final message return can_continue=false.'}),
                'mode': 'dialogue', 'dialogue_completion': 'user', 'max_turns': len(script),
                'split': 'test' if family in test else 'validation' if family in validation else 'training',
                'coverage_tags': ['bfcl-' + category, 'family-' + family]})
    return OptimizationDataset.model_validate({'name': 'BFCL V4 multi-turn · ' + ','.join(categories),
        'environment': {'mcp_servers': ['BFCL']}, 'cases': cases})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--categories', nargs='+', choices=CATEGORIES, default=['base'])
    parser.add_argument('--output', type=Path, default=ROOT / 'rsi.dataset.json')
    args = parser.parse_args()
    args.output.write_text(build_dataset(categories=tuple(args.categories)).model_dump_json(indent=2) + '\n')


if __name__ == '__main__':
    main()
