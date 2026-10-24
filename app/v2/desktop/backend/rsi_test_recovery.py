"""Host-only recovery of interrupted human checkpoints; no tuning input."""

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from sagents.v2.optimization.contracts import (
    OptimizationGrade,
    OptimizationDialogueReply,
)
from sagents.v2.optimization.observer import (
    HumanTestObserver,
    IsolatedTestEvaluator,
    _measurement_retry,
    _MEASUREMENT_IDENTITY,
)


def persist_human_evidence(path, records):
    """A resumed observer's new rows must not erase completed private evidence."""
    path = Path(path)
    previous = json.loads(path.read_text()) if path.exists() else []
    if not isinstance(previous, list):
        raise ValueError('Human evidence must be a record list')
    merged = {}
    for record in [*previous, *records]:
        key = (record['round'], record['package_hash'], record['case_id'], record['trial'])
        old = merged.get(key)
        if old is not None and old.get('conversation') != record.get('conversation'):
            raise ValueError('Completed human execution evidence differs')
        merged[key] = record
    # Never truncate the only copy of previously completed private evidence.
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps(list(merged.values()), ensure_ascii=False))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def resumable_human_test_observer(*, completed_records=(), **kwargs):
    original_evaluate = kwargs.pop("evaluate")
    resume_measurement = getattr(original_evaluate, "resume_measurement", None)
    records = deepcopy(list(completed_records))
    rounds = [record["round"] for record in records]
    if len(rounds) != len(set(rounds)):
        raise ValueError("duplicate human checkpoint round")
    expected_ids = {case.id for case in kwargs["suite"].cases}
    repeats = kwargs.get("repeats", 1)
    terminal, pending = [], {}
    for record in records:
        recoverable_error = record.get("status") == "error" and any(
            trial.get("status") == "error" and (trial.get("grade") is None or resume_measurement is not None)
            for row in record.get("cases", ())
            for trial in row.get("trials", ())
        )
        if (
            record.get("status") in {"completed", "error", "invalid"}
            and not recoverable_error
        ):
            terminal.append(record)
            continue
        if (
            record.get("status") not in {"queued", "running", "cancelled"}
            and not recoverable_error
        ):
            raise ValueError("unknown human checkpoint status")
        if record.get("valid") is False:
            record.update(status="invalid")
            terminal.append(record)
            continue
        rows = record.get("cases", [])
        if (
            len(rows) != len(expected_ids)
            or {row["id"] for row in rows} != expected_ids
            or record.get("repeats") != repeats
        ):
            raise ValueError("interrupted human checkpoint suite differs")
        if resume_measurement is None and any(
            trial.get("status") != "completed" and trial.get("grade") is not None
            for row in rows
            for trial in row.get("trials", ())
        ):
            raise ValueError(
                "scored interrupted trial requires diagnosis-only recovery"
            )
        cached = {}
        for row in rows:
            trials = row.get("trials", [])
            if len(trials) != repeats or {trial["trial"] for trial in trials} != set(
                range(1, repeats + 1)
            ):
                raise ValueError("interrupted human checkpoint trials differ")
            for trial in trials:
                if trial.get("status") != "completed" and trial.get('grade') is None:
                    continue
                grade = OptimizationGrade.model_validate(trial["grade"])
                if (
                    trial.get("score") != grade.score
                    or trial.get("passed") != grade.passed
                ):
                    raise ValueError("completed human trial grade differs")
                cached[(row["id"], trial["trial"])] = {
                    "grade": grade.model_dump(mode="json"),
                    "conversation": deepcopy(trial.get("conversation", [])),
                    "infrastructure_retries": deepcopy(
                        trial.get("infrastructure_retries", {})
                    ),
                    "recovered_measurement": True,
                    "diagnosis_pending": trial.get('status') != 'completed',
                }
        pending[record["round"]] = (record["package_hash"], cached)
    observer = None

    async def evaluate(package, case):
        identity = _MEASUREMENT_IDENTITY.get()
        if identity is None:
            raise ValueError("human checkpoint execution has no measurement identity")
        checkpoint_round, trial = identity
        old = pending.get(checkpoint_round)
        if old is not None:
            package_hash, cached = old
            if package.content_hash != package_hash:
                raise ValueError("interrupted human checkpoint package differs")
            result = cached.get((case.id, trial))
            if result is not None:
                if result.get('diagnosis_pending'):
                    return await resume_measurement(package, case, deepcopy(result))
                return deepcopy(result)
        return await original_evaluate(package, case)

    observer = HumanTestObserver(
        completed_records=terminal, evaluate=evaluate, **kwargs
    )
    return observer


def completed_checkpoint_events(baseline, result, *, saved_records=()):
    """Reconstruct only predeclared human checkpoints after optimization ends.

    Validate every identity before returning any events. This does not run or
    resume the optimizer, call a tuner, select a package, or inspect test scores.
    """
    if baseline.content_hash != result.report.baseline.package_hash:
        raise ValueError("completed experiment baseline differs")
    current = baseline
    expected = {0: baseline.content_hash}
    events = [
        {
            "event": "suite_fixed",
            "data": {"suite": result.report.suite.model_dump(mode="json")},
        },
        {
            "event": "evaluation_completed",
            "data": {
                "round": 0,
                "evaluation": result.report.baseline.model_dump(mode="json"),
            },
        },
    ]
    last = 0
    for record in result.report.rounds:
        if record.round <= last or record.parent_hash != current.content_hash:
            raise ValueError("completed experiment checkpoint chain differs")
        candidate, evaluation = record.candidate_package, record.evaluation
        if evaluation is not None and (
            candidate is None or evaluation.package_hash != candidate.content_hash
        ):
            raise ValueError("completed experiment candidate evaluation differs")
        if record.accepted:
            if candidate is None or evaluation is None:
                raise ValueError("accepted checkpoint is incomplete")
            current = candidate
        expected[record.round] = current.content_hash
        events.append(
            {
                "event": "round_completed",
                "data": {"record": record.model_dump(mode="json")},
            }
        )
        last = record.round
    if (
        current.content_hash != result.candidate_package.content_hash
        or current.content_hash != result.report.selected.package_hash
    ):
        raise ValueError("completed experiment retained package differs")
    seen = set()
    for record in saved_records:
        number = record["round"]
        if (
            number in seen
            or number not in expected
            or record.get("package_hash") != expected[number]
        ):
            raise ValueError("saved human checkpoint differs from completed experiment")
        seen.add(number)
    return tuple(deepcopy(events))


class RecoveringIsolatedTestEvaluator(IsolatedTestEvaluator):
    """Repair read-only driver JSON without repeating a target execution.

    Host compatibility for frozen experiments: scoring and target semantics stay
    in the unchanged SDK evaluator. Only an invalid tool-free driver reply is
    regenerated with the same authorized user context and schema.
    """

    async def _ask(self, agent, task, data, schema):
        if (
            schema is not OptimizationDialogueReply
            or agent is not self.driver
            or agent.package.manifest.agents[agent.agent_id].tools
        ):
            return await super()._ask(agent, task, data, schema)
        source = data
        for attempt in range(3):
            try:
                reply = await super()._ask(agent, task, data, schema)
                if reply.can_continue and not reply.message.strip():
                    error = ValueError(
                        "can_continue=true requires a nonempty message; use false if no continuation is possible"
                    )
                    error.rsi_failure_metadata = {
                        "phase": "dialogue",
                        "code": "evaluation.invalid_record",
                        "retryable": False,
                    }
                    raise error
                return reply
            except ValueError as error:
                failure = getattr(error, "rsi_failure_metadata", {})
                if failure.get("code") != "evaluation.invalid_record" or attempt == 2:
                    raise
                _measurement_retry("dialogue_format")
                data = {"original_data": source, "validation_error": str(error)[:6000]}
                task = (
                    "Return valid JSON matching response_schema using original_data as "
                    "the complete authorized user context and conversation. Preserve the "
                    "original user goal; do not invent facts, preferences or consent. "
                    "Correct the response format without sending messages to the target."
                )
