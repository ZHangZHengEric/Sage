---
layout: default
title: Agent Package Optimization (RSI)
parent: Applications
nav_order: 4
lang: en
ref: v2-applications-RSI
---

{% include lang_switcher.html %}

# Agent Package Optimization (RSI)

RSI improves a supplied Agent package over a configurable number of proposal rounds.
It uses the existing model and host-bound capabilities; it does not train model
weights or automatically replace the original Agent. Use the independent Python
API or launch a background job from Desktop Agent settings.

## The loop

1. Supply a package, authorized goal, editable scope, and test suites. A test-design
   Agent can generate suites when they are omitted. Single-turn tasks and bounded
   multi-turn conversations are supported.
2. Independently generate and fix validation questions (24 by default, configurable),
   and generate initial training questions. Every round adds training challenges.
   A suite-review Agent checks goal, rubric, permissions and executable fixtures;
   it does not judge leakage or memorization.
3. Run the baseline in fresh target Sessions. A separate evaluation Session judges
   each case using its rubric and the target's actual observations.
4. A tuning Agent proposes an in-scope patch using training feedback. A separate
   semantic-review Session checks for goal drift and permission
   drift before testing the candidate. Original instructions remain preserved;
   editable instruction guidance is an additional section.
5. Compare both packages on identical accumulated questions. Retain candidates
   whose overall score improves enough: training and validation means have equal
   weight. Individual regressions are recorded and training regressions remain
   repair targets while subsequent rounds start from the stronger package.
6. Confirm target success with a fresh full evaluation, or stop for stagnation,
   round or time limits. Keep the stronger package even without verified success,
   withhold its recommendation, and never apply it automatically. The default
   workflow has no final exam.

Each internal Agent invocation uses a fresh Session. Tuning receives validation
aggregates and anonymous per-question scores, never validation inputs, original
IDs, answers or grading rationale. Repeated validation selection does not establish
unseen-task quality. Freeze candidates before an external benchmark measurement.
Explicit `validation_case_count=None` preserves the historical fixed-suite and
optional final-evaluation path for legacy SDK clients only.

Desktop now defaults to 12 independently generated test cases alongside 24 fixed dev cases and expanding training cases. Configure `human_test_count` from 0 (off) to 100, or supply `human_test_suite` with `split=test`. The API defaults to 0 for existing clients.

`HumanTestObserver` consumes baseline and round events, measures the retained package in fresh sessions, and stores results outside the optimizer report and Agent history. No test score reaches proposal, selection, or stopping logic. The dashboard shows train/dev/test curves and selectable per-round dot matrices; missing or failed measurements stay unscored. Both workloads share the configured call-concurrency ceiling. Human steering based on test outcomes makes that test development evidence and must be disclosed.

See the [τ-bench experiment protocol](TAU_BENCH.md) for external benchmark measurement.

## Python API and editable scope

See the [complete API and examples](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/optimization/README.md).
`AgentPackageTestGenerator` also generates a reviewable question set independently
of optimization. Callers may instead supply their own `OptimizationSuite` and
`OptimizationFinalSuite`.

`optimize(..., rounds=10, optimization_scope=("skills",), constraints=...)`
limits changes to the requested parts. Parts are `instructions`, `skills`, `tools`,
`budgets`, and `resources`; combine them as needed. Scope does not grant file or
capability access: constraints must separately allow each editable file, new path,
Tool/Skill candidate, and budget field. New Tool/Skill names require working,
authorized host bindings. Tool source implementations, model routes, credentials,
policies, and flow definitions remain protected.

Configure `suite_reviewer=OptimizationAgent(...)` to use a dedicated review
package/model route. Otherwise the evaluator package runs with host audit
principles in a fresh Session. A blocking audit raises
`OptimizationSuiteReviewRejected` before any target/tuner invocation; its `review`
and `call` retain the evidence. Successful reports retain `suite_review`.

`result.iterations` contains iteration zero and every valid candidate, with complete
packages, patches, reviews and available test records. Invalid proposals remain
in the report without an executable package. Opt-in `journal_path` records progress
and partial evidence on failure; an aborted run has no normal result and is not
automatically replayed. Model-facing feedback bounds diagnostic excerpts and prior
attempts while preserving full caller-visible records. Set host token/resource
budgets as well as round counts and deadlines; excerpt limits are not a total
prompt budget.

## Desktop history and confirmation

Agent settings expose separate **RSI** and **Version history** entries. The RSI
page contains background run histories and each run's candidate iterations. The
Agent-level version history contains manually saved and explicitly applied
configuration versions. Unapplied RSI candidates stay inside their run.

Leaving the page does not stop the sidecar job. Reopening displays persisted
progress, test observations and audit findings. Sidecar exit marks unfinished jobs
as interrupted; unknown model/tool outcomes are not automatically replayed.

Optimization does not update the active configuration. A user must preview a
version, select **Use this version**, and explicitly confirm. The backend checks
the current configuration fingerprint before applying it and rejects unfinished
or semantically rejected candidates. Per-version final-test status remains visible
when users choose a completed iteration other than the selected candidate.

Desktop currently supports simple Agents with native tools, temporary workspaces,
and host sandbox restrictions. Shell test bindings, MCP and non-simple Agents are
not supported by this workflow. Persistence is owned by one sidecar; distributed
job takeover and automatic checkpoint resume are not provided. See the
[Desktop implementation guide](https://github.com/ZHangZHengEric/Sage/blob/main/app/v2/desktop/README.md#rsi-与-agent-版本).

## Real-model experiments

The opt-in [domain benchmark](https://github.com/ZHangZHengEric/Sage/blob/main/examples/v2/optimizer_domains.py)
uses an explicitly supplied JSON model catalog (`--catalog`) with an
`openai-responses` provider and makes billable calls.
It exports the original package, every iteration package, suites, model-call and
Session evidence, evaluations, reviews, and a comparison summary. Credentials are
resolved in memory; output folders must be new. No production Agent is activated.

Skill-only and tool-selection runs each improved to 3/3 final cases in the
2026-10-12 experiments. The joint scope also reached 3/3 but changed only a Skill;
simultaneous instruction-and-Skill edits were not demonstrated. All three used
four proposal rounds, with no changes after the first accepted candidate. The
Skill/tool final fixtures were reused from a previous study and measure regression;
only the clarified joint run used newly sealed final fixtures. Keep failed runs and
audit rejections when assessing these results. They do not certify general RSI
reliability.
