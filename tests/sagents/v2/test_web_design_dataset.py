"""Fixed tasks, native file replay, square screenshots and technical baseline."""
from collections import Counter
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
import pytest

from evaluation_datasets.web_design import workspace
from evaluation_datasets.web_design.preflight import fixture_observation
from evaluation_datasets.web_design.rendering import pages, sheet


def test_fixed_disjoint_tasks_and_technical_baseline():
    root = Path('evaluation_datasets/web_design')
    data = json.loads((root/'rsi.dataset.json').read_text())
    assert Counter(c['split'] for c in data['cases']) == {'training': 20, 'validation': 10, 'test': 10}
    assert len({c['input'] for c in data['cases']}) == len({c['id'] for c in data['cases']}) == 40
    families = Counter(tag for c in data['cases'] for tag in c['coverage_tags'])
    assert len(families) == 10 and set(families.values()) == {4}
    assert all(len({tag for c in data['cases'] if c['split'] == split
                    for tag in c['coverage_tags']}) == 10 for split in ('training', 'validation', 'test'))
    assert all(len(c['input']) < 300 for c in data['cases'])
    assert all(len(c['input'].split('. ')) >= 2 for c in data['cases'])
    assert 'environment' not in data
    from sagents.v2.agent.management import AgentPackageBundle
    baseline = AgentPackageBundle.model_validate_json((root/'baseline.package.json').read_text())
    agent = next(iter(baseline.manifest.agents.values()))
    assert agent.instructions.inline == (root/'baseline.system.txt').read_text().strip()
    assert 'index.html' in agent.instructions.inline and not agent.skills
    assert set(agent.tools) == set(workspace.TOOLS)
    assert not any(word in agent.instructions.inline.lower() for word in ('beautiful', 'artistic', 'typography', 'color'))


def test_full_experiment_optimizes_skills_with_equal_repeats():
    settings = json.loads(Path('evaluation_datasets/web_design/experiment.settings.json').read_text())
    assert settings['optimization_scope'] == ['instructions', 'skills']
    assert settings['max_skill_count'] == 5
    assert settings['evaluation_repeats'] == settings['human_test_repeats'] == 2
    assert settings['max_concurrency'] == 8 and settings['rounds'] == 5


def test_native_receipt_replay_uses_successful_writes_not_final_paths():
    files = {'index.html': '<h1>First</h1>', 'style.css': 'h1{color:red}',
        'README.md':'# Delivery notes', 'helper.py':'raise RuntimeError("Never execute project assets")'}
    observation = fixture_observation(files)
    observation['output'] = '/private/arbitrary/index.html'
    recovered, trace = workspace.replay({'observation': observation})
    assert recovered == files
    assert trace[0]['arguments']['content_sha256']
    observation['evidence']['final_items'][1]['data']['content'][0]['value']['file_path'] = 'different.html'
    with pytest.raises(ValueError, match='receipt'):
        workspace.replay({'observation': observation})


def test_absolute_paths_require_run_bound_host_workspace_mapping():
    files = {'index.html':'<h1>Native absolute path</h1>', 'assets/style.css':'h1{color:red}'}
    observation = fixture_observation(files)
    root = '/tmp/host-owned-case'
    for item in observation['evidence']['final_items']:
        data = item['data']
        if data['kind'] == 'tool_call':
            data['arguments']['file_path'] = root+'/'+data['arguments']['file_path']
        elif data['kind'] == 'tool_result':
            value = data['content'][0]['value']
            value['file_path'] = root+'/'+value['file_path']
    with pytest.raises(ValueError,match='attested workspace'):
        workspace.replay({'observation':observation})
    observation['evidence'].update(run_id='native-case',workspace_attestation={
        'protocol':'sage.rsi.workspace/v1','run_id':'native-case','roots':[root]})
    assert workspace.replay({'observation':observation})[0] == files
    observation['evidence']['workspace_attestation']['run_id'] = 'other-case'
    with pytest.raises(ValueError,match='Unbound'):
        workspace.replay({'observation':observation})
    assert workspace.file_path('C:\\case\\index.html',workspace_roots=('C:/case',)) == 'index.html'
    for value in ('/outside/index.html', root+'/../outside.html'):
        with pytest.raises(ValueError):
            workspace.file_path(value,workspace_roots=(root,))


def test_append_update_and_rejected_mutations():
    from sagents.v2.tool.official.filesystem import _apply_update_operations
    observation = fixture_observation({'index.html': 'Original'})
    def add(name, args, value, step):
        common = {'run_id':'fixture','step_id':step}
        observation['evidence']['final_items'].extend([
            {**common, 'item_id':step+'c', 'data':{'kind':'tool_call','tool_call_id':step,'tool_name':name,'arguments':args}},
            {**common, 'item_id':step+'r', 'data':{'kind':'tool_result','tool_call_id':step,'content':[{'kind':'json','value':value}]}}])
    add('file_write', {'file_path':'index.html','content':' page','mode':'append'},
        {'status':'success','file_path':'index.html','mode':'append'}, 'append')
    operations = [{'update_mode':'search_replace','search_pattern':'Original','replacement':'Final'}]
    content, summaries, replacements = _apply_update_operations('Original page', operations)
    add('file_update', {'file_path':'index.html','operations':operations},
        {'status':'success','file_path':'index.html','operations':summaries,'replacements':replacements}, 'update')
    assert workspace.replay({'observation':observation})[0]['index.html'] == content
    observation['evidence']['final_items'][-1]['data']['error'] = {'code':'tool.arguments_invalid'}
    assert workspace.replay({'observation':observation})[0]['index.html'] == 'Original page'


def test_paths_and_ambiguous_parallel_mutations_fail():
    for path in ('../index.html', '/host/index.html', 'a/../../x.html', 'a\\b.html', '.'):
        with pytest.raises(ValueError):
            workspace.file_path(path)
    assert workspace.file_path('/workspace/index.html') == 'index.html'
    observation = fixture_observation({'index.html':'one'})
    second = fixture_observation({'index.html':'two'})['evidence']['final_items']
    for item in second:
        item['item_id'] += '-second'
        item['data']['tool_call_id'] += '-second'
    observation['evidence']['final_items'].extend(second)
    with pytest.raises(ValueError, match='Concurrent'):
        workspace.replay({'observation':observation})


def test_terminal_host_files_resolve_overlapping_native_writes_without_guessing(tmp_path):
    from sagents.v2.optimization.contracts import OptimizationObservation
    from sagents.v2.optimization.workspace_evidence import attest_files
    observation = fixture_observation({'index.html':'one'})
    second = fixture_observation({'index.html':'two'})['evidence']['final_items']
    for item in second:
        item['item_id'] += '-second'
        item['data']['tool_call_id'] += '-second'
    observation['evidence']['final_items'].extend(second)
    observation['evidence']['run_id'] = 'fixture'
    # Actual completion order differs from proposal order; use the host's bytes.
    (tmp_path/'index.html').write_text('one')
    original = OptimizationObservation.model_validate(observation)
    evidence = attest_files(original,tmp_path)
    observation['evidence'] = evidence
    recovered, trace = workspace.replay({'observation':observation})
    assert recovered == {'index.html':'one'}
    assert all(t['final_file_authority']=='host_terminal_workspace' for t in trace)
    evidence['workspace_files']['files']['index.html']['content'] = 'forged'
    with pytest.raises(ValueError,match='hash'):
        workspace.replay({'observation':observation})


def test_noop_update_matches_native_replacement_count():
    from sagents.v2.tool.official.filesystem import _apply_update_operations
    observation = fixture_observation({'index.html':'Original'})
    operation = [{'update_mode':'search_replace','search_pattern':'Original','replacement':'Original'}]
    content, summaries, count = _apply_update_operations('Original',operation)
    assert content == 'Original' and count == 1
    observation['evidence']['final_items'].extend([
        {'item_id':'nc','run_id':'fixture','step_id':'next','data':{'kind':'tool_call',
            'tool_call_id':'noop','tool_name':'file_update','arguments':{'file_path':'index.html','operations':operation}}},
        {'item_id':'nr','run_id':'fixture','step_id':'next','data':{'kind':'tool_result','tool_call_id':'noop',
            'content':[{'kind':'json','value':{'status':'success','file_path':'index.html','operations':summaries,'replacements':0}}]}}])
    assert workspace.replay({'observation':observation})[0] == {'index.html':'Original'}


@pytest.mark.parametrize('count', [1, 3, 4, 6])
def test_screenshot_contact_boards_are_square_and_bounded(count):
    stream = BytesIO()
    Image.new('RGB', (1440, 1000), '#884466').save(stream, 'PNG')
    board = sheet([stream.getvalue()] * count, 'desktop 1440x1000 / page 1')
    assert board.width == board.height and board.width <= 1920


def test_local_linked_page_selection():
    assert pages({'index.html':'<a href="a.html">A</a><a href="README.md">Notes</a><a href="helper.py">Source</a><a href="https://remote.invalid/b.html">B</a>',
        'README.md':'# Notes', 'helper.py':'raise RuntimeError("Not executable")',
        'a.html':'<a href="b.html">B</a>', 'b.html':'<h1>B</h1>'}) == ['index.html','a.html','b.html']


def test_builtin_lint_and_skill_reads_preserve_site_and_lint_evidence():
    observation = fixture_observation({'index.html': '<h1>Keep me</h1>'})
    lint = {'status': 'success', 'diagnostics': [{'path': 'main.js', 'message': 'Unexpected token'}],
            'diagnostics_count': 1, 'linters': {'eslint': {'status': 'completed', 'exit_code': 1}},
            'skipped_linters': []}
    for name, args, result in [('read_lints', {'paths': ['main.js']}, lint),
                               ('load_skill', {'skill_name': 'layout'}, {'status': 'success'})]:
        observation['evidence']['final_items'].extend([
            {'item_id': name+'c', 'run_id': 'fixture', 'step_id': name,
             'data': {'kind': 'tool_call', 'tool_call_id': name, 'tool_name': name, 'arguments': args}},
            {'item_id': name+'r', 'run_id': 'fixture', 'step_id': name,
             'data': {'kind': 'tool_result', 'tool_call_id': name,
                      'content': [{'kind': 'json', 'value': result}]}}])
    files, trace = workspace.replay({'observation': observation})
    assert files == {'index.html': '<h1>Keep me</h1>'}
    assert next(item for item in trace if item.get('tool') == 'read_lints')['result'] == lint


def test_seeded_random_is_reproducible_but_allows_unique_selection():
    import json
    import shutil
    import subprocess
    from evaluation_datasets.web_design.rendering import DETERMINISTIC_RANDOM
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required for native JavaScript PRNG test')
    sample = '''const pick = new Set(); let tries = 0;
      while (pick.size < 2 && tries++ < 100) pick.add(Math.floor(Math.random() * 20));
      console.log(JSON.stringify({pick:[...pick], tries, samples:Array.from({length:50},()=>Math.random())}));'''
    def run(source):
        return json.loads(subprocess.check_output([node, '-e', source + sample], text=True))
    old = run('Math.random = () => .5;')
    assert len(old['pick']) == 1 and old['tries'] >= 100
    fixed = run(DETERMINISTIC_RANDOM)
    assert fixed == run(DETERMINISTIC_RANDOM)
    assert len(fixed['pick']) == 2 and fixed['tries'] < 100
    assert len(set(fixed['samples'])) > 40
    assert all(0 <= value < 1 for value in fixed['samples'])


def test_render_progress_preserves_phase_and_resets_each_attempt(tmp_path):
    import json
    from evaluation_datasets.web_design.rendering import progress
    progress(tmp_path, 'browser_queue')
    progress(tmp_path, 'browser_acquired')
    progress(tmp_path, 'interaction', viewport='mobile', control=0)
    progress(tmp_path, 'interaction', error_type='TimeoutError')
    data = json.loads((tmp_path / 'render-progress.json').read_text())
    assert [x['stage'] for x in data['history']] == ['browser_queue', 'browser_acquired', 'interaction', 'interaction']
    assert data['error_type'] == 'TimeoutError'
    assert data['elapsed_seconds'] >= 0
    progress(tmp_path, 'browser_queue')
    assert len(json.loads((tmp_path / 'render-progress.json').read_text())['history']) == 1
