"""V2 lint Tool: only completed, parsed checks can report a passing result."""
from __future__ import annotations

import json
import posixpath
from pathlib import PurePosixPath
from typing import Any

from sagents.v2.tool import SideEffectLevel, ToolInvocation, tool
from sagents.v2.tool.official.runtime import OfficialToolRuntime


class QualityTools:
    def __init__(self, runtime: OfficialToolRuntime) -> None:
        self.runtime = runtime

    @tool(
        description="Check HTML/CSS syntax (including inline CSS), and run installed Python/JavaScript/TypeScript linters. Only passed=true confirms all requested checks completed without diagnostics; incomplete checks are not passes.",
        side_effect_level=SideEffectLevel.READ,
    )
    async def read_lints(self, paths: list[str], invocation: ToolInvocation,
                         max_diagnostics: int = 50, session_id: str | None = None) -> dict[str, Any]:
        del session_id
        if not paths:
            raise ValueError('paths must be a non-empty list')
        paths = list(dict.fromkeys(paths))
        groups = {'ruff': [], 'eslint': [], 'html': [], 'css': []}
        unsupported = []
        for path in paths:
            suffix = PurePosixPath(path).suffix.lower()
            group = ('ruff' if suffix == '.py' else 'eslint' if suffix in {'.js', '.jsx', '.ts', '.tsx', '.vue'}
                     else 'html' if suffix in {'.html', '.htm'} else 'css' if suffix == '.css' else None)
            (groups[group] if group else unsupported).append(path)
        diagnostics, linters = [], {}
        for name in ('ruff', 'eslint'):
            if not groups[name]:
                continue
            args = ' '.join(_shell_quote(path) for path in groups[name])
            # Never let npx download/install packages or wait for a prompt.
            command = ('ruff check --output-format json -- ' + args if name == 'ruff' else
                'if [ -x node_modules/.bin/eslint ]; then node_modules/.bin/eslint --format json -- ' + args +
                '; else eslint --format json -- ' + args + '; fi')
            child = ToolInvocation(invocation.call.model_copy(update={
                'idempotency_key': invocation.call.idempotency_key + ':' + name,
            }), invocation.request_context)
            result = await self.runtime.shell(command, child, workdir=None, env_vars={}, block_until_ms=120_000)
            check = _linter_status(result)
            check['paths'] = groups[name]
            linters[name] = check
            if check['status'] != 'completed':
                continue
            try:
                values = json.loads(result.get('stdout') or '')
                parsed = _parse_report(name, values)
                if result['exit_code'] == 1 and not parsed:
                    raise ValueError('Nonzero exit without diagnostics')
                if name == 'eslint':
                    reported = [posixpath.normpath(v['filePath'].replace('\\', '/')) for v in values]
                    for path in groups[name]:
                        expected = posixpath.normpath(path.replace('\\', '/'))
                        if not any(p == expected or (not expected.startswith('/') and p.endswith('/' + expected)) for p in reported):
                            raise ValueError('ESLint did not report every requested file')
                diagnostics.extend(parsed)
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                check.update(status='failed', reason='Invalid or incomplete linter report: ' + str(error)[:200])
        from sagents.v2.tool.official.web_syntax import css_diagnostics, html_diagnostics
        for name, checker in [('html', html_diagnostics), ('css', css_diagnostics)]:
            for path in groups[name]:
                check = {'status': 'completed', 'paths': [path]}
                linters[f'{name}:{path}'] = check
                try:
                    content = await self.runtime.read_text(path, invocation)
                    diagnostics.extend(checker(content, path))
                except (OSError, UnicodeError, ImportError, RecursionError) as error:
                    check.update(status='failed', reason=f'{type(error).__name__}: {str(error)[:200]}')
        complete = bool(linters) and not unsupported and all(c['status'] == 'completed' for c in linters.values())
        limit = max(1, max_diagnostics)
        return {
            'success': complete, 'status': 'completed' if complete else 'incomplete',
            'passed': not diagnostics if complete else None,
            'diagnostics': diagnostics[:limit], 'diagnostics_count': len(diagnostics),
            'truncated': len(diagnostics) > limit, 'linters': linters,
            'skipped_linters': [name for name, value in linters.items() if value['status'] == 'skipped'],
            'unsupported_paths': unsupported,
            'coverage': 'HTML5 parse errors; CSS structural/declaration syntax including inline CSS. '
                'Does not check CSS property values, visual appearance, linked resources, accessibility or inline JavaScript. '
                'External linters use their installed configuration. Missing, running and failed checks are not passes.',
        }


def _parse_report(name, values):
    if not isinstance(values, list):
        raise ValueError('Expected a JSON array')
    diagnostics = []
    if name == 'ruff':
        for value in values:
            location = value['location']
            diagnostics.append(dict(path=value['filename'], line=location['row'], column=location['column'],
                code=value['code'], message=value['message'], source='ruff', severity='error'))
    else:
        for value in values:
            if not isinstance(value['messages'], list):
                raise ValueError('Expected ESLint messages')
            for message in value['messages']:
                diagnostics.append(dict(path=value['filePath'], line=message.get('line'), column=message.get('column'),
                    code=message.get('ruleId'), message=message['message'], source='eslint',
                    severity='error' if message.get('severity') == 2 else 'warning'))
    return diagnostics


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _linter_status(result: dict[str, Any]) -> dict[str, Any]:
    detail = {key: result[key] for key in ('task_id', 'exit_code', 'error') if key in result}
    status, exit_code = result.get('status'), result.get('exit_code')
    if status in {'running', 'pending', 'queued'}:
        return {**detail, 'status': 'running', 'reason': 'Check is still running; no result is available.'}
    if exit_code == 127:
        return {**detail, 'status': 'skipped', 'reason': 'Linter is not installed.'}
    if status not in {'completed', 'failed'} or type(exit_code) is not int or exit_code not in (0, 1) or result.get('error'):
        return {**detail, 'status': 'failed', 'reason': 'Linter did not produce a verified terminal result.'}
    return {**detail, 'status': 'completed'}
