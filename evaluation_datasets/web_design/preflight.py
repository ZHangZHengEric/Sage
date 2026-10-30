"""Check the dataset, native receipts, browser and frozen screenshots offline."""
import asyncio
from collections import Counter
import json
from pathlib import Path
import sys

from evaluation_datasets.web_design import workspace
from sagents.v2.optimization.comparison_plugin import ComparisonPreparationRequest
from sagents.v2.optimization.contracts import OptimizationCase


def fixture_observation(files):
    events = []
    for index, (path, content) in enumerate(files.items()):
        common = {'run_id': 'fixture', 'step_id': f'step-{index}'}
        events.extend([
            {**common, 'item_id': f'call-{index}', 'data': {'kind': 'tool_call', 'tool_call_id': str(index),
                'tool_name': 'file_write', 'arguments': {'file_path': path, 'content': content}}},
            {**common, 'item_id': f'result-{index}', 'data': {'kind': 'tool_result', 'tool_call_id': str(index),
                'content': [{'kind': 'json', 'value': {'status': 'success', 'file_path': path, 'mode': 'overwrite'}}]}}])
    return {'state': 'completed', 'output': 'Website ready.', 'evidence': {'final_items': events}}


async def main():
    root = Path(__file__).parent
    data = json.loads((root / 'rsi.dataset.json').read_text())
    assert Counter(c['split'] for c in data['cases']) == {'training': 20, 'validation': 10, 'test': 10}
    assert len({c['input'] for c in data['cases']}) == 40
    for case in data['cases']:
        OptimizationCase.model_validate(case)
    files = {'index.html': '<!doctype html><title>Preflight</title><style>body{margin:0;background:#102532;color:#ffe8bc;font:40px serif}section{height:1200px;padding:30px}</style><section>Website rendering fixture <a href="about.html">About</a></section><section>Second section</section>',
        'about.html': '<!doctype html><title>About</title><h1>Another page</h1>'}
    files['index.html'] += """<button type="button" onclick="document.body.style.background='#884422'">Change color</button>"""
    observation = fixture_observation(files)
    assert workspace.replay({'observation': observation})[0] == files
    directory = (root / '.runtime' / 'preflight').resolve()
    from sagents.v2.optimization.evaluation_plugin import PythonEvaluationPlugin
    from sagents.v2.optimization.scoring import ScorerDescriptor
    import hashlib
    source = root / 'scorer.py'
    plugin = PythonEvaluationPlugin(path=source, source_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
        descriptor=ScorerDescriptor(id='web-preflight', name='Web Design', version='1'), python_executable=sys.executable)
    await plugin.validate()
    result = await plugin.prepare(ComparisonPreparationRequest.model_validate({'capture_id': 'preflight',
        'artifact_directory': str(directory), 'goal': (root / 'goal.txt').read_text(),
        'case': data['cases'][0], 'observation': observation}))
    result.verify_files()
    captures = result.artifact['captures']
    assert len(captures) == 9
    assert {c['viewport'] for c in captures} == {'desktop', 'tablet', 'mobile'}
    interactions = [c for c in captures if c.get('kind') == 'interaction']
    assert len(interactions) == 3
    assert all(c['actions'][0]['state_changed'] for c in interactions)
    from sagents.v2.optimization.evaluation_plugin import evidence_content, EvaluationResult
    from sagents.v2.contracts.items import ImageBlock
    content = evidence_content('preflight', {}, EvaluationResult, [('A', result)])
    assert len([block for block in content if isinstance(block, ImageBlock)]) == 9
    assert len(result.artifact['presentation']['images']) == 9
    print(json.dumps({'ready': True, 'training': 20, 'dev': 10, 'test': 10,
        'viewports': 3, 'fixture_pages': 2, 'captures': len(result.artifact['captures']), 'judge_images': 9, 'interaction_boards': 3,
        'artifacts': str(directory), 'isolated_plugin': True, 'native_file_tools': True, 'model_calls': 0}))


if __name__ == '__main__':
    asyncio.run(main())
