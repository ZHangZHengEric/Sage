---
layout: default
title: RSI Evaluation and Tuning Loop Proposal (Draft)
parent: Architecture
lang: en
ref: v2-detail-rsi-evaluation-tuning-loop-proposal
---

{% include lang_switcher.html %}

# RSI Evaluation and Tuning Loop Proposal

Date: 2026-10-24
Status: discussion draft. This page describes proposed changes; it does not claim they are implemented or experimentally validated.

## Implemented scope and validation status

The code now implements the three selected directions: eval focused on what to verify next, a single-mechanism
`OptimizationExperiment` with falsification conditions declared in advance, and measuring new training cases on the
retained version first. Experiment cards constrain new candidates by default while old archives stay readable; the
model may decline to edit when it has no supportable intervention. Supplementary measurement uses its own phase so
recovery and presentation never confuse the retained version with a candidate. The entry points are
`sagents/v2/optimization/{diagnostics,experiments,optimizer}.py`.

The remaining statistical comparison, independent acceptance, and full issue-cluster protocol are still future
design; the changes above do not complete this proposal. Offline tests and real ALFWorld runs are validated separately.

The real ALFWorld subset experiment of 2026-10-24 is complete, with GPT 5.6 Luna as both target and RSI model.
It covered 120 train / 24 dev / 24 test cases; 20 training cases were added after the initial 100 and measured on
the retained version first. In the final experiment `rsi_aee5286497c04837b049d56b04707937`, the candidate scored
train 114/120 and dev 21/24, against 107/120 and 20/24 for the retained version on the same cases. The old selector
rejected the candidate because of one native loop-protection pause, so both independent 23/24 test results belong to
the retained version and are not candidate effects. The original decisions and evidence are preserved; the framework
then completed grading and selection boundaries for closed single-turn episodes. One execution and reuse of
historical observations do not prove causality or stable improvement. The full report is stored with the experiment
in Sage Desktop's `runtime/rsi/<run_id>/REPORT.md`, with frozen code archived separately.

## 1. Goals and confirmed principles

The primary goal is to improve RSI's ability to produce effective changes and to reliably judge whether a candidate is actually better. Lower token consumption is secondary and must not come from dropping necessary evidence, skipping regressions, or lowering validation standards.

Confirmed directions:

1. eval produces actionable, testable diagnoses rather than exhaustive fault-finding.
2. Each tuner round works on an explicit mechanism hypothesis and states the expected behavior change and how to verify it.
3. The loop follows "expose failures, then edit, then verify". New training cases are measured on the current retained version first.
4. Validation stays isolated: the tuner receives only validation scores, never validation traces, analyses, questions, or answers.
5. The proposal is a generic optimization protocol; TauRetail tasks, tools, identity verification, and business rules stay out of the framework.

The remaining protocols, statistical thresholds, and implementation order are proposals of this draft and need further decisions before implementation.

## 2. Problems and design direction

Recent experiments show that the key problem is not a lack of generated changes, but a weak link between the basis for a change and the evidence of its effect:

- Task failures, legitimate but incomplete procedures, simulated-user variation, environment problems, and grading doubts blend into one score.
- General flaws in diagnosis can outweigh the errors that actually affect outcomes, steering the tuner toward secondary issues.
- The tuner is still pushed to edit after training already passes; new cases run only after editing and cannot supply failure evidence in advance.
- Edits can add restrictions the original policy never required, breaking paths that used to work.
- Comparing a new candidate against historical retained-version scores can mistake execution noise for improvement or regression.
- Per-round acceptance, reaching the goal, stability confirmation, and independent generalization are distinct conclusions and need separate records.

Authoritative grading, causal diagnosis, edit decisions, and version selection should be separated. No single model's explanation or self-report can prove a fix works.

## 3. Generic roles and data boundaries

| Role/component | Inputs and responsibility | Boundary it must not cross |
|---|---|---|
| Grader | Computes results under a fixed grading protocol and stores component checks and rationale | Never adjusts criteria afterwards because of diagnostic explanations |
| eval | Attributes execution evidence and produces issue cards, success contrasts, and uncertainty | Never turns case answers into production instructions or changes fixed scores |
| tuner | Proposes hypotheses from training issue cards, edits candidates, and states expected behavior | Never reads validation/test content, widens permissions, or changes grading |
| Experiment orchestrator | Manages training measurement, candidate evaluation, contrast runs, and evidence archives | Never zero-fills missing grades or silently drops failures |
| Selector | Selects versions by predefined objectives, thresholds, and risk constraints | Never treats tuner self-reports or diagnostic confidence as actual gains |
| Independent acceptance | Measures the frozen candidate against the baseline independently | Never feeds test results back as per-round tuning material |

This is a division of responsibility, not a requirement for the same number of model Agents. Deterministic ordering, protocol validation, statistics, and state management should preferably be done by code.

Without an external scorer, model grading may continue, but it must separate "grading result" from "explanatory diagnosis", fix the grading prompt, model binding, and protocol, and record its uncertainty.

## 4. eval: causal, action-oriented issue cards

### 4.1 Diagnosis order

1. Identify the grading conditions actually unmet, separating scored conditions from diagnosis-only checks.
2. Confirm that execution, grading, and environment records are valid and sufficient for analysis.
3. Decide whether a better executable decision existed given the information, permissions, and user authorization at that time.
4. Locate the earliest deviation related to the failure, separating main cause, contributing factors, and unrelated flaws.
5. When successful executions exist, contrast them to find key decision differences; differing outcomes alone do not prove causality.
6. Give testable hypotheses with counterevidence; keep unknowns explicit when evidence is insufficient.

### 4.2 Issue card fields

| Field | Requirement |
|---|---|
| `issue_id` | Stable identifier linking issue clusters and historical experiments |
| `failed_conditions` | Specific failed conditions from authoritative grading, with references |
| `attribution` | Agent-controllable, environment, user simulation, grading doubt, infrastructure, mixed, or unknown |
| `causal_status` | Confirmed controllable deviation, causal hypothesis, non-causal flaw, or insufficient evidence |
| `critical_decision` | The key decision, its preconditions, and the actual deviation |
| `evidence_refs` | Evidence references bound to version, case, trial, and message/tool indices |
| `successful_contrast` | Differing decisions on successful paths and their conditions; empty if none |
| `hypothesis` | One improvement hypothesis that an experiment can support or refute |
| `expected_observation` | Behavior change expected after the fix |
| `counterevidence` | Facts against the attribution, alternative explanations, and missing information |
| `protected_behaviors` | Successful behaviors and policy boundaries to preserve |
| `priority` | Severe rule violation, outcome-related, or general quality issue |

Field names are a draft protocol and do not require changing all existing public APIs at once.

### 4.3 Priorities and handling

- Severe permission or business-rule violations: handle separately even when the task score passes, and block non-compliant candidates from acceptance.
- Controllable errors related to failures: enter the main tuning queue.
- General wording, efficiency, or style flaws: accumulate separately; trigger edits only for a matching optimization objective or clear experimental basis.
- Environment, scenario, or grading disputes: enter the measurement-issue queue instead of forcing the tuner to fix them through prompts.

Task scores and failure attribution are both preserved. A legitimate handoff to a human with an incomplete task may still be a task failure; that alone is not evidence that the Agent should perform unauthorized operations.

Incomplete evaluation material must be read further or marked as incomplete analysis. On-demand reading must not package partial excerpts as complete causal conclusions.

## 5. tuner: hypothesis-driven candidate experiments

### 5.1 Experiment card

Each candidate stores the following before evaluation, preventing success criteria from being rewritten after the results:

- Linked issue cards and the current retained-version hash.
- The main mechanism hypothesis and its scope.
- Exact edit locations, rationale, and why existing rules do not already solve the problem.
- Expected behavior change and the task outcomes expected to be affected.
- Observations that would support the hypothesis, refute it, or leave it undecided.
- Training cases, similar cases, and successful protection cases used for verification.
- Potential regressions, inviolable business rules, and any necessary resource impact.

A candidate centers on one main mechanism and may include necessary supporting edits. Multiple independent mechanisms should be split into separate experiments, or the loss of attribution power must be stated.

### 5.2 Edit constraints

1. New production restrictions must trace back to the original policy or verified necessary conditions; new business rules cannot be derived from preferences in individual traces.
2. When an existing rule fails in execution, check priority conflicts, procedures, resource loading, and capability gaps instead of appending more prompt text by default.
3. Choose instructions, skills, tools, or procedure according to the problem, within the authorized optimization scope only.
4. Allow small edits as well as evidence-backed overall reorganization, without forcing full rewrites or appended patches every round.
5. Check the candidate's actual diff for scope and for changes the experiment card does not explain.
6. Without a supportable hypothesis, allow no edit, request supplementary training measurement, or report a measurement problem.

### 5.3 Generic example

Hypothesis: the Agent misreads "make the overall configuration meet the optimal target" as "every component must change".

Edit: separate the target configuration from the set of changes to execute, allowing components that already meet the target to stay.

Expectation: existing optimal components stay unchanged and others change within constraints, without harming tasks where the user explicitly asks to replace everything.

Verification: the original failing case, similar training cases with different initial states, and a successful protection case that explicitly requires changing everything.

This is only a format example for experiment cards, not a built-in domain rule of the framework.

## 6. Training and tuning loop

### 6.1 Standard flow

1. Freeze the grading protocol, dataset version, model, and environment bindings for the experiment.
2. Run or complete training measurement for the current retained version, building issue cards and successful protection cases.
3. Select issue clusters by severity, recurrence, controllability, and coverage.
4. The tuner submits an experiment card and edits the candidate; without a valid hypothesis, request supplementary measurement or pause the cluster.
5. Check configuration and edit scope.
6. Measure the training cases related to the hypothesis and check whether behavior changed as expected.
7. Run the necessary extended training regression covering possibly affected successful paths.
8. Once the candidate meets the entry condition, compare it on the independent validation set.
9. Record acceptance, rejection, or insufficient evidence; update experience, then decide the next round.
10. After reaching a stage goal or stop condition, freeze the candidate for independent acceptance.

### 6.2 Order for new training cases

New training cases must first run on the current retained version before entering the round's tuning input. Candidate and retained version should produce comparable evidence on the same relevant cases.

When all measured training cases pass but validation performance is insufficient, prefer widening uncovered training task types, adding necessary repetitions, or running reviewed training challenges, rather than forcing the tuner to rewrite successful traces. New cases cannot manufacture success by changing goals, answers, or grading criteria.

Existing failures must be preserved. Supplementary runs may estimate stability, but "rerunning until it passes" and overwriting old failures is not allowed.

## 7. Validation and test isolation

Validation continues to give the tuner only anonymous scores and selection results, never traces, diagnoses, original case IDs, reference answers, or free-text explanations that could reveal question content.

Training evidence indices, experience documents, error messages, file paths, and cross-round summaries all follow the same boundary. New issue cards or experience summaries cannot bypass isolation.

If a validation case truly must be used for training diagnosis, move it explicitly into the training set, add a new independent validation case, and create a new dataset version; an exposed case can no longer count as unseen validation evidence.

Distinguish two kinds of tests:

- The existing per-round, human-only test may serve as observational data, but results viewed repeatedly cannot be claimed as independent acceptance.
- Proving generalization requires independent acceptance data, not used in selection, after the final candidate is frozen. A human selecting versions from per-round test results also counts as participating in selection.

Whether to keep per-round observational tests by default is a product configuration question; this proposal does not remove them to save tokens. The independent acceptance boundary is a requirement for credible results.

## 8. How to confirm real improvement

### 8.1 Three layers of evidence

**Mechanism improvement**: whether the behavior expected by the experiment card appears and the original error decreases. Behavior metrics come from the specific task and observation interfaces; the framework does not hard-code domain judgments.

**Overall improvement**: after related training issues are fixed, the candidate still has a net gain in independent validation comparison and satisfies policy, regression, and resource constraints.

**Generalization improvement**: the final frozen candidate is still supported against the original baseline on independent acceptance data. If validation improves but acceptance does not support it, report honestly that generalization is not yet confirmed.

### 8.2 Formal selection comparison

- Candidate and current retained version use the same data version, grading rules, repetition plan, and environment conditions.
- Remeasure both in the same comparison window, rather than letting a new candidate challenge an old historical high score.
- Interleave or balance run order; isolate and reset environment state between trials.
- Use paired seeds when seeds can be fixed, without treating identical seeds as making the whole interaction deterministic.
- Report fixed cases, regressed cases, task success rate, same-case stability, and severe violations together.
- Statistical analysis groups repetitions by case instead of treating repeated runs of one case as independent new samples.
- Decide the minimum meaningful gain, acceptable regression, hard rejection conditions, and statistical method before the experiment.
- With staged supplementary measurement, limit supplements and stopping rules in advance; do not keep peeking at scores until a favorable result appears.

This draft does not fix a repetition count. It should depend on sample size, execution variance, and the required strength of conclusion; a limited budget can only lower confidence, not lower the standard and then claim effectiveness.

### 8.3 Result states

| State | Meaning |
|---|---|
| Accepted | Meets the agreed gain and risk thresholds with sufficient evidence |
| Rejected | Clearly ineffective, regressive, or violating hard requirements |
| Insufficient evidence | Results within noise, insufficient measurement, or unresolved disputes |

Separately record whether the business goal is reached, stability is confirmed, and independent acceptance is passed. Acceptance does not automatically imply all three.

## 9. Experience and evidence persistence

The experience store is organized around mechanism hypotheses and records conditions, actual edits, behavior changes, task outcomes, counterevidence, regressions, and open questions.

"Accepted" only means the candidate passed the selection rules at the time; it cannot directly label a causal hypothesis as correct. Distinguish hypotheses that were supported, refuted, or remain unverified.

Each experiment stores at least:

- Content hashes and actual diffs of the original baseline, current retained version, and candidate.
- Version bindings for model, scorer, user simulator, data, and environment.
- Issue cards, experiment cards, and the actual requests and responses of eval and tuner.
- Target execution, tool results, grading details, diagnoses, and validity checks.
- All valid trials of the selection comparison, missing/failed records, statistical method, and decision.
- Evidence read ranges, truncation/missing markers, and complete archive entry points.

Clearly separate native sessions from long-term archived evidence. After temporary working directories are cleaned, a session ID alone cannot justify claiming the conversation is fully preserved; archives must suffice to review key behaviors and decisions.

## 10. Tokens and efficiency: a secondary goal

Effectiveness comes first. Even if most cost comes from execution, necessary old/new contrasts, successful-protection checks, and independent acceptance cannot be skipped to reduce runs.

Possible later optimizations:

- Record tokens, latency, and run counts by role and stage to confirm the actual cost structure first.
- Reuse diagnoses for identical evidence with matching bindings; deduplicate identical candidates.
- Use issue cards and indices to locate necessary evidence, reducing repeated copies of full traces while keeping the ability to read more.
- Stop early for candidates that clearly violate rules or obviously fail their hypothesis, without running pointless later measurements.
- Add measurements for comparisons near the threshold or with high variance; avoid unjustified repetition when evidence is clear.

Old execution caches can help discover problems and pre-screen, but do not automatically replace fresh measurements required for formal selection. Diagnosis depth for successful samples can follow risk, but their rule checks and regression role must not be removed by default.

## 11. Implementation stages and acceptance criteria

### Stage 1: diagnosis and hypothesis protocol

Add issue cards and experiment cards, stored and referenced in existing archives; adjust eval/tuner responsibilities and output requirements.

Acceptance: main causes of task failures are clearly separated from general flaws; insufficient evidence does not force a fix; candidates have prior hypotheses, refutation conditions, and protected behaviors; validation material does not enter tuner input.

### Stage 2: training evidence loop

Change the training growth order so new cases run on the current retained version first; support success/failure contrast, no-edit, supplementary measurement requests, and a measurement-issue queue.

Acceptance: new training issues supply real failure traces before candidate editing; coverage can grow when all training passes; successful strategies are not forcibly edited just to produce a candidate.

### Stage 3: effect confirmation and selection

Establish formal old/new comparison and accepted/rejected/insufficient-evidence states, separating business goal, stability, and independent acceptance.

Acceptance: selection no longer relies only on historical high scores of the retained version; all valid failures are preserved; statistical handling of repetitions has explicit rules; generalization gains are claimed only with independent acceptance support.

### Stage 4: presentation and efficiency

The interface separately shows the current candidate, retained version, evaluation metrics, and evidence state; improve archives and cost reports, then optimize repeated work.

Acceptance: means, repeated success rates, selection metrics, and convergence metrics are not confused; users can trace "why it changed, why it was accepted, whether it was really verified"; cost savings do not harm the effectiveness of the first three stages.

## 12. How to validate this proposal

After implementation, one successful optimization run is not enough. Compare the old and new flows with the same initial package, task data, model, and environment bindings, across multiple task types and multiple independent optimization runs.

Main evaluation: net gain on independent acceptance, the proportion of runs producing repeatable effective candidates, false acceptances and severe regressions, and the quality of failure attribution in human spot checks.

Report resource consumption too, but do not substitute cheaper for more effective. State the limited scope of conclusions when samples are small. Use controlled experiments to separate the contributions of issue cards, measuring training first, and selection remeasurement, rather than attributing all gains to one change.

## 13. Decisions needed before implementation

1. How issue cards and experiment cards stay compatible with existing diagnosis / patch / experience fields.
2. The main metric for formal selection, minimum meaningful gain, hard rejection items, and statistical method.
3. Repetition, supplementary measurement, and stopping rules, plus product behavior for insufficient evidence.
4. Selection rules for training issue clusters and successful protection cases.
5. The human confirmation entry for scenario or grading disputes and how dataset versions migrate.
6. The product distinction between per-round observational tests and independent acceptance data.

These parameters are not final; this draft does not confirm specific thresholds, repetition counts, or default test switches.
