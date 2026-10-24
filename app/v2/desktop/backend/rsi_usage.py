"""Human-only RSI accounting from provider usage, separate from optimization data."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

STAGES = ('execution', 'evaluation', 'design', 'tuning', 'review', 'dialogue', 'other')
FIELDS = ('input_tokens', 'cached_input_tokens', 'output_tokens')
ROLE_STAGES = {'evaluation': 'evaluation', 'evaluator': 'evaluation', 'scoring': 'evaluation', 'test_design': 'design',
    'designer': 'design', 'tuning': 'tuning', 'tuner': 'tuning', 'semantic_review': 'review',
    'reviewer': 'review', 'suite_review': 'review', 'suite_reviewer': 'review',
    'dialogue': 'dialogue', 'test_dialogue': 'dialogue', 'user': 'dialogue', 'user_simulator': 'dialogue'}


def stage_for_package(package):
    identity = package.manifest.metadata.id
    role = identity.removeprefix('desktop.rsi.')
    if not identity.startswith('desktop.rsi.'):
        return 'execution'
    if role == 'designer':
        from sagents.v2.optimization.principles import DIALOGUE_USER_PRINCIPLES
        if any(a.instructions.inline == DIALOGUE_USER_PRINCIPLES for a in package.manifest.agents.values()):
            return 'dialogue'
    return ROLE_STAGES.get(role, 'other')


class MeteredRsiModel:
    """One durable usage record per actual provider invocation, including failures."""
    def __init__(self, provider, root, stage):
        self.provider, self.root, self.stage = provider, Path(root), stage

    def __getattr__(self, name):
        return getattr(self.provider, name)

    async def stream(self, request):
        from sagents.v2.model.contracts import ModelEventKind
        usage, status = None, 'failed'
        stream = None
        try:
            stream = self.provider.stream(request)
            async for event in stream:
                if event.kind == ModelEventKind.COMPLETED:
                    usage = event.response.usage.model_dump(mode='json', include={'reported', *FIELDS})
                    status = 'completed'
                yield event
        except asyncio.CancelledError:
            status = 'cancelled'
            raise
        finally:
            try:
                close = getattr(stream, 'aclose', None)
                if close is not None:
                    await close()
            finally:
                record = {'id': uuid4().hex, 'native_run_id': request.run_id, 'stage': self.stage,
                    'status': status, 'usage': usage}
                path = self.root / 'token-usage.jsonl'
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(fd, 'w', encoding='utf-8') as output:
                    output.write(json.dumps(record) + '\n')


def empty_counts():
    return {**dict.fromkeys(FIELDS, 0), 'reported_records': 0, 'unreported_records': 0}


def add_usage(counts, usage):
    if not isinstance(usage, dict) or usage.get('reported') is not True:
        counts['unreported_records'] += 1
        return
    counts['reported_records'] += 1
    for name in FIELDS:
        value = usage.get(name, 0)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            counts[name] += value


def finalize(counts):
    return {**counts, 'total_tokens': counts['input_tokens'] + counts['output_tokens'],
        'cache_rate': counts['cached_input_tokens'] / counts['input_tokens']
            if counts['input_tokens'] and counts['cached_input_tokens'] <= counts['input_tokens'] else None}


class RsiUsageReader:
    """Incremental file cursors avoid rescanning large transcripts on every poll.

    Legacy observation scopes are deduplicated across recovery journals and test
    checkpoint snapshots. Native runs with provider records use ONLY those records.
    """
    def __init__(self):
        self.cursors, self.roles, self.primary, self.legacy, self.scorer = {}, {}, {}, {}, {}
        self.user_simulator = {}

    def observation(self, observation, stage, fallback):
        if not isinstance(observation, dict):
            return
        evidence = observation.get('evidence') or {}
        reused = evidence.get('measurement_reuse')
        if (isinstance(reused, dict)
                and reused.get('protocol') == 'sage.rsi.historical-observation/v1'
                and reused.get('billed_provider_calls') == 0):
            return  # Historical tokens belong to the source experiment.
        native = evidence.get('run_id')
        scope = evidence.get('execution_usage_scope')
        key = json.dumps([native, scope], sort_keys=True) if native else fallback
        usage = evidence.get('execution_usage')
        if not isinstance(usage, dict):
            usage = {**{k: observation.get(k, 0) for k in FIELDS}, 'reported': observation.get('usage_reported', False)}
        self.legacy.setdefault(key, (native, stage, usage))

    def _lines(self, path):
        offset = self.cursors.get(str(path), 0)
        if path.stat().st_size < offset:
            raise ValueError('RSI usage source was truncated')
        with path.open('rb') as stream:
            stream.seek(offset)
            while line := stream.readline():
                if not line.endswith(b'\n'):
                    break  # A concurrently appended record is not complete yet.
                try:
                    record = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    break
                self.cursors[str(path)] = stream.tell()
                yield record

    def read(self, root, value):
        root = Path(root)
        primary_path = root / 'token-usage.jsonl'
        if primary_path.exists():
            for record in self._lines(primary_path):
                self.primary.setdefault(record['id'], record)
        for path in sorted(root.glob('audit*.jsonl'), key=lambda p: (p.name != 'audit.jsonl', p.name)):
            for record in self._lines(path):
                name, data = record.get('event'), record.get('data') or {}
                call = data.get('call_id')
                if name == 'agent_call_started':
                    self.roles[call] = ROLE_STAGES.get(data.get('role'), 'other')
                elif name in {'agent_call_completed', 'target_call_completed'}:
                    stage = 'execution' if name == 'target_call_completed' else self.roles.get(call, 'other')
                    self.observation(data.get('observation'), stage, f'call:{call}')
        path = root / 'scorer-model-calls.jsonl'
        if path.exists():
            for record in self._lines(path):
                self.scorer.setdefault(record['request_id'], record)
        path = root / 'user-simulator-model-calls.jsonl'
        if path.exists():
            for record in self._lines(path):
                self.user_simulator.setdefault(record['request_id'], record)
        for checkpoint in value.get('test_observations', ()):
            for case in checkpoint.get('cases', ()):
                for trial in case.get('trials', ()):
                    for index, turn in enumerate(trial.get('conversation', ())):
                        self.observation(turn.get('target'), 'execution',
                            f"test:{checkpoint.get('round')}:{case.get('id')}:{trial.get('trial')}:{index}")
        stages = {stage: empty_counts() for stage in STAGES}
        native_runs = {record['native_run_id'] for record in self.primary.values()}
        for record in self.primary.values():
            add_usage(stages.get(record['stage'], stages['other']), record.get('usage'))
        legacy_count = 0
        for native, stage, usage in self.legacy.values():
            if native not in native_runs:
                add_usage(stages[stage], usage)
                legacy_count += 1
        for record in self.scorer.values():
            add_usage(stages['evaluation'], record.get('usage'))
        for record in self.user_simulator.values():
            add_usage(stages['dialogue'], record.get('usage'))
        total = {k: sum(row[k] for row in stages.values()) for k in empty_counts()}
        return {'protocol': 'sage.rsi.token-usage/v1', 'total': finalize(total),
            'stages': {stage: finalize(row) for stage, row in stages.items()},
            'coverage': 'partial_legacy' if legacy_count else 'provider_calls' if self.primary else 'pending',
            'cache_is_input_subset': True}
