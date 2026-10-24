"""Export the committed, deterministic subset using official split membership."""
import argparse
import json
from pathlib import Path
from evaluation_datasets.alfworld.runtime import ROOT, tasks
from sagents.v2.optimization.dataset import OptimizationDataset


def build_dataset():
    splits = {'train': 'training', 'valid_seen': 'validation', 'valid_unseen': 'test',
        'dev': 'validation', 'test': 'test'}
    cases = []
    for t in tasks().values():
        cases.append({'id': t['id'], 'input': t['input'] + '\nUse observe first, then step to act in the world.',
            'rubric': 'Complete the task in the official environment within 200 actions.',
            'reference_answer': json.dumps({'format_version': 'alfworld.reference/v1', 'task_id': t['id']}),
            'environment_context': {'task_id': t['id']}, 'mode': 'single_turn',
            'split': splits[t.get('source_split', t.get('fold'))],
            'coverage_tags': [t.get('task_type', t.get('task', 'world'))]})
    return OptimizationDataset.model_validate({'name': 'ALFWorld · pinned RSI subset',
        'environment': {'mcp_servers': ['ALFWorld'], 'terminal_on_done': True}, 'cases': cases})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'rsi.dataset.json')
    args = parser.parse_args()
    args.output.write_text(build_dataset().model_dump_json(indent=2) + '\n')
