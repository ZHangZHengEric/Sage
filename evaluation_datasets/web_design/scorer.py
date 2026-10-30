"""Prepare frozen website screenshots. Sage's configured Eval Agent judges them."""
from evaluation_datasets.web_design import workspace

EVALUATION_CAPABILITIES = {'mode': 'pairwise', 'prepare': True}
EVALUATION_CONTRACT = '''Prepare anonymous rendered websites, never score or analyze them here.
The Eval Agent sees the problem, optimization goal and paired visual evidence.
Prefer beauty, visual appeal and artistic expression: composition, typography,
color, imagery, rhythm, detail, originality and a coherent artistic direction.
Accept different styles; do not favor minimalism, maximalism, dark themes, gradients,
length, page count or feature count by themselves. Consider the whole website across
desktop, tablet and mobile. Reward meaningful visual authorship over generic templates.
The brief must still be recognizable, and broken/empty/unreadable output is a defect.
State concrete visual evidence and tradeoffs. Equal beauty or insufficient basis
for preference permits a tie; infrastructure failure is missing measurement.
Interaction boards show before/after states for up to two semantic controls on the homepage.
Judge their visible coherence and usefulness, without assuming uncaptured interactions work.
Screenshots cannot prove complete interaction quality, accessibility conformance or animation quality.
No absolute aesthetic scores. Blind judgments see screenshots only. After judgment, analysis can inspect anonymous execution summaries and complete final source. No agent policy or version identity is shown.
'''


async def prepare(request):
    files, trace = workspace.replay(request)
    if not files.get('index.html', '').strip():
        result = {'execution_failure': 'missing_index_html', 'artifact': {'status': 'invalid', 'presentation': {
            'text': 'No nonempty index.html was produced in the recorded website workspace.', 'images': []}}}
        if request.get('artifact_directory'):
            from pathlib import Path
            import json
            from evaluation_datasets.web_design.rendering import frozen as freeze_file
            root = Path(request['artifact_directory'])
            root.mkdir(parents=True, exist_ok=True)
            path = root / 'execution.json'
            path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')
            result.update(files=[freeze_file(path, 'application/json')],
                diagnostics={'text': 'Execution of the invalid submission; no usable entry page was produced.', 'files': [str(path)]})
        return result
    if not request.get('artifact_directory'):
        raise ValueError('Website rendering requires a host-owned artifact_directory')
    from pathlib import Path
    from evaluation_datasets.web_design.rendering import render
    import json
    artifact, frozen = await render(files, request['artifact_directory'])
    contacts = [item['path'] for item in frozen if item['media_type'] == 'image/jpeg']
    artifact['presentation'] = {'text': 'Homepage and up to two linked local pages; desktop 1440x1000, '
        'tablet 768x1024, mobile 390x844. Each square n-by-n board contains up to four labeled scroll frames '
        'when the document scrolls. Additional boards show before/after states of up to two homepage '
        'controls in DOM order (button, tab, disclosure, range or select). Uncaptured controls are unverified. '
        'Full-resolution PNGs are retained. All external network requests '
        'are blocked equally; appearance is judged with local/inline assets. '
        'Source and screenshot manifest are frozen for audit.', 'images': contacts}
    # Paths remain host-private; screenshots contain only neutral page/viewport labels.
    artifact['manifest'] = str(Path(request['artifact_directory']) / 'screenshots.json')
    trace_path = Path(request['artifact_directory']) / 'execution.json'
    trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')
    from evaluation_datasets.web_design.rendering import frozen as freeze_file
    frozen.append(freeze_file(trace_path, 'application/json'))
    source_paths = [item['path'] for item in frozen if Path(item['path']).is_relative_to(Path(request['artifact_directory']) / 'source')]
    return {'artifact': artifact, 'files': frozen, 'diagnostics': {
        'text': 'Anonymous chronological assistant actions, native tool arguments and outcomes, plus complete final website source. '
            'Write bodies are represented by their content hashes and sizes; full earlier revisions remain in the host execution archive. '
            'Use visible screenshots for appearance and these records for diagnosis; do not infer unobserved causal effects.',
        'files': [str(trace_path), *source_paths]}}



EVALUATION_TEST_CASES = [{
    'operation': 'prepare',
    'request': {'capture_id': 'empty-site', 'goal': 'Beauty, visual appeal and artistic expression.',
        'case': {'id': 'fixture', 'input': 'Create a website for a kite festival.', 'rubric': 'Aesthetics.'},
        'observation': {'state': 'completed', 'output': 'Finished.', 'evidence': {
            'final_items': [{'item_id': 'message', 'data': {'kind': 'message', 'role': 'assistant',
                'content': [{'kind': 'text', 'text': 'Finished.'}]}}]}}},
    'expected': {'execution_failure': 'missing_index_html', 'artifact': {'status': 'invalid', 'presentation': {
        'text': 'No nonempty index.html was produced in the recorded website workspace.', 'images': []}}},
}]
