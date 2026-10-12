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
2. Seal the independent final suite before baseline execution. A suite-review
   Agent audits both suites against the goal in its own Session. Conflicting
   rubrics, untestable fixtures, or concrete answer leakage can block the run.
   Advisory coverage gaps remain visible without blocking execution.
3. Run the baseline in fresh target Sessions. A separate evaluation Session judges
   each case using its rubric and the target's actual observations.
4. A tuning Agent proposes an in-scope patch using training feedback. A separate
   semantic-review Session checks for memorization, goal drift, and permission
   drift before testing the candidate. Original instructions remain preserved;
   editable instruction guidance is an additional section.
5. Compare the candidate against the retained best version on the fixed training
   and validation suites. Require improvement on non-saturated splits and no
   individual-case regression. Retain rejected and no-change rounds in the report.
6. After the requested rounds, test the selected version and baseline on the
   sealed final suite. Return complete iteration packages and evidence for the
   caller to inspect and choose from.

Each internal Agent invocation uses a fresh Session. Training feedback excludes
validation/final cases, their grades, and suite-audit findings. Final results do
not become another tuning round. Model judgments are evidence-based estimates;
small suites and repeated validation selection do not establish general quality.

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

The opt-in [domain benchmark](https://github.com/ZHangZHengEric/Sage/blob/main/examples/sagents_v2_optimizer_domains.py)
uses Yiii's locally configured GPT-6.1 Sol Responses route and makes billable calls.
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
