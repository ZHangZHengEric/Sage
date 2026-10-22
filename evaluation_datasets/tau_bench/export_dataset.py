"""Convert pinned official tasks to the ordinary Sage RSI dataset contract."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random

from sagents.v2.optimization.dataset import OptimizationDataset

ROOT = Path(__file__).resolve().parent


def checked_json(relative):
    manifest = json.loads((ROOT / 'upstream.json').read_text())
    raw = (ROOT / relative).read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest['files'][relative]:
        raise ValueError(f'official dataset changed: {relative}')
    return json.loads(raw)


def build_dataset(*, dev_count=12, seed=20261021):
    tasks = checked_json('data/tau2/domains/retail/tasks.json')
    splits = checked_json('data/tau2/domains/retail/split_tasks.json')
    if not 1 <= dev_count < len(splits['train']):
        raise ValueError('dev_count must leave both training and validation tasks')
    train = list(splits['train'])
    random.Random(seed).shuffle(train)
    dev = set(train[-dev_count:])
    # Validation is drawn only from official train. Official test stays untouched.
    by_id = {str(task['id']): task for task in tasks}
    cases = []
    for task_id in [*train, *splits['test']]:
        task_id = str(task_id)
        task = by_id[task_id]
        scenario = task['user_scenario']
        instructions = scenario['instructions']
        if not isinstance(instructions, dict) or not isinstance(instructions.get('reason_for_call'), str):
            raise ValueError(f'task {task_id} has no supported question')
        reference = {
            'format_version': 'tau2.retail.reference/v1',
            'task_id': task_id,
            'initial_state': task.get('initial_state'),
            'evaluation_criteria': task['evaluation_criteria'],
        }
        cases.append({
            'id': f'tau-{task_id}',
            'input': instructions['reason_for_call'],
            'user_context': json.dumps(scenario, ensure_ascii=False),
            'environment_context': {'initial_state': task.get('initial_state')},
            'reference_answer': json.dumps(reference, ensure_ascii=False),
            'rubric': 'Use the official task reward_basis and evaluation_criteria. '
                'Reference actions describe expected outcomes; they do not replace user authorization.',
            'split': 'test' if task_id in splits['test'] else 'validation' if task_id in dev else 'training',
            'mode': 'dialogue',
            'max_turns': 20,
            'coverage_tags': ['official-retail-task'],
        })
    return OptimizationDataset.model_validate({
        'name': 'τ-bench retail · standard RSI dataset',
        'environment': {'mcp_servers': ['TauRetail']},
        'cases': cases,
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dev-count', type=int, default=12)
    parser.add_argument('--seed', type=int, default=20261021)
    parser.add_argument('--output', type=Path, default=ROOT / 'rsi.dataset.json')
    args = parser.parse_args()
    dataset = build_dataset(dev_count=args.dev_count, seed=args.seed)
    args.output.write_text(dataset.model_dump_json(indent=2) + '\n')


if __name__ == '__main__':
    main()
