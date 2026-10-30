"""Desktop imports prepare-only plugins and routes native images to its Eval Agent."""
import base64
from io import BytesIO
import json

from PIL import Image
import pytest

from app.v2.desktop.backend.rsi_evaluation import ScorerImport
from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
from sagents.v2.optimization.builtin_scoring import BuiltinScoring
from tests.app.v2.desktop.test_rsi import RsiModel, authored_evaluation_response, setup_service, start_request
from tests.sagents.v2.test_evaluation_plugin import diagnosis


def prepare_only_source():
    data = BytesIO()
    Image.new('RGB', (32, 32), '#e8b36c').save(data, 'PNG')
    return '''from pathlib import Path
import base64
import hashlib
EVALUATION_CAPABILITIES = {'mode':'pairwise','prepare':True}
EVALUATION_CONTRACT = 'Prepare screenshots only. The Eval Agent judges beauty and analyzes it.'
def prepare(request):
    images, files = [], []
    if request.get('artifact_directory'):
        path = Path(request['artifact_directory'])/'image.png'
        raw = base64.b64decode(''' + repr(base64.b64encode(data.getvalue()).decode()) + ''')
        path.write_bytes(raw)
        images = [str(path)]
        files = [{'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw),'media_type':'image/png'}]
    return {'artifact':{'presentation':{'text':'Rendered website','images':images}},'files':files}
EVALUATION_TEST_CASES = [{'operation':'prepare','request':{'capture_id':'fixture','goal':'Beauty',
    'case':{'id':'fixture','input':'Make a website','rubric':'Beauty'},'observation':{'state':'completed','output':'Site'}},
    'expected':{'artifact':{'presentation':{'text':'Rendered website','images':[]}}}}]
'''


class VisualEvalModel(RsiModel):
    visual_requests = 0

    async def _stream(self, request):
        user = [m for m in request.messages if m.role == 'user'][-1]
        text = ''.join(b.text for b in user.content if b.kind == 'text')
        if '<user_request>' in text:
            text = text.split('<user_request>', 1)[1].rsplit('</user_request>', 1)[0].strip()
        try:
            payload = json.JSONDecoder().raw_decode(text)[0]
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        title = payload.get('response_schema', {}).get('title')
        if title in {'EvaluationResult', 'OptimizationDiagnosis'}:
            self.requests.append(request)
            if payload['data'].get('protocol') != 'sage.rsi.evaluation-files/v1':
                assert payload['data']['goal'] == 'Beauty'
            if 'visual_evidence' in payload:
                assert any(b.kind == 'image' for b in user.content)
                self.visual_requests += 1
            analysis = diagnosis().model_dump(mode='json')
            answer = ({'comparison': {'winner': 'A', 'rationale': 'Stronger composition'}, 'analysis': analysis}
                if title == 'EvaluationResult' else analysis)
            response = authored_evaluation_response(request, payload, answer)
            yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=response or ModelResponse(
                response_id='visual-eval', text=json.dumps(answer), finish_reason='stop'))
            return
        async for event in super()._stream(request):
            yield event


@pytest.mark.asyncio
async def test_desktop_prepare_only_plugin_runs_visual_eval_and_summary(tmp_path, monkeypatch):
    model = VisualEvalModel()
    service, agent = await setup_service(tmp_path, monkeypatch, model)
    try:
        imported = await service.import_rsi_scorer(agent, ScorerImport(name='scorer.py', source=prepare_only_source()), 'alice')
        assert imported['validation']['capabilities']['prepare']
        from sagents.v2.optimization.contracts import OptimizationCase, OptimizationTestSuite
        request = start_request().model_copy(update={'goal': 'Beauty', 'rounds': 1, 'grow_training': False, 'max_concurrency':2,
            'builtin_scoring': BuiltinScoring(mode='pairwise'), 'scorer_id': imported['id'],
            'human_test_repeats': 2, 'human_test_suite': OptimizationTestSuite(cases=(
                OptimizationCase(id='hidden-visual', input='PRIVATE hidden visual brief', rubric='Beauty', split='test'),))})
        run = await service.start_rsi(agent, request, 'alice')
        await service._rsi_tasks[run['id']]
        final = await service.rsi_run(agent, run['id'], 'alice')
        assert final['status'] == 'completed', final.get('error_type')
        assert final['test_observations'] and all(row['status'] == 'completed' for row in final['test_observations'])
        assert 'PRIVATE hidden visual brief' not in str(final['result']['report']['agent_calls'])
        assert model.visual_requests >= 5  # Initial training analysis plus both orders for train/dev.
        baseline_case = final['result']['report']['baseline']['cases'][0]
        assert all(trial['grade']['diagnosis'] for trial in (baseline_case['trials'] or [baseline_case]))
        # Resume after only the first anonymous order has completed. The other
        # order must not consume its cached judgment, even with identical text.
        from sagents.v2.optimization.recovery import OptimizationRecovery
        calls = final['result']['report']['agent_calls']
        judgments = [c for c in calls if c['role'] == 'evaluation'
            and json.loads(c['request']).get('response_schema', {}).get('title') == 'EvaluationResult']
        first = judgments[0]
        opposite = next(c for c in judgments[1:] if c['case_id'] == first['case_id']
            and c['round'] == first['round'] and c['trial'] == first['trial'])
        assert json.loads(first['request'])['visual_artifact_binding'] != json.loads(opposite['request'])['visual_artifact_binding']
        path = tmp_path/'partial-visual-judgment.jsonl'
        fields = ('role', 'phase', 'round', 'trial', 'case_id', 'request')
        path.write_text('\n'.join(json.dumps(e) for e in [
            {'event':'operation_started', 'data':{}},
            {'event':'agent_call_started', 'data':{'call_id':'first', **{k:first[k] for k in fields}}},
            {'event':'agent_call_completed', 'data':{'call_id':'first', 'observation':first['observation']}},
        ]))
        recovered = OptimizationRecovery(path)
        assert recovered.completed_call(**{k:opposite[k] for k in fields}) is None
        assert recovered.completed_call(**{k:first[k] for k in fields}) is not None
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_empty_desktop_system_prompt_is_preserved_in_rsi_snapshot(tmp_path, monkeypatch):
    service, identity = await setup_service(tmp_path, monkeypatch, RsiModel())
    try:
        record = await service._agent(identity, 'alice')
        empty = record.model_copy(update={'config': {**record.config, 'systemPrefix': ''}})
        bundle, _ = await service._agent_snapshot(empty)
        assert bundle.resolved_manifest().agents[identity].instructions.inline == ''
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_native_web_dataset_renders_grids_and_analyzes_readonly_process_files(tmp_path, monkeypatch):
    from pathlib import Path
    from sagents.v2.model.contracts import ModelToolCall
    from app.v2.desktop.backend.schemas import AgentSettingsPatch
    from sagents.v2.optimization.dataset import OptimizationDataset
    from evaluation_datasets.web_design.workspace import TOOLS
    playwright = pytest.importorskip('playwright.async_api')
    async with playwright.async_playwright() as browser_api:
        if not Path(browser_api.chromium.executable_path).exists():
            pytest.skip('Chromium not installed')
    class NativeWebsiteModel(VisualEvalModel):
        async def _stream(self, request):
            user = [m for m in request.messages if m.role == 'user'][-1]
            text = ''.join(b.text for b in user.content if b.kind == 'text')
            if '<user_request>' in text:
                text = text.split('<user_request>', 1)[1].rsplit('</user_request>', 1)[0].strip()
            if text.startswith('Create a website for'):
                self.requests.append(request)
                completed = {m.tool_call_id for m in request.messages if m.role == 'tool'}
                if 'site-unknown' not in completed:
                    yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=ModelResponse(
                        response_id='unknown-site-tool', finish_reason='tool_calls', tool_calls=(ModelToolCall(
                            tool_call_id='site-unknown',name='read',arguments={'file_path':'index.html'}),)))
                    return
                if 'site-done' in completed:
                    yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=ModelResponse(
                        response_id='site-ready', text='Created index.html.', finish_reason='stop'))
                    return
                if 'site-write' not in completed:
                    call = ModelToolCall(tool_call_id='site-write', name='file_write', arguments={
                        'file_path':'index.html', 'content':'<!doctype html><title>Studio</title><h1>Fixture</h1><p>Local artwork</p>'})
                elif 'site-update' not in completed:
                    call = ModelToolCall(tool_call_id='site-update', name='file_update', arguments={
                        'file_path':'index.html','operations':[{'update_mode':'search_replace',
                            'search_pattern':'<h1>Fixture</h1>','replacement':'<h1>Gallery</h1>'}]})
                else:
                    call = ModelToolCall(tool_call_id='site-done', name='turn_status', arguments={'status':'task_done'})
                calls = (call,)
                if call.tool_call_id == 'site-write':
                    calls += (ModelToolCall(tool_call_id='site-readme',name='file_write',arguments={
                        'file_path':'README.md','content':'# Local website notes'}),
                        ModelToolCall(tool_call_id='site-helper',name='file_write',arguments={
                            'file_path':'helper.py','content':'from pathlib import Path\nPath('
                                + repr(str(tmp_path/'project-script-executed')) + ').write_text("executed")'}))
                yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=ModelResponse(
                    response_id='native-site', tool_calls=calls, finish_reason='tool_calls'))
                return
            async for event in super()._stream(request):
                yield event
    model = NativeWebsiteModel()
    service, agent = await setup_service(tmp_path, monkeypatch, model)
    root = Path('evaluation_datasets/web_design')
    try:
        await service.patch_agent_settings(agent, AgentSettingsPatch(system_prefix=(root/'baseline.system.txt').read_text(),
            available_tools=list(TOOLS),available_skills=[]), 'alice')
        imported = await service.import_rsi_scorer(agent, ScorerImport(name='scorer.py', source=(root/'scorer.py').read_text()), 'alice')
        data = json.loads((root/'rsi.dataset.json').read_text())
        data['cases'] = [next(c for c in data['cases'] if c['split']==split) for split in ('training','validation')]
        request = start_request().model_copy(update={'goal':'Beauty','suite':None,
            'dataset':OptimizationDataset.model_validate(data),'rounds':1,'grow_training':False,
            'initial_training_case_count':1,'builtin_scoring':BuiltinScoring(mode='pairwise'),'scorer_id':imported['id']})
        run = await service.start_rsi(agent, request, 'alice')
        await service._rsi_tasks[run['id']]
        final = await service.rsi_run(agent, run['id'], 'alice')
        assert final['status']=='completed', final.get('error_type')
        native = final['result']['report']['baseline']['cases'][0]['observation']
        assert native['state'] == 'completed'
        snapshot = native['evidence']['workspace_files']
        assert snapshot['complete'] is True
        assert snapshot['run_id'] == native['evidence']['run_id']
        assert '<h1>Gallery</h1>' in snapshot['files']['index.html']['content']
        assert all(path.endswith('/work') for path in native['evidence']['workspace_attestation']['roots'])
        assert any((item.get('data',{}).get('error') or {}).get('code') == 'tool.not_found'
            for item in native['evidence']['final_items'])
        calls = final['result']['report']['agent_calls']
        contexts = list((service.runtime_root/'rsi'/run['id']/'evaluations').rglob('context.json'))
        assert any('diagnostic_evidence' in json.loads(path.read_text()) for path in contexts)
        assert any(c['role']=='evaluation' and c['observation']['evidence'].get('evaluation_read_coverage') for c in calls)
        assert model.visual_requests >= 5
        assert not (tmp_path/'project-script-executed').exists()
        assert list((service.runtime_root/'rsi'/run['id']/'pairwise').rglob('source/README.md'))
        assert list((service.runtime_root/'rsi'/run['id']/'pairwise').rglob('source/helper.py'))
    finally:
        await service.close()
