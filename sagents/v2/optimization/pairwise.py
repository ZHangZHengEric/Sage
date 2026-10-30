"""Anonymous paired judgments with durable repeated-trial binding."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
from typing import Literal

from pydantic import Field

from sagents.v2.contracts.common import StrictModel
from sagents.v2.optimization.contracts import OptimizationDiagnosis, OptimizationGrade, OptimizationObservation


class PairwiseDecision(StrictModel):
    protocol: Literal['sage.rsi.comparison.result/v1'] = 'sage.rsi.comparison.result/v1'
    winner: Literal['A', 'B', 'tie']
    rationale: str = Field(min_length=1, max_length=4000)
    analysis: OptimizationDiagnosis | None = None


class PairwiseMeasurementError(ValueError):
    rsi_requires_feedback = True
    rsi_authoritative_measurement_failed = True


FAILURE_PROTOCOL = 'sage.rsi.execution-failure/v1'


def execution_failure(observation, case):
    """Only attributable target failures qualify; unknown/infrastructure stays missing."""
    if case.mode != 'single_turn':
        return None
    error = observation.evidence.get('error') or {}
    metadata = error.get('metadata') or {}
    from sagents.v2.agent.model_recovery import ARGUMENT_ERROR_CODES
    if (error.get('code') in ARGUMENT_ERROR_CODES
            and metadata.get('side_effect_state') == 'not_applied'
            and metadata.get('tool_execution_started') is False
            and observation.state in {'failed', 'suspended'}):
        return error['code']
    if error:
        return None
    evidence = observation.evidence
    suspension = evidence.get('suspension') or {}
    if observation.state == 'suspended' and suspension.get('reason') == 'input_required':
        for event in evidence.get('runtime_events', ()):
            data = event.get('data') or {}
            if (event.get('run_id') == evidence.get('run_id')
                    and event.get('type') == 'interaction.requested'
                    and data.get('interaction_id') == suspension.get('interaction_id')
                    and (data.get('payload') or {}).get('reason_code') in
                        {'budget.max_steps', 'loop.repeated_pattern', 'loop.no_progress'}):
                return data['payload']['reason_code']
    return None


def failure_receipt(reason):
    return {'protocol': FAILURE_PROTOCOL, 'reason': reason}


def is_failure(value):
    return isinstance(value, dict) and value.get('protocol') == FAILURE_PROTOCOL


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def comparison_summary(grades):
    """Count pairs, never treating the two presentation orders as two samples."""
    counts = dict(wins=0, ties=0, losses=0, both_failed=0, order_disagreements=0, pairs=0)
    for grade in grades:
        details = grade.scorer_details.get('pairwise', {})
        outcome = details.get('outcome')
        if outcome == 'both_failed':
            counts['both_failed'] += 1
            counts['pairs'] += 1
            continue
        if outcome not in {'win', 'tie', 'loss'}:
            continue
        counts[{'win': 'wins', 'tie': 'ties', 'loss': 'losses'}[outcome]] += 1
        counts['pairs'] += 1
        counts['order_disagreements'] += int(details.get('order_disagreement', False))
    n = counts['pairs']
    return {**counts, 'win_rate': counts['wins'] / n if n else None,
        'tie_rate': counts['ties'] / n if n else None,
        'loss_rate': counts['losses'] / n if n else None,
        'preference_score': (counts['wins'] + .5 * counts['ties']) / n if n else None}


class PairwiseEvaluator:
    """Host-private frozen executions and judgments; no mutable workspace reads.

    The default judge compares completed text. Dataset-owned plugins may instead
    freeze and compare other artifacts. Sage never renders or judges web pages.
    """
    def __init__(self, *, binding, judge=None, directory=None, plugin=None, goal=""):
        self.plugin, self.goal = plugin, goal
        self.binding, self.judge = binding, judge
        self.directory = Path(directory) if directory is not None else None
        self.memory = {}

    def _load(self, key):
        if self.directory is None:
            return self.memory.get(key)
        path = self.directory / (key + '.json')
        if not path.exists():
            return None
        envelope = json.loads(path.read_text())
        if fingerprint(envelope['value']) != envelope['checksum']:
            raise PairwiseMeasurementError('Pairwise checkpoint checksum mismatch')
        return envelope['value']

    def _save(self, key, value):
        self.memory[key] = value
        if self.directory is None:
            return
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.directory / (key + '.json')
        temporary = path.with_suffix('.' + secrets.token_hex(8) + '.tmp')
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump({'value': value, 'checksum': fingerprint(value)}, stream, ensure_ascii=False)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _reference_key(self, case, trial):
        return fingerprint(['reference', self.binding, case.model_dump(mode='json'), trial])

    def reference(self, case, trial):
        saved = self._load(self._reference_key(case, trial))
        return OptimizationObservation.model_validate(saved['observation']) if saved is not None else None

    def artifact_key(self, case, observation, *, trial, execution_id):
        return fingerprint(['artifact', self.binding, execution_id, trial,
            case.model_dump(mode='json'), observation.model_dump(mode='json')])

    async def prepare(self, case, observation, *, trial=1, execution_id=""):
        from sagents.v2.optimization.native_episode import evaluation_episode_finished
        reason = execution_failure(observation, case)
        if reason is not None:
            receipt = failure_receipt(reason)
            self._save(self.artifact_key(case, observation, trial=trial, execution_id=execution_id), receipt)
            return receipt
        if not evaluation_episode_finished(observation, case):
            raise PairwiseMeasurementError("Unclassified execution is a missing pairwise measurement")
        from sagents.v2.optimization.comparison_plugin import ComparisonPreparationRequest, PreparedComparisonArtifact
        key = self.artifact_key(case, observation, trial=trial, execution_id=execution_id)
        saved = self._load(key)
        if saved is None:
            if self.plugin is None:
                saved = observation.output if observation.output.strip() else failure_receipt('empty_output')
            else:
                artifact_directory = (self.directory / 'artifacts' / key).absolute() if self.directory is not None else None
                if artifact_directory is not None:
                    artifact_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                request = ComparisonPreparationRequest(capture_id=key, goal=self.goal, case=case, observation=observation,
                    artifact_directory=str(artifact_directory) if artifact_directory is not None else None)
                try:
                    artifact = PreparedComparisonArtifact.model_validate(await self.plugin.prepare(request))
                    artifact.verify_files()
                    if artifact_directory is not None and any(not Path(item.path).resolve().is_relative_to(
                            artifact_directory.resolve()) for item in artifact.files):
                        raise PairwiseMeasurementError('Frozen files must be captured inside the supplied artifact_directory')
                except Exception as error:
                    error.rsi_authoritative_measurement_failed = True
                    raise
                saved = artifact.model_dump(mode='json')
                if artifact.execution_failure:
                    saved = {**failure_receipt(artifact.execution_failure), 'prepared_artifact': saved}
            self._save(key, saved)
        if is_failure(saved):
            return saved
        return PreparedComparisonArtifact.model_validate(saved) if self.plugin is not None else saved

    async def capture(self, case, observation, *, trial, execution_id):
        if case.mode != 'single_turn':
            raise PairwiseMeasurementError('Pairwise evaluation currently requires single-turn cases')
        if observation.evidence.get('generated_tool_audit', {}).get('passed') is False:
            raise PairwiseMeasurementError('Pairwise execution failed the generated-tool audit')
        artifact = await self.prepare(case, observation, trial=trial, execution_id=execution_id)
        failed = is_failure(artifact)
        return OptimizationGrade(score=0 if failed else .5, passed=not failed,
            rationale=('Target execution failed: ' + artifact['reason']) if failed else 'Artifact captured; comparison pending',
            scorer_details={'pairwise': {'pending': True, 'execution_failed': failed, 'trial': trial,
                'artifact_key': self.artifact_key(case, observation, trial=trial, execution_id=execution_id)}})

    async def grade(self, case, observation, *, trial, is_reference=False, execution_id=""):
        if case.mode != 'single_turn':
            raise PairwiseMeasurementError('Pairwise evaluation currently requires single-turn cases')
        if observation.evidence.get('generated_tool_audit', {}).get('passed') is False:
            raise PairwiseMeasurementError('Pairwise execution failed the generated-tool audit')
        existing = self._load(self._reference_key(case, trial)) if is_reference else None
        if existing is not None and existing['observation'] == observation.model_dump(mode='json'):
            return OptimizationGrade(score=0 if is_failure(existing['artifact']) else .5,
                passed=not is_failure(existing['artifact']),
                rationale='Failed baseline execution' if is_failure(existing['artifact']) else 'Fixed baseline self-reference; neutral preference, not an absolute quality grade',
                scorer_details={'pairwise': {'reference': True, 'trial': trial, 'artifact_key': existing['artifact_key']}})
        artifact = await self.prepare(case, observation, trial=trial, execution_id=execution_id)
        if is_reference:
            key = self._reference_key(case, trial)
            saved = self._load(key)
            artifact_key = self.artifact_key(case, observation, trial=trial, execution_id=execution_id)
            value = {'artifact_key': artifact_key, 'observation': observation.model_dump(mode='json'),
                'artifact': artifact.model_dump(mode='json') if self.plugin is not None and not is_failure(artifact) else artifact}
            if saved is not None and saved != value:
                raise PairwiseMeasurementError('Fixed pairwise reference changed')
            self._save(key, value)
            return OptimizationGrade(score=0 if is_failure(artifact) else .5, passed=not is_failure(artifact),
                rationale='Failed baseline execution' if is_failure(artifact) else 'Fixed baseline self-reference; neutral preference, not an absolute quality grade',
                scorer_details={'pairwise': {'reference': True, 'trial': trial, 'artifact_key': artifact_key}})
        reference = self.reference(case, trial)
        if reference is None:
            raise PairwiseMeasurementError('Missing same-case, same-trial baseline artifact')
        reference_key = self._load(self._reference_key(case, trial))['artifact_key']
        candidate_key = self.artifact_key(case, observation, trial=trial, execution_id=execution_id)
        return await self.compare_prepared(case, trial=trial, reference_key=reference_key, candidate_key=candidate_key)

    async def compare_prepared(self, case, *, trial, reference_key, candidate_key):
        reference_data, candidate_data = self._load(reference_key), self._load(candidate_key)
        if reference_data is None or candidate_data is None:
            raise PairwiseMeasurementError('Missing frozen comparison receipt')
        for data in (reference_data, candidate_data):
            if is_failure(data) and data.get('prepared_artifact'):
                from sagents.v2.optimization.comparison_plugin import PreparedComparisonArtifact
                PreparedComparisonArtifact.model_validate(data['prepared_artifact']).verify_files()
        if is_failure(reference_data) or is_failure(candidate_data):
            both = is_failure(reference_data) and is_failure(candidate_data)
            outcome = 'both_failed' if both else 'loss' if is_failure(candidate_data) else 'win'
            return OptimizationGrade(score=1. if outcome == 'win' else 0., passed=outcome == 'win',
                rationale='Both executions failed; not a quality tie.' if both else 'Completed execution beats failed execution.',
                scorer_details={'pairwise': {'outcome': outcome, 'trial': trial,
                    'execution_failure': True, 'reference_failure': reference_data if is_failure(reference_data) else None,
                    'candidate_failure': candidate_data if is_failure(candidate_data) else None,
                    'artifact_key': candidate_key, 'reference_artifact_key': reference_key,
                    'decisions': [], 'order_disagreement': False}})
        if self.plugin is not None:
            from sagents.v2.optimization.comparison_plugin import PreparedComparisonArtifact
            reference_artifact = PreparedComparisonArtifact.model_validate(reference_data)
            artifact = PreparedComparisonArtifact.model_validate(candidate_data)
        else:
            reference_artifact, artifact = reference_data, candidate_data
        if self.plugin is not None:
            reference_artifact.verify_files()
            artifact.verify_files()
        key = fingerprint(['judgment', self.binding, case.model_dump(mode='json'), trial,
            reference_key, candidate_key])
        saved = self._load(key) or {'candidate_first': bool(secrets.randbits(1)), 'decisions': []}
        self._save(key, saved)
        for index in range(len(saved['decisions']), 2):
            candidate_first = saved['candidate_first'] != bool(index)
            outputs = [artifact, reference_artifact] if candidate_first else [reference_artifact, artifact]
            if self.plugin is not None:
                from sagents.v2.optimization.comparison_plugin import ComparisonRequest
                for item in outputs:
                    item.verify_files()
                request = ComparisonRequest(goal=self.goal, case=case, A=outputs[0], B=outputs[1])
                try:
                    decision = PairwiseDecision.model_validate(await self.plugin.compare(request))
                except Exception as error:
                    error.rsi_authoritative_measurement_failed = True
                    raise
                for item in outputs:
                    item.verify_files()
            else:
                payload = {'input': case.input, 'rubric': case.rubric, 'reference_answer': case.reference_answer,
                    'A': outputs[0], 'B': outputs[1]}
                decision = PairwiseDecision.model_validate(await self.judge(payload, case))
            outcome = ('tie' if decision.winner == 'tie' else
                'win' if (decision.winner == 'A') == candidate_first else 'loss')
            saved['decisions'].append({'outcome': outcome, 'rationale': decision.rationale,
                'candidate_side': 'A' if candidate_first else 'B',
                'analysis': decision.analysis.model_dump(mode='json') if decision.analysis else None})
            self._save(key, saved)
        decisions = saved['decisions']
        disagreement = decisions[0]['outcome'] != decisions[1]['outcome']
        outcome = 'tie' if disagreement else decisions[0]['outcome']
        details = {'outcome': outcome, 'trial': trial, 'order_disagreement': disagreement,
            'decisions': decisions, 'reference_artifact_key': reference_key, 'artifact_key': candidate_key}
        analysis = decisions[0].get('analysis')
        if analysis:
            analysis = OptimizationDiagnosis.model_validate(analysis)
            analysis = analysis.model_copy(update={'summary':
                f"Candidate is side {decisions[0]['candidate_side']} in this analysis. " + analysis.summary[:1900]})
            if disagreement:
                analysis = analysis.model_copy(update={'next_action': 'measure',
                    'uncertainties': (*analysis.uncertainties[:3], 'Presentation orders disagree; no reliable preference established.')})
        return OptimizationGrade(diagnosis=analysis, score={'win': 1., 'tie': .5, 'loss': 0.}[outcome],
            passed=outcome != 'loss', rationale=('Presentation orders disagree; counted as a tie. ' if disagreement else '')
                + ' | '.join(d['rationale'] for d in decisions), scorer_details={'pairwise': details})



async def compare_evaluations(engine, previous, candidate, *, max_concurrency=1):
    if type(max_concurrency) is not int or not 1 <= max_concurrency <= 16:
        raise ValueError('Comparison concurrency must be an integer between 1 and 16')
    old_by_id = {item.case.id: item for item in previous.cases}

    async def compare_case(current):
        old = old_by_id.get(current.case.id)
        if old is None:
            raise PairwiseMeasurementError('Missing incumbent execution for comparison case')
        if old.case != current.case:
            raise PairwiseMeasurementError('Comparison case definitions differ')
        old_trials, new_trials = old.trials or (old,), current.trials or (current,)
        if len(old_trials) != len(new_trials):
            raise PairwiseMeasurementError('Comparison requires equal repeated-trial counts')
        grades = []
        for index, (before, after) in enumerate(zip(old_trials, new_trials, strict=True), 1):
            reference_key = before.grade.scorer_details.get('pairwise', {}).get('artifact_key')
            candidate_key = after.grade.scorer_details.get('pairwise', {}).get('artifact_key')
            if not reference_key or not candidate_key:
                raise PairwiseMeasurementError('Comparison requires frozen per-trial artifacts')
            grades.append(await engine.compare_prepared(current.case, trial=index,
                reference_key=reference_key, candidate_key=candidate_key))
        from sagents.v2.optimization.contracts import OptimizationCaseTrial
        updated_trials = tuple(sample.model_copy(update={'grade': grade}) for sample, grade in zip(new_trials, grades, strict=True))
        summary_grade = grades[0] if not current.trials else OptimizationGrade(
            score=sum(g.score for g in grades) / len(grades), passed=all(g.passed for g in grades),
            rationale='Mean paired preference against the incumbent; not a cumulative score',
            scorer_details={'pairwise_summary': comparison_summary(grades)})
        evaluated = current.model_copy(update={'grade': summary_grade,
            'trials': tuple(OptimizationCaseTrial.model_validate(t.model_dump(mode='json', exclude={'case', 'trials', 'contrast'}))
                for t in updated_trials) if current.trials else ()})
        return current, grades, evaluated

    from sagents.v2.optimization.call_isolation import settle_cases
    results = await settle_cases(candidate.cases, compare_case, max_concurrency=max_concurrency,
        stop_on_error=lambda error: True)
    by_split, training, evaluated = {}, [], []
    for current, grades, result in results:
        evaluated.append(result)
        by_split.setdefault(current.case.split, []).append(grades)
        if current.case.split == 'training':
            training.append({'case_id': current.case.id, 'trials': [g.model_dump(mode='json') for g in grades]})
    summaries = {}
    for split, cases in by_split.items():
        summary = comparison_summary(g for grades in cases for g in grades)
        summary['preference_score'] = sum(sum(g.score for g in grades) / len(grades) for grades in cases) / len(cases)
        summaries[split] = summary
    if 'validation' not in summaries:
        raise PairwiseMeasurementError('Comparison requires independent validation pairs')
    compared = candidate.model_copy(update={'cases': tuple(evaluated), 'comparison_reference_hash': previous.package_hash})
    return {'reference_package_hash': previous.package_hash, 'splits': summaries, 'training': training}, compared


def comparison_training_feedback(comparison, max_chars=12000):
    """Bound training-only comparison reasons; never return dev identities or evidence."""
    result, used = [], 0
    for item in comparison.get('training', [])[:16]:
        grades = [OptimizationGrade.model_validate(g) for g in item['trials']]
        entry = {'case_id': item['case_id'], 'outcomes': comparison_summary(grades),
            'reasons': [g.rationale[:800] for g in grades[:3]]}
        size = len(json.dumps(entry, ensure_ascii=False))
        if used + size > max_chars:
            break
        result.append(entry)
        used += size
    return result
