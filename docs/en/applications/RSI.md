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

RSI evaluates and improves a supplied Agent package over a configured number of rounds, using an existing model and host-bound capabilities. It does not train model weights or automatically replace the original Agent. Use the independent Python API or launch a background job from Desktop Agent settings.

## The loop

1. Supply a package, authorized goal, editable scope, and suites. A test-design Agent can generate missing suites. Single-turn tasks and bounded multi-turn conversations are supported.
2. Independently generate and fix validation questions (24 by default, configurable). Generate training questions separately and add challenges each round. Suite review checks the goal, rubric, permissions, and execution conditions, rather than judging memorization or leakage.
3. Run the baseline in fresh target Sessions. Independent evaluation Sessions judge each case against its rubric and actual execution evidence.
4. The tuner uses training feedback to propose in-scope changes; validation measurements are host-only. Independent semantic review checks goal and permission drift before candidate execution. The baseline snapshot remains unchanged; a candidate can rewrite the complete package system-prompt file, reorganize it, remove duplicates, and resolve conflicts. Appending `Optimization guidance:` is no longer mandatory. Review preserves original business rules, responsibilities, and permissions, not their verbatim wording.
5. Every candidate runs all accumulated training cases and fixed validation cases. New cases are not backtested on historical versions. Acceptance uses only the fixed validation mean (the validation objective when built-in resource scoring is enabled), with the existing `min_improvement` threshold. Training scores remain diagnostic feedback and do not contribute to acceptance. New training cases retain their execution and diagnosis without changing the selection denominator. Sufficient validation improvement permits acceptance despite individual regressions. Training regressions remain repair targets; validation measurements, regressions and selection scores remain host-only.
6. Confirm target success with a fresh full evaluation, or stop for stagnation, round limits, or deadlines. Retain the stronger package and complete history even without verified stable success, but do not recommend or automatically apply it. Human-only test observations are independent and do not gate convergence.

Desktop defaults to 12 human-only test cases, configurable from 0 to 100. They run on the baseline and each retained version, with train/dev/test curves and per-question matrices. Test Sessions and storage are separate: no test material enters tuning requests, acceptance, selection, or stopping. Test failures appear as measurement errors.

Every internal Agent invocation uses a fresh Session. Tuning receives training evidence, retention status and parent identity, never validation aggregates, pass counts, anonymous per-question scores, score history or mixed selection scores. Validation questions, original IDs, answers and diagnoses also stay hidden. The external RSI MCP is a user-delegated review interface, separate from internal tuning inputs. Compact, detailed, history and version reads expose train/dev grades, per-case diagnoses, executions, regressions and mixed selection metrics; `rsi_questions` exposes train/dev questions. Compact summaries explicitly name `baseline_training`, `selected_training`, `baseline_validation` and `selected_validation`; detailed reads retain per-case evidence. Test data, reference-answer fields, credentials and raw internal calls that cannot be classified by split remain excluded. Review results are not automatically fed into the internal tuner. If an external Agent uses dev feedback to guide further optimization, that dev set participates in development rather than independent final evaluation. The host still uses validation for selection, growth scheduling and convergence; retention and scheduling outcomes remain indirect feedback. Repeated selection on validation scores does not establish unseen-task quality; freeze candidates before an external measurement, as described in the [τ-bench experiment protocol](TAU_BENCH.md). Explicit `validation_case_count=None` preserves the historical fixed-suite and optional final-evaluation path for legacy SDK clients. This feedback boundary changes the recovery engine fingerprint; old runs require their original engine or a new experiment, rather than replaying old dev-bearing requests into the new protocol.

Custom scorer `details` are stored alongside the fixed grade for independent diagnosis. File mode puts scoring components and assertion rationales in `scorer.json`, referenced by `context.json`. Evaluation must distinguish actual failure criteria from advisory checks using the scorer's declared basis; it cannot invent grading conditions. These details are not sent to the target or simulated user, and dev/test visibility remains unchanged. The Python scorer v1 subprocess protocol retains its existing `details` field rather than adding host-internal fields inside `grade`.

If restricted file evaluation stops at an explicit `loop.repeated_pattern` user-input pause, a trusted host can authorize up to two analysis repairs with `restart_file_evaluator=True`. Repair explains the loop, rereads evidence, and writes an assessment without rerunning completed target execution or scoring. Human-only test uses the same local evaluation authorization. Approval pauses, permission pauses, and unknown side effects are outside this repair scope. File reads use approximately 8 KiB pages and still require complete coverage.

## Checkpoint recovery

Desktop offers **Resume evolution**. The backend endpoint is `POST /api/v2/agents/{agent_id}/rsi/runs/{run_id}/resume`; stdio MCP exposes `rsi_resume`. Recovery retains the same run ID and version history. External benchmark mirrors must resume through their original host, not a Desktop service without the business-tool bindings.

SDK recovery uses `resume_from=old_journal_path` and a new `journal_path`. Initial and resumed calls must share a `recovery_binding_id` derived by the trusted host from model routing, sampling, permissions, and test bindings. The original package, goal, question configuration, editable scope, and stopping rules must match.

Recovery preserves version identifiers and original grades for completed cases without reexecution or regrading. Completed internal model responses are reused. A single-turn case with completed target execution resumes only its interrupted evaluation. Multi-turn execution records `dialogue_execution_completed` and persisted target-call references; `dialogue_execution_scored` separately checkpoints its score. Interrupted diagnosis reruns diagnosis only; interrupted scoring completes only missing scores. Rejected assessment JSON is recorded as `evaluation_response_rejected` and is never reused as a valid decision.

Incomplete conversations or unknown tool outcomes raise `OptimizationRecoveryRequired` by default. Only a trusted host proving that the environment is disposable and real external side effects cannot be duplicated may set `restart_incomplete=True`; the tuner cannot authorize it. An incomplete conversation then starts in a fresh Session, without replaying old simulator decisions or intermediate assessments, and follows the target's new responses. Completed cases, executions, and grades still reuse their checkpoints.

Interrupted internal Agents with tools also require reconciliation by default. A frozen host binding restricting a role to read-only operations can explicitly authorize `restart_readonly_roles=("tuning",)` with a `recovery_binding_id`. This neither adds tools nor relabels unknown writes as reads. The current Desktop tuner edits files using `file_read`, `file_write`, and `file_update`, so it is not read-only. `restart_package_editor=True` declares a private round directory, read-only assessment inputs, and no process permission: unfinished edits are rebuilt from the retained version, and completed edits restore the actual journaled package snapshot. The target receives no additional tools.

`restart_file_evaluator=True` similarly declares private directories, read-only inputs, and no process permission for each evaluation call. Only unfinished local assessment output is recreated; completed target execution is not repeated.

Retryable native-model transport errors, including `model.provider_transient` and `model.stream_incomplete`, are not zero-score training samples. An `invalid_provider_response` interruption after a successful connection is treated as a transport error too; authentication, parameter, and context errors do not become automatically retryable. Desktop checkpoints the journal and resumes after backoff, for at most 12 consecutive recoveries, with waits from 2 to 60 seconds. Permanent configuration errors retain a failure record. Existing evidence remains readable during waits, and manual interruption preserves the resume entry.

## Independent diagnosis and repeated-case comparison

Evaluation, tuning, and review receive the host's execution semantics. In the default deterministic runner, a text-only response without tool calls normally ends the current Run; tool-call and model-response steps are not two user turns. Rewritten procedures must preserve policy ordering, cannot schedule required actions after the final reply, and cannot assume the user will send an extra “continue.” Missing information or authorization still requires clarification.

Assessment files and native Run status are validated separately. For explicitly authorized local file evaluation, a known repeated-response pause may retain a valid output only with complete actual-read receipts and valid structure and references; the native paused status remains recorded. Missing evidence or invalid output still requires correction.

When human-only test uses an external scorer, a later diagnosis failure preserves the fixed grade and execution and records the diagnosis error. A complete mean requires valid scores for all questions and planned repetitions. Missing grades are not zero-filled, and failed diagnosis is not marked complete. Scored execution is not rerun or resampled, and test material remains outside tuning.

Without an external scorer, eval grades and diagnoses the evidence. With one, a trusted host can supply synchronous or asynchronous `authoritative_grader(case, observation)` returning `OptimizationGrade` to `optimize()`. Eval independently analyzes execution but cannot change the host's grade.

Diagnosis includes causes, evidence indices, actionable instruction/Skill/tool/procedure suggestions, established facts versus hypotheses, and evidence coverage. Long records are analyzed in contiguous segments and synthesized without treating truncation as complete evidence. Full diagnosis remains in reports and journals.

Desktop uses a separate file workflow: actual conversation and tool records are read-only `inputs/conversation.json`; version instructions and grading context are in `inputs/context.json`; enabled Skill and generated-tool resources are `inputs/configuration-NNN.md`. Context records source paths and the executed package hash. The initial user message contains only entry paths, input hashes, and the output protocol. Eval reads all input with `file_read` and writes `assessment.json` with `file_write`. The framework checks coverage, JSON structure, field constraints, and evidence references and writes `validation.json`. Large reads return complete-line structured previews with the actual `end_line` and next start, counting only delivered lines. A chat reply cannot replace the output file. Invalid output allows at most two repairs with the original evidence and rejection reason, without rerunning the target. Train/dev assessments and human-only test remain separate; tuning can read only categorized training analysis.

File mode uses one assessment input per complete conversation rather than separate framework-created diagnosis segments. Eval may page through the file. Conversations are simple message arrays with `role`/`content`, tool names/arguments/results, and optional timestamps. Each repetition is stored separately, without nested trials, runtime metadata, or duplicate scores. Runtime state, retries, and audit events stay in the framework audit records. Legacy score-completion mode still grades each turn; `dialogue_completion=user` grades once after full execution and diagnoses once using that version's actual instructions. Unscored intermediate turns have `grade=null`, not an invented zero. SDK callers without file tools retain the inline protocol.

**Open optimization folder** opens the experiment root with a navigation `README.md`. Private assessment files are under `evaluations/round-NNN/<case-key>/trial-NNN/<input-hash>/`; categorized training evidence and packages are under `workspace/iterations/`; human-only test stays in `human-test/`, outside tuner access.

When repeated training executions disagree, eval compares complete records to identify successful steps, the earliest failure branch, and reusable interventions. It checks policy and actual tool outcomes rather than making every action in one success mandatory. Before each tuning round, eval synthesizes evidence-backed training priorities for the tuner.

With journaling enabled, `iterations/round-000/`, `round-001/`, and later round directories preserve independent snapshots. `input/training-evidence/` holds the parent evidence used for tuning; `evaluation/training-evidence/` holds actual candidate results; `proposal.json` and `decision.json` hold changes and acceptance. Unexecuted candidates have no fabricated results, and reused evaluations are identified. Host-only validation numbers remain in `validation-scores.json`; they are never copied into the tuner editor evidence. Test material is excluded, original journals remain authoritative, and upgrades do not delete old directories.

Training evidence has an entry index and `mixed/`, `failed/`, and `passed/` groups. Per-case `index.json` links `case.json`, individual `execution-NNN.json` records, `assessment-NNN.json`, and available `comparison.json`. `case.json` retains input, rubric, mode, and optional user context so greeting-only starts have a complete scenario, but excludes reference answers and environment grants. Undisclosed facts and future intent do not imply target knowledge or user authorization and must not become concrete production answers. Cases are stored once, not repeated inside every execution. Read unstable and failing cases first, using successes to preserve working behavior. Validation, test, and direct reference-answer fields stay outside training folders. In file-edit mode the entry is `evidence/training-evidence/index.json`, with paths relative to `evidence/`.

Evaluation separates original responsibilities from candidate instructions. Individual diagnosis, repeated-execution comparison, default model scoring, and training-priority synthesis receive an independent `original_policy`. Candidate restrictions do not automatically become immutable business policy. Compliant but unsuccessful runs may support explicitly labeled hypotheses with conditions and counterevidence, without inventing errors, authorization, or revised scores.

Suite review asks whether a dialogue has a legal path through information gathering, clarification, confirmation, and execution. Initial questions need not contain later confirmations or facts obtainable by authorized tools. Policy scope is interpreted using complete paragraphs, operation sections, parameters, and state transitions. Text-supported consistent interpretations preserving every explicit obligation may leave ambiguity as an advisory note. Irreconcilable goal/policy conflicts, unavailable required facts, and explicit general restrictions still block execution. High model scores, reference actions, and tools accepting a request cannot override prohibitions.

The training entry includes an `experience` path to `experience.md`. Tuning reads cumulative experience before current evidence and returns reusable lessons, conditions, evidence, and hypotheses in `experience_notes`. The host builds the document from actual acceptance and training outcomes, excluding validation/test questions, reference-answer fields, and private rejection reasons. Experience is not part of the production package. Rejected and unevaluated attempts are labeled rather than treated as retained capabilities. Each round preserves its input experience snapshot, a read-only editor copy, and its final cumulative snapshot. Recovery rebuilds experience from journaled round records, not mutable files, without limiting it to the last four rounds.

New Desktop experiments register `runtime/rsi/<run-id>/workspace/` as a project workspace. Run records return `workspace_id` and `workspace_path` for existing workspace APIs. Each round contains:

```text
workspace/iterations/round-001/
  input/training-evidence/          # 调优时的父版本执行评估
  editor/
    package/
      manifest.json                # Agent 配置
      dependencies.json
      files/prompts/rsi-system.md  # 初始为 inline 时生成；已有路径保持
      files/skills/<name>/SKILL.md
      files/tools/rsi/<name>.json
    evidence/training-evidence/    # 编辑器可读，不可写
  version/package/                 # 校验后封存的完整候选包
  version/package-hash.txt
  evaluation/training-evidence/   # 该封存版本的实际执行评估
  proposal.json                    # 框架从文件导出的差异，非第二个编辑入口
  decision.json
  experience.md                    # 本轮结束后的累计调优经验
```

Tuner file tools are bound only to that round's `editor/`, with no process permission. They cannot modify other rounds, sealed versions, original journals, or hidden evaluation material. Package files are authoritative; the final response supplies rationale and separate experience notes. The framework validates changes, seals the candidate, performs independent semantic review, and executes the same bundle in an isolated directory. The next round starts from the retained version. Rejected versions remain recorded but do not become parents. The original listed Agent changes only after explicit application.

New τ-bench hosts use the same directories and protocol. Ordinary resources such as MCP source can enter authorized package paths, but saving source does not bind a runtime. Current Desktop/τ hosts support new Skills and restricted pure tools, not arbitrary MCP-source builds, stdio launch, and version binding. Those need separate host integration. Old experiments cannot silently resume with the new editing protocol; preserve evidence and start a new experiment, reusing verified identical baseline execution when appropriate.

Conversation cards follow their own newest messages, pause when manually scrolled upward, resume at the bottom, and respect reduced motion. `input_visibility=opaque_fixture` declares internal task routing, withholding bubble content until real conversation evidence exists. Frontend polling uses `compact=true` to omit duplicated low-level events, tool copies, and internal requests while retaining conversations, scores, diagnosis, and diffs. Default APIs, journals, and assessment files retain full evidence.

Important executions from recently rejected candidates are under `attempts/round-N/`: failures, unstable cases, new cases absent from the parent, and locally improved paths on the current comparison metric. Entries link same-case analysis, regressions, and `training_improvements` metrics. Overall rejection does not make every step useless; local improvement does not establish overall benefit or causality. Unchanged passing parent traces are not duplicated. Dev-specific rejection details stay private, and rejected proposals are not presented as retained versions.

When the host explicitly binds read-only `file_read` and a workspace, tuning context includes only entry indices and priorities. Desktop/τ use `tuner_workspace` to persist full training evidence outside the package's 256-file/4 MiB quota; the host binds file tools to that directory. SDK callers without a persistent directory can still bundle small evidence. Without authorized file access, budgeted inline feedback remains the default, without implicit tool grants. Invalid diagnosis format or length permits two bounded repairs preserving original responses, without target reruns or numeric score changes. Diagnosis and priorities also receive editable scope to distinguish repairable Agent behavior from immutable environment faults.

Validation measurements and diagnoses remain available to the host and human UI, but never enter tuning inputs. Independent human-test material never enters training-priority synthesis.

## Python API and editable scope

See the [complete API and examples](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/optimization/README.md). `AgentPackageTestGenerator` independently generates reviewable suites; callers can provide `OptimizationSuite` and `OptimizationFinalSuite`.

`optimize(..., rounds=10, optimization_scope=("skills",), constraints=...)` restricts editable parts: `instructions`, `skills`, `tools`, `budgets`, and `resources`. Scope does not grant file or capability access; constraints separately authorize editable files, new paths, tools, Skills, and budget fields. New external names need working authorized host bindings; package Skills and pure tools can be explicitly authorized as below. Tool implementations, model routes, credentials, policies, and flow definitions stay protected.

`suite_reviewer=OptimizationAgent(...)` selects a separate review package/model. Otherwise the evaluation package runs with host audit principles in a fresh Session. Blocking review raises `OptimizationSuiteReviewRejected` before target/tuner execution; `review` and `call` retain evidence, and successful reports retain `suite_review`.

`result.iterations` contains the baseline and valid candidate packages, changes, reviews, and available tests. Invalid proposals remain recorded without executable packages. Optional `journal_path` records progress and partial failure evidence; aborted runs have no normal result or automatic replay. Model feedback bounds diagnosis excerpts and history while preserving caller-visible records. Hosts must also set token/resource budgets and deadlines; excerpt limits are not total prompt budgets.

## Creatable capabilities and repeated evaluation

Hosts can set `OptimizationConstraints(allow_skill_changes=True, allow_skill_creation=True, allow_tool_changes=True, allow_tool_creation=True)` and select `skills`/`tools` in scope. `skill_definitions` maps names to complete versioned `SKILL.md` files; `skills` lists enabled names, without predeclaring every future name. Creation grants apply only inside packages, not to credentials, networking, or processes.

`tool_definitions` creates bounded pure JSON-expression tools with arithmetic, comparison, branching, `filter/map/sort` (`item` is the current element), and `length/sum/at`. Collections are limited to 256 items and execution to 20000 expression steps. They handle retrieved data, sorting, and checks without arbitrary code or external side effects. Existing business tools remain host-bound.

Prefilled `OptimizationCase` can include `reference_answer`. Eval receives it and the fixed rubric; targets receive only input and simulated users only user context. Training references may inform feedback; dev references and feedback remain hidden from tuning; test belongs to the independent human observer. Hosts must validate references rather than treating unverified model answers as truth.

`evaluation_repeats=3, evaluation_aggregation="mean"` selects using the three-score mean and preserves every execution and assessment. `passed` still requires every repetition to pass for reliability and stable success. Default `minimum` retains conservative legacy aggregation. `refresh_incumbent=True` remeasures the retained package after semantic approval, avoiding indefinitely reusing lucky scores. Hosts supporting seeds can read shared trial identifiers from `OPTIMIZATION_TRIAL`.

With a complete fixed training suite, supply `suite` and `grow_training=False` to use all cases from baseline. Independent dev and overall-improvement selection remain. Default generated suites still grow. These are generic SDK options rather than benchmark-specific rules.

Trusted local hosts can use `examples/v2/desktop_optimization_mirror.py` to mirror external journals into Desktop history. Curves, matrices, processes, and diffs reuse production components. External versions stay read-only when they need uninstalled business tools. Mirroring is one-way observation and does not expose test scores to tuning.

## Desktop history and confirmation

Agent settings provide separate **RSI** and **Version history** entries. RSI contains background runs and candidates; Agent history contains manually saved or explicitly applied configurations. Unapplied candidates remain inside their run.

Leaving a page does not stop the sidecar job. Reopening shows persistent progress, answers, and review findings. Sidecar exit marks unfinished jobs interrupted; new local experiments can resume the same record, reusing completed cases, diagnosis, question-generation responses, tuning, and review decisions while preserving the original journal.

Optimization never changes the active configuration. Preview a version, select **Use this version**, and explicitly confirm. Backend fingerprint checks reject overwriting changed configurations, unfinished candidates, and semantic-review failures. Completed alternate iterations show whether final evaluation was performed.

Desktop supports simple Agents, native tools, temporary workspaces, and host sandbox limits. MCP is limited to explicit `sage.rsi.case/v1` stdio-isolated fixtures; arbitrary external MCP, Shell fixtures, and non-simple Agents are unsupported. A single sidecar persists jobs, with user recovery and explicit transient-model automatic recovery, not distributed takeover. Recovery verifies the model, Agent configuration, evaluation settings, and engine fingerprint. Disposable Desktop test workspaces allow unfinished local execution to restart; generic SDK hosts must reconcile unknown external outcomes. See the [Desktop implementation guide](https://github.com/ZHangZHengEric/Sage/blob/main/app/v2/desktop/README.md#rsi-与-agent-版本).

## Real-model experiments

The opt-in [domain benchmark](https://github.com/ZHangZHengEric/Sage/blob/main/examples/v2/optimizer_domains.py) reads an explicit `--catalog` JSON model catalog using `openai-responses` and makes billable calls. It exports original and candidate packages, suites, model/Session evidence, reviews, and comparisons. Credentials resolve only in memory; output directories must be new. It never activates a production Agent.

On 2026-10-12, Skill-only and tool-selection experiments each reached 3/3 final cases. Joint scope also reached 3/3 but changed only a Skill, so simultaneous instruction/Skill modification was not demonstrated. All used four proposal rounds with no new changes after the first accepted version. Skill/tool tests reused old final cases and measure regression; the clarified joint run used newly sealed cases. Preserve failures and review rejections; small samples do not establish general reliability.

### Responsibilities of prompts, Skills, and tools

The system prompt holds persistent rules, priorities, Skill triggers, and completion checks. Skills hold on-demand multistep procedures with inputs, branches, tool use, validation, and failure handling. Tools implement verifiable computation or controlled actions. Skills follow Voyager-inspired reusable and composable capability principles: descriptive names, clear prerequisites and observable completion, parameterized entities and values, and actual available dependencies, without invented tools, cycles, or copied exploration traces. Inspect real tool output, handle missing input, empty results, errors, and state changes, and define clarification, stopping, and recovery conditions. Never blindly replay unknown external effects. Failures identify bad decisions; successes help preserve working capabilities. Production prompts must exclude case answers, optimization commentary, and patch history, and must not turn one successful trace into an unconditional procedure.

File editing derives internal `system_prompt` differences from actual files; the tuner need not return them. Legacy SDK `system_prompt` fully replaces text, is mutually exclusive with `instruction_guidance`, and remains scope/permission/length constrained. Omitting it preserves the current candidate. New Desktop/τ experiments disable legacy append mode; old records remain unchanged. Experimental candidates still require explicit user application.

## Custom scoring and execution diagnosis

Built-in scoring defaults to **Quality**, preserving selection behavior. Explicit alternatives are **Quality and cost**, **Quality and latency**, and **Quality and token usage**. Desktop exposes them in scorer selection; MCP `rsi_start` uses names such as `builtin_scoring="quality_cost"`; SDK/API use `BuiltinScoring`. Resources come from actual target execution, not model estimates, and exclude tuning, generation, and evaluation overhead.

Each repetition records full-Session input, output, cached-input and reasoning tokens, cost, and `usage_reported`. Native runners read usage increments at execution boundaries from persistent events. Continuing a Run after user input adds only new usage; conversation turns are summed without duplication. Cached input is already included in total input. Missing or partial provider usage is not zero; token mode requires explicit `usage_reported=True`, including custom runners. Original values stay in existing audit and assessment records.

Efficiency selection uses `quality × (1 - weight + weight / (1 + usage / reference))`, default weight 0.2 and references of one host-reported cost unit, 60 seconds, or 10000 input/output tokens. SDK/API configuration is frozen into the recovery fingerprint. Zero quality cannot gain points by being cheap. Explicit efficiency modes permit tradeoffs, but goals and stability still use quality and pass state. Shared-case weights and repeat aggregation remain unchanged. Reports retain `grade.score`, `objective_score`, `score_metrics`, and round-level selection deltas; human-only test measures quality. Cost mode fails when real cost data is unavailable. External scorers can provide quality before the host applies the chosen efficiency mode.

Without a custom scorer, internal eval grades and diagnoses. With a Python scorer, `score(request)` owns rule checks, model judging, and numeric grades. The framework supplies standard data and evidence, validates the result, and offers a direct ModelProvider proxy using Sage adapters and concurrency budgets, without a separate host model-grading route. Eval still analyzes causes, strengths, unstable paths, and improvements but cannot change scores or pass states. Exceptions, timeouts, or explicit nonapplicability never fall back to internal scoring. Numeric scores drive selection/convergence, while test remains human-only. See the [dataset and scorer protocol](../../../evaluation_datasets/README.md).

### Dialogue completion

`dialogue_completion=user` lets the simulated user continue until scenario completion, inability to proceed, or the turn cap, followed by one scoring call and one diagnosis. Intermediate turns store execution only. Default `score` retains score-based completion. Dialogue identity combines the initial input with user context, so different scenarios sharing a greeting are not duplicates. Training and human-only test share simulator boundaries; targets see only actual user messages.

The page distinguishes scoring, diagnosis preparation, assessment repair, and recovery wait using actual phases and counts unfinished calls. Failure or cancellation closes a call; recovery wait does not keep old execution tasks active.

Default internal scoring must also diagnose full execution. A file containing scores only is invalid; inline evidence indices must reference the supplied simple conversation array, not nonexistent runtime events. External scoring remains the sole numeric authority.

Human-only test stores content-free error stage/code separately for execution, scoring, and diagnosis. Retry only explicit transient transport failures, never valid zero scores. Scoring/diagnosis retries reuse execution and existing scores. Tool-free internal roles are safely restartable; file roles require declared private-directory isolation, and target-dialogue restart requires an explicitly disposable simulated environment. SDK defaults grant neither write-role restart nor target restart. Exhausted errors stay errors, not zero-filled or silently omitted samples.
