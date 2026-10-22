---
layout: default
title: τ-bench and RSI Experiments
parent: Applications
nav_order: 6
lang: en
ref: v2-applications-TAU_BENCH
---

{% include lang_switcher.html %}

# τ-bench Dataset and Sage RSI Experiments

Written on 2026-10-21; completed results updated on 2026-10-22.

τ-bench tests whether a target can understand a simulated user, follow policy, call tools, and leave the environment in the required state. Sage uses it to measure whether RSI improves a fixed target model on tasks excluded from tuning. Local evaluation does not require a leaderboard submission.

## Completed local measurements

The selection-feedback experiment completed 320 frozen measurements: 40 official retail test tasks, four trials each, for the default gpt-5.6-luna Package and its RSI candidate. A default gpt-6.1-sol reference separately completed 160 measurements under the same explicit conditions.

| Target | pass¹ across 160 trials | pass⁴ across 40 tasks |
| --- | ---: | ---: |
| Default gpt-5.6-luna | 75.000%, 120/160 | 57.50%, 23/40 |
| gpt-5.6-luna after RSI | 83.125%, 133/160 | 65.00%, 26/40 |
| Default gpt-6.1-sol | 76.250%, 122/160 | 62.50%, 25/40 |

The candidate gained 8.125 percentage points in pass¹ and 7.50 points in pass⁴. Paired trials contain 28 improvements, 15 regressions, 105 shared successes, and 12 shared failures. Per-task four-trial means improved on 11 tasks, regressed on 6, and stayed unchanged on 23. Completed scored failures were retained rather than rerun to select a better result.

Train/dev alone selected the candidate. Rounds 1 and 3 were accepted; rounds 4–6 did not improve sufficiently, so stagnation retained round 3. Its development scores were train 28/30 and dev 11/12. `goal_verified=false` records that the stable-success requirement was not met.

These observations do not establish general RSI reliability or stable superiority over another model. An earlier repeated baseline differed by 6.25 pass¹ points and 17.50 pass⁴ points. Models use different inference defaults; the target received stronger-model tuning, and development resumed across a disclosed transport repair. The comparison is not equal-compute or a clean attribution to one feedback change.

The run audit checked all 320 measurement identities, four-trial coverage, frozen Package hashes, and paired seeds. Six tuning requests contained only anonymous dev scores; test tasks were absent from RSI execution. Twenty-four unscored failed attempts remain recorded. A failed baseline human checkpoint stays missing rather than zero. Fourteen Sage native tools and sixteen domain tools were retained without web search.

The compact public evidence file `docs/assets/benchmarks/tau-retail-rsi.json` retains all 320 task/trial measurements, frozen hashes, paired outcomes, and disclosed implementation adjustments. Full trajectories, evaluator calls, failed attempts, and replay media remain with the original experiment artifacts; checkpoint videos replay saved records rather than live execution.

## What is measured

A task can require several dialogue turns, clarification, policy reasoning, and database operations. A model simulates the user, and tools act on a local simulated database. No real refund, booking, or customer account is changed. Success is determined by external evaluation, not the target's claim that it finished.

## Version and domains

This experiment pins sierra-research/tau2-bench v1.0.1 at `fc0055dc4e0a316c3f83133267fbd6faaa770992`. Benchmark naming spans τ-bench and later generations; versions and task sets must not be mixed when comparing percentages.

| Domain | Typical tasks | v1.0.1 standard split |
| --- | --- | --- |
| retail | Orders, cancellation, changes, returns, exchanges | base 114; train 74; test 40 |
| airline | Booking, changes, cancellation, policy | base 50; train 30; test 20 |
| telecom | Account/device troubleshooting and collaboration | base 114; train 74; test 40 |
| banking_knowledge | Retrieval and financial support tasks | Not evaluated here |

Counts come from the pinned split files. Base includes train and test; the 40-task external retail test measurement is not a full-base leaderboard result. Telecom also has a larger full set.

## Task execution

1. The host creates an isolated environment and initial database state.
2. The user simulator presents its private scenario and answers clarification.
3. The target receives public policy, tool definitions, and the actual conversation.
4. Domain tools execute until completion or the configured budget.
5. Official evaluation checks the conversation and resulting state.

The target must not receive private simulator scenarios, reference actions, target database states, or grading conditions. Public policy and tool documentation are legitimate inputs; disclosed test answers are leakage.

## Tools and network access

All sixteen official retail tools are bound to the simulated database. They cover identity lookup, order/product queries, address/payment/item changes, cancellation, returns, exchanges, calculation, and human handoff. They need neither a search API nor real commerce integrations.

The target also retains fourteen default Sage tools for files, planning, Shell, and Skills. File operations are restricted to a task workspace; Shell execution was not granted. Web search and scraping were disabled. Network use primarily consists of target, user-simulator, and natural-language-judge model calls.

## Grading

Each task's `reward_basis` selects grading components, which are multiplied. Database evaluation compares final state with the state produced by reference actions; those actions need not be the only valid path. Action matching applies only when ACTION is selected.

| Component | Check |
| --- | --- |
| DB | Final simulated database state |
| ENV_ASSERTION | Task-specific environment assertions |
| COMMUNICATE | Required information in target messages |
| NL_ASSERTION | Model-judged natural-language requirements |
| ACTION | Required action/arguments when enabled |

The pinned retail data uses DB and NL_ASSERTION for 112 tasks and DB alone for 2. Consult the actual task configuration rather than assuming one documented default covers every task. Model judging varies; retain judgments and inspect trajectories alongside database results.

## Success and reliability

Single-trial success measures task completion in one run. `pass^k` concerns the same task succeeding on all k trials; it differs from `pass@k`, which measures at least one success across attempts. Report step limits, tool errors, and infrastructure failures separately. Do not silently discard failures, and do not report full pass⁴ before four trials are complete.

## Information separation

### Product train, dev, and test permissions

The three collections describe information access and purpose, not necessarily the benchmark's original split labels.

| Collection | Optimization access | Human view | Automatic optimization |
| --- | --- | --- | --- |
| train | Questions, execution evidence, grades, feedback | Cases, trajectories, scores | Drives diagnosis and repair; may expand |
| dev | Aggregates and stable anonymous per-case scores | Scores and changes | Drives candidate selection and stopping |
| test | No questions, trajectories, feedback, or scores | Independent scores, dot matrices, progress | Observation only |

The measured target still receives test-user requests in isolated evaluation Sessions. Their memory and evidence must not return to tuning. Simulators and evaluators receive only the access their roles require.

The same boundary applies to RSI's stdio MCP interface: detailed status/history/version reads cannot disclose hidden dev questions or test scores. `rsi_questions` returns training questions and dev counts. MCP callers can choose collection sizes but cannot supply hidden suites. Complete Desktop human responses are not forwarded unchanged to machine callers.

Predeclare checkpoints, budgets, and selection rules. Test scores cannot enter tuning requests, history, candidate selection, or stopping, and cannot automatically extend rounds or trigger repairs. Incomplete measurements remain pending or failed, not zero.

Human-only access does not itself prove independence. If a person steers development or selects a version using these scores, that collection becomes development evidence and another untouched evaluation is needed.

`HumanTestObserver` measures the retained version at the baseline and each round, including rounds whose proposals are rejected. It does not pair one Package's dev score with another Package's test score. Results are stored separately, and cancelled/failed observations preserve their state.

Desktop defaults to 24 dev and 12 human-only test cases, while train grows. `human_test_count=0` disables observation; the API defaults to zero for compatibility. A supplied `human_test_suite` uses `split=test` and cannot enter the optimizer's train/dev suite. Observation and optimization share the call-concurrency ceiling, and completed observation records survive restart.

Exact ID or normalized-input overlap invalidates test observation without exposing hidden cases to tuning or changing selection. This does not prove the absence of semantic overlap. Prefer official predeclared benchmark splits. Older freeze-then-test runs retain their original protocol; newer checkpoint runs disclose their observation protocol separately.

### Initial experiment split

Optimization splits only the official train set into train and dev. Official test remains outside the optimizer for measuring a frozen candidate against the baseline.

| Collection | Purpose | Tuner access |
| --- | --- | --- |
| train | Execute and diagnose failures; add official training tasks | Actual dialogue, tool evidence, grading diagnostics |
| dev | Fixed candidate-selection cases drawn from train | Aggregates and anonymous scores only |
| external test | Compare frozen baseline and candidate | No content or scores enter tuning |

## Why dev is not independent final evidence

Repeated anonymous dev feedback still influences candidates. It is useful for selection but cannot simultaneously prove performance on untouched tasks. Repeated final measurements begin after freezing the candidate and evaluation configuration. Human checkpoint observations do not select the version.

Do not feed test failures back, choose the highest test-scoring historical version, or change prompts and continue claiming the same blind test. Once test evidence guides development, disclose that change and use another untouched collection for independent validation.

## Observing progress during RSI

Development scores provide useful process evidence. Their meaning depends on which tasks are measured and whether results affect subsequent decisions.

### Development already uses real official tasks

Train and dev tasks use actual model conversations, official simulated tools, and official grading. A change from 2/4 to 3/4 means one additional success on those four dev tasks in that measurement, not guaranteed test improvement. Small sets and stochastic users/judges limit the conclusion.

### Independent process monitoring

Predeclare observation cases and checkpoints, exclude them from train/dev, and keep their questions and scores out of tuning, design, selection, and stopping. The initial study did not add a fourth collection; the product's three-collection workflow uses its designated human-only test set for observation.

### Running official test each round

This is possible as an isolated, predeclared observation protocol. If test results influence a person or automatic controller's next decision, those cases become development data. Freeze the final candidate according to train/dev and use an untouched evaluation for an independent final claim.

### When improvement is supported

Distinguish better training scores, better dev scores, and better frozen external test results. Report improvements and regressions, repeat counts, uncertainty, costs, and whether test evidence influenced decisions. A reasonable patch explanation is not evidence of performance.

## Expanded coverage and repeated measurements

Expanded studies used a 12-task training start, 12 fixed dev cases, and six additional training tasks per round, with a maximum of eight proposals and a three-round stagnation limit. Frozen baseline and candidate Packages were each measured on forty test tasks using four predeclared seeds. Infrastructure failures retained their attempts; completed official failures were not rerun to improve scores.

Expansion addressed limited initial training coverage and truncated feedback that lost late execution results. It did not use official test questions or trajectories. Earlier aggregate test observations had already been seen, so the overall program is exploratory research on a public benchmark, not a first-ever untouched encounter.

A separate default gpt-6.1-sol reference matched the explicit task, tool, seed, budget, user, and grading settings. Different model defaults and tuner overhead prevent an equal-compute interpretation. An earlier expanded run accepted no candidate, so differences between its identical frozen Packages measure variance rather than RSI gain.

### Training-side feedback correction

Inspection found that tuning history included patches and reviews without clearly identifying whether a proposal had been accepted. Subsequent feedback adds `accepted`, `overall_before`, `overall_after`, and `selected_round`. It separates permission review from performance acceptance and requires new training evidence before retrying a rejected idea. Scores from changing suites cannot be compared as if the suites were unchanged.

The selection-feedback experiment began under a predeclared trigger after the earlier development run ended without accepting a candidate. It retained the same baseline, models, splits, budgets, and selection rules, with no test-driven candidate choice. Its accepted rounds, rejected regressions, frozen measurements, failed attempts, transport repair, and limits are preserved in the evidence described above. Earlier runs retain their original implementation and cannot be retroactively credited with later fixes.

## Implementation of isolation

The host retains task routing, private user scenarios, and grading. The target receives information through normal Session interfaces with unchanged native/domain tool permissions. File tools access only per-task workspaces; benchmark source, test files, and credentials are not mounted there. Native process execution is not granted without OS isolation.

Record model routes, seeds, splits, budgets, and candidate hashes before execution or freezing. Retain official trajectories and native runtime evidence. Isolation depends on host input/resource boundaries, not instructions telling the model to avoid answers.

## Initial Sage experiment

The baseline uses default Sage instructions plus official public retail policy and all required tools. The target is Luna; tuning, user simulation, and natural-language judgment use the configured stronger model. This is stronger-model-assisted optimization, not pure same-model self-improvement.

The initial integration used four training and four dev tasks drawn in advance from official train, added two official training tasks per round, and allowed at most three proposals. Train/dev means had equal weight; sufficient aggregate improvement could retain a candidate with recorded per-case regressions. Initial tuning changed only instruction guidance, preserving policy, tools, target model, and budgets.

These small initial settings tested integration, not coverage. Freeze the last development-selected candidate before measuring the same forty official test tasks against baseline. A stronger candidate can remain unverified against the internal stable-success target; test results must not retroactively select it.

## Assessing RSI benefit

Consider train/dev changes, frozen external success, paired gains and losses, tool errors, dialogue length, and optimization cost. Multiple proposal rounds establish recursive benefit only when later rounds add measured value. Higher train with flat/lower external test should prompt investigation of coverage, noise, or overfitting.

Local measurement requires no leaderboard submission. Sage's tools, orchestration, and prompt changes form a custom method; any future submission must disclose them. Test-subset results do not establish complete-base leaderboard performance or universal domain effectiveness.

## Public result references

The following official retail records were reference examples as of 2026-10-21, not a ranking of the top three current models.

| Model | Retail pass¹ | Retail pass⁴ |
| --- | ---: | ---: |
| [Qwen3.5-397B-A17B](https://github.com/sierra-research/tau2-bench/blob/main/web/leaderboard/public/submissions/qwen3.5-397b-a17b-think_sierra_2026-03-02/submission.json) | 84.43% | 59.65% |
| [GPT-5.2](https://github.com/sierra-research/tau2-bench/blob/main/web/leaderboard/public/submissions/gpt-5-2_sierra_2026-02-26/submission.json) | 81.58% | 51.75% |
| [Claude Opus 4.5](https://github.com/sierra-research/tau2-bench/blob/main/web/leaderboard/public/submissions/claude-opus-4-5_sierra_2026-02-26/submission.json) | 79.61% | 51.75% |

Those submissions use full retail sets and their disclosed simulators/inference settings. Sage's train-optimized, external-test subset has different coverage and simulator conditions and cannot be ranked against those percentages directly. Live model evaluation generally incurs provider costs.

## Official sources

[[1] Pinned v1.0.1 project](https://github.com/sierra-research/tau2-bench/tree/v1.0.1)

[[2] Mainline version comparison](https://github.com/sierra-research/tau2-bench#comparing-with-v101)

[[3] Pinned domain data and splits](https://github.com/sierra-research/tau2-bench/tree/v1.0.1/data/tau2/domains)

[[4] Task structure and grading](https://github.com/sierra-research/tau2-bench/blob/v1.0.1/docs/evaluation.md)

[[5] v1.0.1 custom submission requirements](https://github.com/sierra-research/tau2-bench/blob/v1.0.1/docs/leaderboard-submission.md)
