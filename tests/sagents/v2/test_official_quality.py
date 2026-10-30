"""Read-only lint results must not confuse unavailable checks with passes."""
import json
from unittest.mock import AsyncMock

import pytest

from sagents.v2.tool import ToolCall, ToolInvocation
from sagents.v2.contracts.principals import ActorRef, RequestContext
from sagents.v2.tool.official.quality import QualityTools
from sagents.v2.tool.official.web_syntax import css_diagnostics, html_diagnostics


INVOCATION = ToolInvocation(ToolCall(tool_call_id='lint', tool_name='read_lints',
    arguments={}, operation_id='lint-op', idempotency_key='lint-key', owner_run_id='run'),
    RequestContext(actor=ActorRef(principal_id='user', principal_type='user')))


def runtime_with(result=None, files=None):
    runtime = AsyncMock()
    runtime.shell.return_value = result
    async def read(path, invocation):
        if path not in (files or {}):
            raise FileNotFoundError(path)
        return files[path]
    runtime.read_text.side_effect = read
    return runtime


@pytest.mark.asyncio
@pytest.mark.parametrize('result,expected', [
    ({'status': 'running', 'task_id': 'pending', 'stdout': '[]'}, 'running'),
    ({'status': 'failed', 'exit_code': None, 'stdout': ''}, 'failed'),
    ({'status': 'completed', 'exit_code': 0, 'stdout': ''}, 'failed'),
    ({'status': 'completed', 'exit_code': 0, 'stdout': 'not JSON'}, 'failed'),
    ({'status': 'failed', 'exit_code': 2, 'stdout': '[]'}, 'failed'),
    ({'status': 'failed', 'exit_code': 127, 'stdout': ''}, 'skipped'),
    ({'status': 'failed', 'exit_code': 1, 'stdout': '[]'}, 'failed'),
    ({'status': 'completed', 'exit_code': 0, 'error': {'message': 'lost'}, 'stdout': '[]'}, 'failed'),
    ({'exit_code': 0, 'stdout': '[]'}, 'failed'),
    ({'status': 'killed', 'exit_code': 0, 'stdout': '[]'}, 'failed'),
])
async def test_incomplete_or_invalid_report_never_passes(result, expected):
    value = await QualityTools(runtime_with(result)).read_lints(['a.py'], INVOCATION)
    assert value['status'] == 'incomplete' and value['passed'] is None and not value['success']
    assert value['linters']['ruff']['status'] == expected
    if result.get('task_id'):
        assert value['linters']['ruff']['task_id'] == result['task_id']


@pytest.mark.asyncio
async def test_ruff_empty_verified_report_passes_and_nonzero_diagnostics_do_not():
    runtime = runtime_with({'status': 'completed', 'exit_code': 0, 'stdout': '[]'})
    assert (await QualityTools(runtime).read_lints(['a.py'], INVOCATION))['passed'] is True
    runtime.shell.return_value = {'status': 'completed', 'exit_code': 1, 'stdout': json.dumps([
        {'filename': 'a.py', 'location': {'row': 1, 'column': 2}, 'code': 'F821', 'message': 'undefined'}])}
    value = await QualityTools(runtime).read_lints(['a.py'], INVOCATION)
    assert value['status'] == 'completed' and value['passed'] is False
    assert value['diagnostics'][0]['code'] == 'F821'


@pytest.mark.asyncio
async def test_eslint_never_installs_packages_and_empty_coverage_is_not_pass():
    runtime = runtime_with({'status': 'completed', 'exit_code': 0, 'stdout': '[]'})
    value = await QualityTools(runtime).read_lints(['app.js'], INVOCATION)
    assert value['passed'] is None
    command = runtime.shell.call_args.args[0]
    assert 'npx' not in command and 'npm' not in command
    runtime.shell.return_value['stdout'] = json.dumps([{'filePath':'app.js', 'messages': []}])
    assert (await QualityTools(runtime).read_lints(['app.js'], INVOCATION))['passed'] is True


@pytest.mark.asyncio
async def test_mixed_checks_use_separate_job_identities_and_fail_closed():
    runtime = runtime_with()
    runtime.shell.side_effect = [
        {'status': 'completed', 'exit_code': 0, 'stdout': '[]'},
        {'status': 'running', 'task_id': 'js-job', 'stdout': ''}]
    value = await QualityTools(runtime).read_lints(['a.py','b.js'], INVOCATION)
    assert value['passed'] is None and value['status'] == 'incomplete'
    keys = [call.args[1].call.idempotency_key for call in runtime.shell.call_args_list]
    assert len(set(keys)) == 2


@pytest.mark.asyncio
async def test_html_css_native_read_checks_without_shell_or_external_install():
    files = {'index.html':'<!doctype html><html><head><title>OK</title></head><body><p>Hello</p></body></html>',
             'style.css':'body { color: red; }'}
    runtime = runtime_with(files=files)
    tool = QualityTools(runtime)
    assert (await tool.read_lints(list(files), INVOCATION))['passed'] is True
    files['style.css'] = 'body::before{opacity:.5;\nimg,svg{display:block}'
    value = await tool.read_lints(list(files), INVOCATION)
    assert value['passed'] is False
    assert any(d['source']=='css-syntax' and 'missing }' in d['message'] for d in value['diagnostics'])
    runtime.shell.assert_not_called()
    assert (await tool.read_lints(['missing.html'], INVOCATION))['passed'] is None
    assert (await tool.read_lints(['notes.md'], INVOCATION))['passed'] is None


def test_html5_optional_tags_and_raw_script_text_not_misreported():
    valid = '<!doctype html><title>Test</title><ul><li>One<li>Two</ul><script>if (a < b) { x = "<p>"; }</script>'
    assert html_diagnostics(valid, 'index.html') == []
    invalid = '<!doctype html><title>Test</title><div><span>Text</div>'
    assert any(d['source']=='html5' for d in html_diagnostics(invalid,'index.html'))


def test_inline_style_and_style_attribute_css_errors_have_html_locations():
    text = '<!doctype html>\n<title>Test</title>\n<style>\nbody { color: red;\n</style>\n<p style="color red;">Test</p>'
    errors = html_diagnostics(text, 'index.html')
    assert any(d['source']=='css-syntax' and d['line']==4 and 'missing }' in d['message'] for d in errors)
    assert any(d['source']=='css-syntax' and d['line']==6 for d in errors)


@pytest.mark.parametrize('text', [
    'a{content:"}"; --data:{a:b}; &:hover {color:blue}}',
    '@media(width<600px){a{display:grid}}',
    '@font-face{font-family:x;src:url(data:image/svg+xml;utf8,<svg>{}</svg>)}',
    r'.x\{ {color:var(--a, red)} /* } */',
    '@keyframes go{from{opacity:0}to{opacity:1}}',
])
def test_valid_modern_css_does_not_trigger_balance_false_positives(text):
    assert css_diagnostics(text,'x.css') == []


@pytest.mark.parametrize('text', ['a {color red;}', 'a{content:"x}', 'a{color:red} /* unfinished', 'a{width:calc(2px + 1px}'])
def test_invalid_css_is_reported(text):
    assert css_diagnostics(text,'x.css')


@pytest.mark.asyncio
async def test_partial_eslint_coverage_does_not_pass_whole_request():
    runtime = runtime_with({'status':'completed','exit_code':0,
        'stdout':json.dumps([{'filePath':'/workspace/a.js','messages':[]}])})
    assert (await QualityTools(runtime).read_lints(['a.js','b.js'],INVOCATION))['passed'] is None
