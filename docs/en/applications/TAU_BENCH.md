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

## Current entry: standard Desktop RSI (2026-10-23)

Current experiments use Desktop's standard dataset import, Python-scorer import, and RSI start APIs, without a dedicated τ-bench host. Data and vendored official source are in `evaluation_datasets/tau_bench/`; follow its [README](../../../evaluation_datasets/tau_bench/README.md).

1. Configure the baseline in the Desktop Agent list with official retail policy, the selected GPT-6.1 Sol, and `TauRetail` stdio MCP business tools. RSI snapshots this configuration without adding baseline tools or editing the external Agent.
2. Import `evaluation_datasets/tau_bench/rsi.dataset.json` and `scorer.py`. A scorer must pass four self-tests before selection; default model grading applies only when no custom scorer is selected.
3. The page controls question counts, per-round growth, repetitions, concurrency, prompt length, and Skill limits. Execution and assessment files remain separate. The custom scorer exclusively owns numeric grading; eval still analyzes full execution.
4. Training analysis reaches tuning; dev supplies anonymous scores only; test questions, execution, and grades never enter tuning or acceptance. The page exposes runs, version diffs, and each round's workspace.

Run `rsi_f4e63074223244578902e2f33f28114a` has completed baseline measurement and is executing its first candidate. It uses the same parameters, baseline package, splits, scorer source, and GPT-6.1 Sol described below. Updates preserve complete training scenarios, locally successful paths from rejected rounds, and the distinction between original responsibilities and candidate restrictions. The source snapshot includes 518 verified Python files. Feedback changes passed 300 source regressions; later suite-review prompt changes passed 134 targeted regressions. These are not independent benchmark results.

The new baseline passed train 20/24 and 21/24, averaging 0.8542; dev passed 9/12 and 6/12, averaging 0.6250; equal-weight selection score was 0.7396. Independent test completed **34/40, 0.8500**, with one execution per question, all diagnosis complete, and every score equal to official reward. Audit: `tau-native-provider-v11/baseline-human-score-verification.json`. Test questions, execution, and feedback remain hidden from tuning. The unchanged baseline package means differences from historical baselines are not RSI gains.

The tuner produced the first candidate by actually reading training-analysis files and editing a 12,041-character system prompt and one 8,473-character Skill. Business tools, permissions, and budgets are unchanged, and responsibility review passed. Full train/dev comparison is incomplete: this is neither an accepted improvement nor evidence of reaching independent test 0.95. Evidence contains 24 case files, 48 individual execution files, and 48 individual assessment files: 20 consistently successful cases, 3 consistently failing, and 1 unstable. Repetitions are not nested inside one file.

Intermediate run `rsi_bd14edf54f2344cd9508a4474394868e` stopped during suite review without executing a baseline or producing valid scores. Training-only diagnosis found that review mistook reconcilable operation-specific policy scope for an impossible task. Updated review treats text-supported consistent ambiguity as advisory while retaining blocking checks for explicit authorization, identity/state restrictions, and universal write limits. Real-model controls accepted a feasible training case and rejected explicit universal-limit and unauthorized-operation counterexamples. Original policy, business tools, cases, and scorer were unchanged; the failure remains recorded and the replacement run uses a new engine identity, rather than retrying to erase the review outcome.

Completed standard run `rsi_cdfc856ea31841f39c8b74efccf3634e` used 24 initial train cases, 4 additions per round, 12 fixed dev cases, and 40 independent test cases. Train/dev ran twice with mean aggregation; test ran once. Concurrency was 6, the limit 8 rounds, system prompt 20,000 characters, each Skill 15,000 characters, and at most 2 Skills. These are experiment choices, not framework constants.

That historical run used exactly the same baseline package as the newest run. Its first complete independent baseline scored 29/40 (0.725), with no duplicates or missing tasks, official-reward agreement, and completed diagnosis. A later human checkpoint on the unchanged baseline scored 32/40; an earlier same-package measurement scored 31/40. These are repeated-measurement variation, not RSI gains or framework-quality differences.

The historical run accepted one candidate. This table compares only the 24 training and 12 dev cases executed by both versions, averaging two repetitions per case. Selection equally weights train/dev and excludes test. It is not the newest run's first-round result.

| Version | Common train | dev | Selection score | Outcome |
| --- | ---: | ---: | ---: | --- |
| Baseline | 0.6875 | 0.7083 | 0.6979 | Initial retained version |
| Round 1 | 0.7292 | 0.3750 | 0.5521 | Rejected; baseline retained |
| Round 2 | 0.8333 | 0.6667 | 0.7500 | Accepted |

Round 2 had no common-training regression: three cases changed from two failures to two successes, and another from mixed results to two successes. Dev remained slightly below baseline, so the evidence supports training/selection improvement, not demonstrated generalization. New cases were not backtested on old versions. On all 32 accumulated training cases, its two trials passed 27/32 and 25/32, averaging 0.8125, a different denominator from the table. Audits: `tau-native-provider-v9/round1-selection-verification.json` and `round2-complete-selection-audit.json`.

The accepted round-2 package completed all 40 independent test cases: 33/40 (0.825), with complete diagnosis, no duplicates/missing cases, and official-reward agreement. Package hash: `84236b7148f36986b93e1cf3d5b1d78617b39401b42ec557a174b771415fb16c`; audit: `tau-native-provider-v9/round2-human-score-verification.json`. This exceeds the first baseline's 0.725, but an unchanged-baseline repeat scored 0.800. One difference does not establish stable benefit, and the 0.95 target was not reached.

After the complete round-2 comparison, the run was normally canceled to adopt validated general feedback fixes. Incomplete round-3 records remain and count as neither valid rounds nor failing scores. Fixes address missing training scenarios, lost local successes in rejected candidates, and confusion between original responsibilities and candidate restrictions; they do not use test questions or feedback. Real Flutter recordings cover conversation progress, repetition matrices, acceptance, and prompt/Skill diffs, but cannot replace full independent measurement.

The dedicated host, external mirror, and command-line flags below document historical experiments, not the current entry point. Historical results are not current standard-workflow scores.

## Historical local measurements (complete, not publicly submitted)

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

## Follow-up 6.1 capability experiment (2026-10-22)

This experiment uses only gpt-6.1-sol for target, tuner, simulator, and natural-language judge. The default Agent retains official policy and all native/retail tools. It compares default 6.1 with same-model RSI, without Luna or other model groups.

Before reading new test outcomes, the 74 official training cases were split once into 50 train and 24 fixed dev, all used from baseline. Each runs three times; all outcomes are retained and mean success drives comparison. After semantic approval, the parent is remeasured three times with paired trial seeds. The limit is eight rounds with stagnation after three unimproved rounds; test does not change those rules.

The general `instructions/skills/tools` scopes permit package Skills and bounded pure helpers. Existing native/business tools cannot be removed, and policy, models, tasks, judges, budgets, and simulator cannot be changed. The default package has no retail-specific extra solution. Training evidence determines whether new capabilities are created; set operations and Skill creation are generic framework features.

All 40 test cases are observed at baseline and retained-round checkpoints for people only. After freezing, baseline and candidate each run 40 cases four times for pass¹/pass⁴. Previous aggregate exposure to the same official test makes this an exploratory replication, not a fresh untouched final validation. Old test inputs, failures, and answers do not reach tuning.

Desktop mirrors actual journals and human checkpoints into the existing RSI page. A real-model smoke test completed official training tasks, but full measurement was incomplete, so no gain was claimed in advance.

Output is `tau-retail-61-capabilities/` under the evidence root above. Desktop Agent: **τ-bench 6.1 · RSI**, `agent_4765e13396214ab887211e2f736db40f`; resumed run: `rsi_external_c85c4a449b004d9ea909f705d247b139`, with the original `rsi_external_bcc51342d72d46e281710f70ee8b02a7` journal retained. Actual Desktop HTTP reads verified the history entry and logs. Run `flutter run -d macos` from `app/v2/desktop` and open that Agent's RSI history. Data persists in `~/sage/runtime/rsi.sqlite3` and the journal directory after closing the UI. External host versions are previews and cannot be directly applied to ordinary Agents lacking retail bindings.

Before the first tuning decision, 50 training traces approached one million characters. Generic model feedback now budgets the whole suite, prioritizing failing traces while retaining per-case/per-repetition numbers and explicit truncation markers. Complete reports/journals remain intact. Main training feedback has a 120,000-character limit and each of the last four attempts 12,000; character limits do not guarantee an arbitrary model token budget. All 126 completed official development evaluations were replayed exactly without regrading. Since no candidate or tuning decision existed, execution continued under a new optimization ID. Original journals, source snapshots, and `implementation-adjustments.json` disclose the change; incomplete disposable tasks restarted.

Before the first tuning decision, `--diagnose-executions` was enabled (default for later runs). Official scores remain fixed; independent eval analyzes full train/dev conversations and tool calls, segments long records, compares success/failure traces across repetitions, and summarizes training-only priorities. Dev diagnosis stays hidden from tuning. A real GPT-6.1 smoke test on saved failure `tau-46` identified a successful return that omitted reporting the remaining items' paid amount; this diagnoses a cause without proving optimization benefit. The 159 previously completed target executions were replayed unchanged for fresh diagnosis, without rerunning targets or rejudging official scores; `development-protocol.json` records the change.

Transient gateway errors such as 502 use bounded backoff with at most 60 seconds per wait and a one-hour infrastructure recovery window. Official simulator calls also retry model requests. Native `model.provider_transient` is recognized as infrastructure failure. Recovery applies only to tool-free internal calls and disposable benchmark environments, never to rerunning valid zero scores or authorizing real external side effects. Waits are recorded in `infrastructure-retries.jsonl`; existing scores remain.

### Small workflow debugging experiment (2026-10-22)

Both experimental Agents explicitly contain official policy, 14 Sage tools, and 16 retail tools, without preinstalled Skills. Listed prompts match the frozen baseline. Early scripts appended policy temporarily, making Agent settings differ from the version baseline; this external integration issue was corrected while preserving old settings and run records. New mirrored runs read the selected Agent's real prompt/tools and reject missing policy/tools or mismatched models. Ordinary Desktop RSI already snapshots the selected Agent and only writes changes back through explicit version application.

Retail tools still require the isolated τ-bench host and simulated database; listing tools does not make that environment available in ordinary Desktop chat. Experimental versions remain previews.

The large run was stopped to shorten implementation-feedback cycles, retaining executions, scores, and diagnosis without claiming validated candidate gains. The replacement `tau-retail-61-workflow-debug/` uses Agent **τ-bench 6.1 · 流程调试**, `agent_fcbe499c467a4137b067ffeb37a7152e`, run `rsi_external_be606ba4ffbd4174b6b45d50a60f4f63`; actual Desktop HTTP verified history and logs.

It uses 6 initial train, 3 fixed dev, 2 independent repetitions, at most 4 rounds, at most 1 added training case per round, and concurrency 6. Parent full-remeasurement and human test checkpoints are off; `--workflow-only` also skips frozen final test. Complete successes and failures retain independent diagnosis, with repeated-case comparisons for inconsistent training results. Dev still provides anonymous scores only. This small sample validates tuning, review, acceptance/rejection, and recovery, not final benchmark performance.

Baseline target calls fall from 222 to 18. Small candidate suites avoid full per-round and final 320-test workloads, but new cases, early stopping, and confirmation affect actual call counts and duration.

The next protocol uses `tau-retail-61-workflow-rounds/`, the same debug Agent, run `rsi_external_4aa7b05ca1fc406e968757582985288f`. New cases are not backtested on old versions; candidates rerun accumulated train and fixed dev, and improvement compares shared cases only. Eighteen identical baseline executions and exactly matched eval responses were reused with original tools, traces, and scores, without score shopping. The old run stopped when diagnosis synthesis exceeded field limits; bounded format repair was added. Read-only tuner tools expose full categorized training files, excluding dev/test. The page groups repetitions by baseline/round.

New training case `31` exposed missing diagnosis context: a successful transfer did not satisfy an additional condition hidden from the target. The completed trace was reused to validate `--evaluator-references`, exposing official training scenario/outcomes only as evaluator `reference_answer`. The official zero stayed fixed; diagnosis distinguished unmet overall goals from hidden goals lacking authorization and suggested policy-compliant follow-up. The target was not rerun and test was not read. Evidence: `tau-61-reference-diagnostics-30ce3205/diagnostic-result.json`. New experiments may opt in; existing reference protocols stay frozen after tuning starts. Reference-answer fields never enter target input, tuner folders, or disclosed dev questions.

## Implementation of isolation

The host retains task routing, private user scenarios, and grading. The target receives information through normal Session interfaces with unchanged native/domain tool permissions. File tools access only per-task workspaces; benchmark source, test files, and credentials are not mounted there. Native process execution is not granted without OS isolation.

Record model routes, seeds, splits, budgets, and candidate hashes before execution or freezing. Retain official trajectories and native runtime evidence. Isolation depends on host input/resource boundaries, not instructions telling the model to avoid answers.

## Initial Sage experiment

The baseline uses default Sage instructions plus official public retail policy and all required tools. The target is Luna; tuning, user simulation, and natural-language judgment use the configured stronger model. This is stronger-model-assisted optimization, not pure same-model self-improvement.

The initial integration used four training and four dev tasks drawn in advance from official train, added two official training tasks per round, and allowed at most three proposals. Train/dev means had equal weight; sufficient aggregate improvement could retain a candidate with recorded per-case regressions. Initial tuning changed only instruction guidance, preserving policy, tools, target model, and budgets.

These small initial settings tested integration, not coverage. Freeze the last development-selected candidate before measuring the same forty official test tasks against baseline. A stronger candidate can remain unverified against the internal stable-success target; test results must not retroactively select it.

## Persistent evaluation workspace and full rerun plan

The reference-diagnosis workflow `tau-retail-61-workflow-references/` completed four rounds and 84 executions on 2026-10-22, including exact baseline reuse, without running test. Eval received training references, but direct answer fields stayed outside tuner input and dev remained anonymous. Round 1 was accepted, round 2 tied and was rejected, round 3 improved shared-case overall score from 0.892857 to 0.928571 without shared-case regression and was accepted. Round 4 proposed no changes, reused evaluation, and retained round 3. Its accumulated train mean was 0.888889 and dev 1.000000; remaining training failures kept `goal_verified=false`.

For return task `tau-46`, the two official scores were baseline `[0, 0]`, round 1 `[1, 0]`, round 2 `[0, 1]`, round 3 `[1, 1]`. Round 3 actually read retained and rejected-round failure/instability files and refined an additional email-channel authorization condition. This supports extra multiround benefit on a small sample, not broadly stable behavior or independent test improvement.

Two scaling issues were fixed: repeated diagnosis could exceed history-feedback budgets, and putting full evidence inside the tuner package could exceed 4 MiB. File mode now includes only entry indices, priorities, and numeric history in context, with full training evidence in persistent `workspace/` for authorized read-only tools. Inputs, candidate execution, changes, and acceptance are archived under `workspace/iterations/round-NNN/`. Desktop registers that directory as a project; journals, recovery context, and hidden material stay outside. Real workspace APIs verified in-bounds reads and out-of-bounds rejection; an actual resumed run read over 5 MiB of evidence.

The full rerun `tau-retail-61-full-references-v1/` was planned before reading its independent test outcomes:

- Split the 74 official training tasks once into 50 train and 24 fixed dev; use all from baseline, three repetitions each, with GPT-6.1 Sol only.
- Use the preconfigured **τ-bench 6.1 · RSI** baseline with 30 native/domain tools and no initial Skill, without silently appending policy or applying candidates.
- Reuse all 222 verified same-condition baseline executions, retaining every success and failure without resampling; generate reference-aware diagnosis under the new protocol.
- Run at most 8 rounds; stop after 5 consecutive unaccepted rounds. Train and dev reaching 0.95 still require fresh stability confirmation. Generic `--target-score`, `--patience`, and `--stability-passes` are recorded and checked during recovery.
- Skip per-round test checkpoints. Freeze after train/dev selection, then independently measure baseline and candidate on 40 test tasks four times each. Test material and scores never return to tuning.

The full rerun started after the small experiment completed and passed integrity checks. It was at baseline reuse/diagnosis when documented. This is a preregistered plan, not completed evidence; small-sample gains cannot replace independent test benefit.

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

### Historical workflow test curves and supplementary measurement

The historical development command defaults to `--monitor-count 6`: baseline and retained-round checkpoints measure the same six official test cases for people only. `--workflow-only` now skips final full repeated measurement without disabling checkpoints; explicit `--monitor-count 0` disables them. Test questions, traces, and scores never enter tuning, diagnosis, or acceptance, and curves cannot select a different retained version. Six cases are not a full benchmark.

Old mirrored experiments could supplement measurement into a new output directory with `--measure-checkpoints-from <original-experiment-directory> --monitor-count 6`. Saved packages/rounds are read without calling the optimizer or changing acceptance; results attach to the original Desktop run. Plans and traces remain in the new directory. The original experiment is marked test-exposed and cannot resume as untouched development.

Historical `--initial-training` sets the initial count, `--challenge-batch` adds cases from a preshuffled official training pool each round, and `--concurrency` controls independent execution parallelism. Accumulated old cases rerun. That host stops when the pool is exhausted. A generic RSI question generator still needs executable, assessable simulations; arbitrary language questions are not official task IDs, and generated-case eval grades are not official benchmark scores.

### Dialogue input and completion

Imported cases begin with the ordinary greeting `Hello.`. The complete official scenario, including conditional disclosure and follow-ups, belongs only to the simulator's `user_context`, not target input. `dialogue_completion=user` lets the simulated user end the conversation, followed by one official scoring and one independent diagnosis call. Intermediate turns are unscored, not zero-score failures. Train, dev, and human-only test share simulator rules. The generic RSI simulator differs from the full official orchestrator, so these results must not be labeled official leaderboard scores.
