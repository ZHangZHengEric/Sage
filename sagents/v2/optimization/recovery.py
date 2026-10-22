"""Index durable optimization evidence without replaying any external effect.

Only explicitly completed cases and internal calls can be reused. An unresolved
execution is a reconciliation requirement, never implicit permission to rerun it.
"""
from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import json
from pathlib import Path

from sagents.v2.optimization.contracts import OptimizationAgentCall, OptimizationCaseResult, OptimizationObservation


class OptimizationRecoveryRequired(RuntimeError):
    """An interrupted execution has an unknown outcome that needs host resolution."""


class OptimizationTransientFailure(RuntimeError):
    """Transport interrupted an unscored execution; its outcome is not a grade."""


def configuration_fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


_ENGINE_ID = None


def engine_fingerprint():
    # Works with source trees, zip imports and bundled bytecode. Cache per
    # process so editing files cannot relabel already-loaded running code.
    global _ENGINE_ID
    if _ENGINE_ID is None:
        import importlib.util
        import marshal
        names = [f"sagents.v2.optimization.{name}" for name in ('optimizer', 'contracts', 'feedback',
                 'principles', 'generator', 'runner', 'recovery', 'diagnostics', 'evidence', 'package_workspace', 'scoring', 'dataset', 'environment', 'scorer_runtime', 'python_scorer', 'python_scorer_worker', 'evaluation_files', 'execution_records')]
        names.append('sagents.v2.tool.generated')
        hashes = {}
        for name in names:
            spec = importlib.util.find_spec(name)
            if spec is None or spec.loader is None:
                raise ValueError("optimization engine module unavailable")
            loader = spec.loader
            source = loader.get_source(name) if hasattr(loader, 'get_source') else None
            payload = source.encode() if source is not None else marshal.dumps(loader.get_code(name))
            hashes[name] = hashlib.sha256(payload).hexdigest()
        _ENGINE_ID = configuration_fingerprint(hashes)
    return _ENGINE_ID


def case_key(package_hash, phase, round, trial, case_id):
    return (package_hash, phase, round, trial, case_id)


def call_key(data):
    return (data['role'], data.get('phase', 'optimization'), data.get('round', 0),
            data.get('trial', 1), data.get('case_id'), data['request'])


class OptimizationRecovery:
    def __init__(self, path, *, readonly_roles=(), local_package_editor=False):
        self.path = Path(path).resolve()
        self.operation = None
        self.cases = defaultdict(deque)
        self.calls = defaultdict(deque)
        self._consumed_calls = set()
        self.unresolved = []
        self.designs = defaultdict(deque)
        self.pending_observations = defaultdict(deque)
        self.recovered_agent_calls = []
        self.suite = None
        targets, agents, active_cases = {}, {}, {}
        finished_targets, case_calls = {}, defaultdict(list)
        lines = self.path.read_text().splitlines()
        for index, line in enumerate(lines):
            try:
                event = json.loads(line)
            except ValueError:
                # A crash may leave a partial final write. Earlier corruption
                # cannot be hidden by treating it as an interrupted tail.
                if index == len(lines) - 1:
                    break
                raise ValueError('corrupt optimization journal before final line') from None
            name, data = event['event'], event['data']
            if name == 'operation_started':
                if self.operation is not None:
                    raise ValueError('recovery journal has multiple operations')
                self.operation = data
            elif name == 'target_call_started':
                targets[data['call_id']] = data
                group = (data.get('phase', 'optimization'), data.get('round', 0),
                         data.get('trial', 1), data['case_id'])
                active_cases[group] = case_key(data['package_hash'], *group)
            elif name == 'target_call_completed':
                if data['call_id'] not in targets:
                    raise ValueError('target completion has no matching start')
                finished_targets[data['call_id']] = OptimizationObservation.model_validate(data['observation'])
            elif name == 'agent_call_started':
                agents[data['call_id']] = data
                group = (data.get('phase', 'optimization'), data.get('round', 0),
                         data.get('trial', 1), data.get('case_id'))
                if group in active_cases:
                    case_calls[active_cases[group]].append(data['call_id'])
            elif name == 'agent_call_completed':
                start = agents.get(data['call_id'])
                if start is None:
                    raise ValueError('agent completion has no matching start')
                observation = OptimizationObservation.model_validate(data['observation'])
                if observation.state == 'completed':
                    self.calls[call_key(start)].append((data['call_id'], observation))
            elif name in {'test_design_call_completed', 'final_test_design_call_completed'}:
                call = OptimizationAgentCall.model_validate(data['call'])
                if call.observation.state == 'completed':
                    self.designs[call.request].append(call.observation)
            elif name == 'suite_fixed' and self.suite is None:
                self.suite = data['suite']
            elif name == 'case_completed':
                result = OptimizationCaseResult.model_validate(data['result'])
                group = (data.get('phase', 'optimization'), data.get('round', 0),
                         data.get('trial', 1), result.case.id)
                identity = active_cases.pop(group, None)
                if data.get('package_hash'):
                    identity = case_key(data['package_hash'], *group)
                if identity is None:
                    raise ValueError('completed case has no target execution identity')
                consumed = tuple(case_calls.pop(identity, ()))
                records = [OptimizationAgentCall.model_validate(call) for call in data.get('agent_calls', [])]
                if not records:
                    for call_id in consumed:
                        start = agents[call_id]
                        for saved_id, observation in self.calls[call_key(start)]:
                            if saved_id == call_id:
                                records.append(OptimizationAgentCall(role=start['role'], observation=observation,
                                    request=start['request'], round=start.get('round', 0), trial=start.get('trial', 1),
                                    phase=start.get('phase', 'optimization'), case_id=start.get('case_id')))
                self.cases[identity].append((result, consumed, records))
        if self.operation is None:
            raise ValueError('recovery journal has no operation configuration')
        def transport_failed(observation):
            return observation.state == 'failed' and (observation.evidence.get('error') or {}).get('code') == 'model.provider_transient'
        self.unresolved = [value for identity, value in targets.items()
                           if identity not in finished_targets or transport_failed(finished_targets[identity])]
        self.pending_case_keys = set(active_cases.values())
        for call_id, observation in finished_targets.items():
            call = targets[call_id]
            identity = case_key(call['package_hash'], call.get('phase', 'optimization'),
                call.get('round', 0), call.get('trial', 1), call['case_id'])
            if identity in self.pending_case_keys and not transport_failed(observation):
                self.pending_observations[identity].append(observation)
        completed_agents = {identity for queue in self.calls.values() for identity, _ in queue}
        role_names = {'evaluation': 'evaluator', 'tuning': 'tuner', 'semantic_review': 'reviewer',
                      'suite_review': 'suite_reviewer', 'test_dialogue': 'test_driver'}
        for identity, call in agents.items():
            if identity in completed_agents:
                continue
            role = (self.operation.get('internal_agents') or {}).get(role_names.get(call['role'], ''), {})
            for definition in role.get('package', {}).get('manifest', {}).get('agents', {}).values():
                if (definition.get('tools') and call['role'] not in readonly_roles
                        and not (local_package_editor and call['role'] == 'tuning'
                                 and set(definition['tools']) <= {'file_read', 'file_write', 'file_update'})):
                    raise OptimizationRecoveryRequired('unfinished internal Agent has tool access; reconcile before recovery')

    def verify(self, expected):
        actual = {key: self.operation.get(key) for key in expected}
        if configuration_fingerprint(actual) != configuration_fingerprint(expected):
            raise ValueError('optimization recovery configuration differs')

    def require_reconciled(self, *, restart_incomplete=False):
        if self.unresolved and not restart_incomplete:
            raise OptimizationRecoveryRequired(
                f'{len(self.unresolved)} target executions have unknown outcomes; host reconciliation is required')

    def completed_case(self, package_hash, *, phase, round, trial, case_id):
        queue = self.cases.get(case_key(package_hash, phase, round, trial, case_id))
        if not queue:
            return None
        result, consumed, records = queue.popleft()
        self.recovered_agent_calls = records
        self._consumed_calls.update(consumed)
        return result.model_copy(deep=True)

    def completed_call(self, *, role, phase, round, trial, case_id, request):
        queue = self.calls.get(call_key(dict(role=role, phase=phase, round=round,
                                           trial=trial, case_id=case_id, request=request)))
        while queue:
            identity, observation = queue.popleft()
            if identity not in self._consumed_calls:
                self._consumed_calls.add(identity)
                return observation.model_copy(deep=True)
        expected_key = call_key(dict(role=role, phase=phase, round=round, trial=trial,
                                     case_id=case_id, request=request))
        if any(key[:-1] == expected_key[:-1] and any(identity not in self._consumed_calls for identity, _ in queue)
               for key, queue in self.calls.items()):
            raise ValueError("recovery internal request differs from completed decision")
        return None

    def observation(self, package_hash, *, phase, round, trial, case):
        identity = case_key(package_hash, phase, round, trial, case.id)
        if case.mode == "dialogue" and identity in self.pending_case_keys:
            raise OptimizationRecoveryRequired("partial dialogue requires host reconciliation or a disposable restart grant")
        queue = self.pending_observations.get(identity)
        return queue.popleft().model_copy(deep=True) if queue else None

    def design(self, request):
        queue = self.designs.get(request)
        return queue.popleft().model_copy(deep=True) if queue else None

    def assert_consumed(self):
        if any(self.cases.values()) or any(self.designs.values()):
            raise ValueError("recovery did not consume all completed development evidence")
        if any(identity not in self._consumed_calls for queue in self.calls.values() for identity, _ in queue):
            raise ValueError("recovery did not consume all completed internal decisions")
