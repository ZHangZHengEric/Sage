"""Group all query/write variants of a table family into one RSI split."""
import argparse
import json
import random
from pathlib import Path
from evaluation_datasets.agentbench_db.runtime import ROOT, tasks
from sagents.v2.optimization.dataset import OptimizationDataset


def family(t):
    tables = t['table'] if isinstance(t['table'], list) else [t['table']]
    return '|'.join(sorted(x['table_name'] for x in tables))


def build_dataset():
    groups = sorted({family(t) for t in tasks().values()})
    random.Random(20261023).shuffle(groups)
    n = max(1, len(groups) // 10)
    validation, test = set(groups[:n]), set(groups[n:2*n])
    cases = []
    for identity, t in tasks().items():
        text = ''
        if t.get('evidence'):
            text += 'Evidence about the question: ' + t['evidence'] + '\n'
        if t.get('add_description'):
            text += 'Additional table information about the question: ' + t['add_description'] + '\n'
        text += 'Question: ' + t['description'] + '\n'
        cases.append({'id': identity, 'input': text, 'rubric': 'Official DB answer/table-state comparison; binary success.',
            'reference_answer': json.dumps({'format_version': 'agentbench-db.reference/v1', 'task_id': identity}),
            'environment_context': {'task_id': identity}, 'mode': 'single_turn',
            'split': 'test' if family(t) in test else 'validation' if family(t) in validation else 'training',
            'coverage_tags': [t['type'][0], 'table-family-' + str(groups.index(family(t)))]})
    return OptimizationDataset.model_validate({'name': 'AgentBench DB · standard 300',
        'environment': {'mcp_servers': ['AgentBenchDB']}, 'cases': cases})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'rsi.dataset.json')
    args = parser.parse_args()
    args.output.write_text(build_dataset().model_dump_json(indent=2) + '\n')
