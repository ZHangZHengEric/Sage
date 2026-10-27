# AgentPackageOptimizer

Native MCP observations preserve every immutable item and bind any within-batch
call-order projection to matching proposal/result receipts. Proposal order alone
does not establish environment execution order; authoritative scorers must still
replay and validate every environment outcome. Missing or conflicting receipts
never authorize an inferred action or reward.

Local file evaluator recovery replays durable responses through the original
file/schema/evidence checks, including a rejected response and its recorded
bounded repair. It preserves suspended native states; recovering a response is
not accepting its assessment. This requires the host's file-only evaluator grant.

An independent Python API for testing and improving a supplied
`AgentPackageBundle`. It does not modify the original object, register packages,
activate a version, or alter the target Agent's normal runtime loop.

## API

```python
from sagents.v2 import (
    AgentPackageOptimizer, IsolatedOptimizationRunner,
    OptimizationAgent, OptimizationConstraints,
)

# evaluator_package and tuner_package are ordinary AgentPackageBundles with
# their own instructions and model routes. They should have no mutation tools.
# builder_factory(package, workspace, context) returns a fresh SAgentBuilder.
# authorize(action, package, context) enforces host grants; action=optimize_run.
runner = IsolatedOptimizationRunner(
    builder_factory=builder_factory,
    authorize=authorize,
)
optimizer = AgentPackageOptimizer(
    runner=runner,
    evaluator=OptimizationAgent(package=evaluator_package, agent_id="evaluator"),
    tuner=OptimizationAgent(package=tuner_package, agent_id="tuner"),
    # Optional separate audit package; each review uses a fresh Session.
    # suite_reviewer=OptimizationAgent(package=audit_package, agent_id="suite-reviewer"),
    # Optional separate test designer; otherwise the evaluator designs the suite.
    # test_designer=OptimizationAgent(package=designer_package, agent_id="designer"),
)
result = await optimizer.optimize(
    target_package,
    agent_id="assistant",  # optional for a package with an Agent entrypoint
    context=request_context,
    goal="Improve task completion while preserving the agent's responsibilities",
    rounds=10,  # default 5; accepts 1..100; maximum when stopping_policy is set
    constraints=OptimizationConstraints(
        editable_files=("skills/conversion/SKILL.md",),
        editable_budget_fields=("max_steps",),
    ),
    validation_case_count=24,  # 1..100, fixed independently of training
    # suite=imported_suite,  # optional starting training and fixed validation
    min_improvement=0.01,
    call_timeout_seconds=120,
    timeout_seconds=3600,
    evaluation_repeats=3,  # optional, default 1; fresh target runs + evaluator Sessions
    journal_path="optimization-audit.jsonl",  # optional, must be a new file
)
candidate = result.candidate_package
report = result.report
```

Run the offline runtime example:

```sh
.venv/bin/python -m examples.v2.package_optimizer
```

## Tests and selection

The default workflow independently designs a fixed validation set (24 questions by
 default, `validation_case_count=1..100`) and an initial training set. At every
round, the designer inspects the CURRENT retained package, prior training questions
and bounded training results. `initial_training_case_count` sets the initial training
batch (1..100), and `training_cases_per_round` sets each round's additions (0..100;
0 freezes the training set). Desktop defaults to 6 and 6. Accumulated questions
remain in every subsequent round. Imported training cases form an ordered pool:
consume its initial batch, then append the next batch each round; only when that
pool runs out, a generated experiment may design further additions. Imported fixed suites never extend beyond their frozen training pool. Historical
rounds are not rerun on new questions. SDK callers omitting the initial count
retain their supplied suite as the initial set. Imported
`OptimizationSuite` supplies training and fixed validation; the configured
validation count must match its validation split. Case IDs must be unique.

Deterministic import validation is separate from semantic preflight. Malformed
protocols/fields, duplicate IDs, invalid splits, unavailable environment bindings
and failed scorer self-tests prevent execution. A model review is an evidence-
bearing opinion, not proof of a dataset defect. Supplied fixed suites keep their
original cases and scorer even when `suite_review.approved` is false; the opinion
is retained verbatim. Generated drafts are repaired by the designer up to
`SuitePreflightPolicy.generated_repairs` times (default 2) before admission.
Unrepaired drafts are quarantined with the rejected opinions and repair history;
an experiment without its required valid seed/dev set still fails explicitly.
Invalid model responses and transport/runtime errors remain separate failures.

Human dataset management uses immutable `DatasetVersion` artifacts and confirmed
`DatasetRevisionRequest` exclusions. Original cases are preserved. Each mark
records its case ID, reason, evidence, authenticated operator, timestamp and
source version. Low scores, failures, variance and model inability are not defect
types. A revision is always labeled **revised dataset**, including in reports;
complete-source test targets retain their original denominator. Revisions apply
only to new runs and never change an active run's membership or denominator.
The frozen membership, exclusions and `SuitePreflightPolicy` are recovery-bound.
The optimizer receives version counts and a digest, not hidden test IDs or
exclusion evidence. Dataset management is absent from model-facing MCP tools.

The validation designer sees the original package and previously generated
validation questions only. The training designer sees current capabilities and
training evidence, never validation questions or feedback. Separate fresh Sessions
keep design requests independent. Host checks and an explicitly enabled independent suite reviewer
check policy/rubric consistency, authorization and executable fixtures. They do
not judge cross-split leakage or question memorization.

New training questions first run against the incumbent package. The incumbent and
proposal are then compared on exactly the same cumulative questions; adding hard
questions cannot itself be misreported as a proposal regression. Acceptance uses only the fixed validation mean, or its built-in resource objective
when enabled. Training scores remain available for diagnosis and guidance, but do
not contribute to acceptance. A candidate is retained when that validation score
improves by at least `min_improvement`. Individual regressions are allowed,
recorded per round, and carried forward for repair from the retained package.
Mixed `overall_score` and `overall_before/after` remain historical reporting fields,
not selection criteria.
Execution completion and enabled generated-tool integrity audits still gate
acceptance. Candidate checks are deterministic by default; an explicitly supplied
semantic reviewer is an additional host opt-in gate.

Tuning receives bounded training evidence, previous attempts, retention status
and the retained parent identity. Validation aggregates, pass counts, anonymous
per-question scores, historical scores and mixed train/dev selection scores are
host-only. No validation question text, original IDs, rubrics, answers or grading
rationale is included in internal tuning inputs.
The external RSI MCP is instead a user-delegated review interface: all read modes
can expose train/dev grades, diagnoses, executions, regressions and selection
metrics; `rsi_questions` includes dev questions. Compact score summaries explicitly
name baseline/selected training and validation means. Test data, reference-answer
fields, credentials and unclassified raw internal calls remain excluded. Review
output is not automatically supplied to the internal tuner. External edits based
on dev feedback still make dev part of development, not an independent final exam.
The tuner additionally receives unresolved training regressions with their prior
scores and current training evidence. Growth feedback exposes host scheduling and
training facts, but no validation regression counts or private gate reasons.
Retention and scheduling still convey indirect feedback, so hiding scores does
not make repeatedly used dev data an untouched final exam.
Host reports, journals, `validation-scores.json` and Desktop retain the full
measurements, mixed scores and regression diagnostics for user inspection. The
training evidence directory and experience-document layout stay unchanged. This
visibility change updates the recovery engine fingerprint; resume old experiments
with their original engine or start a new run instead of replaying old requests.

Retaining progress and verifying stable success are separate. At a round or
patience limit, the adaptive result keeps the retained stronger package and its
evaluation; it does not silently fall back to the original. `goal_verified=false`
and `recommendation_block_reason` indicate that the stable-success target was not
established, and no iteration is marked recommended. Nothing is auto-applied.

No final suite is generated or executed in the default workflow. For old SDK
clients only, explicit `validation_case_count=None` retains the legacy fixed-suite
path and its optional final-suite arguments. Desktop and MCP always use the new
adaptive workflow; historical final records remain readable.

## Editable scope and resources

Desktop and tau-bench use `optimize(..., edit_package_files=True,
tuner_workspace=...)`: each round copies the retained package into
`iterations/round-NNN/editor/package/`. The tuner directly edits `manifest.json`
and `files/` (prompt resources, Skills, granted tool definitions/resources), with
`evidence/` read-only. It returns a rationale and optional `experience_notes`,
which are learning notes outside the production package. The host derives the audit
patch, validates all file and manifest changes, seals `version/package/` with its
content hash, then loads that exact validated immutable bundle.
The editor cannot write another round or the sealed version. No process tools are
granted. Ordinary code resources require explicit file grants and a real host
execution binding; saving MCP source does not itself launch a server.

`restart_package_editor=True` is a separate trusted host attestation, requiring a
frozen binding ID. It permits resetting interrupted, isolated local edits from the
retained parent; completed authored bundles are journaled for exact recovery.
It is not a read-only grant and does not authorize external target effects.

The baseline bundle is immutable. `OptimizationPatch.system_prompt` replaces the
candidate's complete production prompt, without adding a framework heading or
requiring a verbatim original prefix. Reorganize, consolidate and correct the prompt
while preserving original business-policy meaning, responsibilities and permissions.
Keep responsibility and permission behavior in the fixed test rubrics and tuner
authoring principles; deterministic validation does not prove semantic equivalence. Other
agents' instructions are unchanged. `allow_system_prompt` and
`max_system_prompt_chars` control this grant and its size limit.

System prompts contain always-needed rules, decision priorities, capability routing
and completion checks. Skills contain conditional reusable procedures with clear
triggers, inputs, branches, actual tool calls, verification and recovery. Tools
implement bounded capabilities. The tuner receives host principles for choosing
among these artifacts and converting failed/mixed traces into causal fixes while
preserving successful behavior. Production artifacts must not contain optimization
history or patch appendices.

`instruction_guidance` remains readable/applicable for legacy SDK clients; it is
mutually exclusive with `system_prompt`. Desktop and the tau-bench host disable
new legacy overlays (`allow_instruction_guidance=False`). Historical packages and
journals are not rewritten.

Skill/resource edits replace explicitly allowlisted bundled files or create explicitly allowlisted new paths.
Base instruction files and `extensions/` source code cannot be allowlisted.
Budget changes require individually allowlisted fields. Tool/Skill grants are separately opt-in as described below. Other manifest
settings (model routes, credentials, policies, flows,
entrypoints, other Agents and tests) remain unchanged. Each valid proposal receives
an independent version; original content is never overwritten. The result is the
best retained version or a copy of the original when nothing improves.

The native runner materializes bundled files into a fresh temporary workspace
before calling the builder factory. Bind candidate Skill ports to that workspace,
for example `FilesystemSkillProvider((workspace / "skills",))` together with the
host's Skill workspace via registered `skill.provider` and `skill.workspace` capabilities selected through runtime.
External Skills must be copied into the bundle to edit them; otherwise the host
must provide stable versioned bindings for comparisons. Model routes, tool
fixtures and external data must also remain stable across runs. Credentials are
resolved by the host, not copied into optimization output.

Temporary directories and fresh sessions provide context/file separation, not
an OS security sandbox. Supply sandbox bindings or test doubles for side-effecting
tools and isolated memory/resource providers. The runner intentionally does not
load bundled Python source plugins. Every invocation is authorized before building.
Custom runners implement `OptimizationRunner.run(package, agent_id, content,
context)` and must provide the same isolation/authorization guarantees.

## Reports and failure behavior

`result.report` contains the goal, requested rounds, cumulative suite, baseline and
selected evaluations, and every round's parent hash, patch, candidate, evaluation,
acceptance and reason. Per-case observations retain native result evidence,
elapsed time, token usage and reported cost. Internal designer/evaluator/tuner
observations are retained in `agent_calls`, so overhead is visible too. Missing
provider cost remains `None`. The default built-in selection metric remains quality.
Optional resource-aware metrics are described below. Reports and intermediate candidate files
may contain sensitive task evidence; storage/redaction is the caller's concern.

### Run-local tuning experience and Skill authoring

The existing `training-evidence/index.json` links `training-evidence/experience.md`.
Each tuner reads accumulated experience before current mixed/failed/passed evidence.
The host reconstructs this document from ALL previous round records, not only the
four recent attempts shown inline. Notes record reusable mechanisms, applicability,
supporting training evidence and unresolved hypotheses. Acceptance and evaluation
status are host facts; a proposed explanation is not established by acceptance.
No validation/test questions, reference-answer fields or private rejection rationale
are copied into the experience document. Do not put optimization history in Skills
or production instructions.

Each `input/training-evidence/experience.md` freezes what that round actually saw;
file editors read its protected `editor/evidence/training-evidence/` copy. After
the round completes, `round-NNN/experience.md` stores the updated cumulative
snapshot. Existing training groups and candidate/evaluation directories keep their
roles. No-change and rejected attempts can still contribute explicitly qualified
lessons. Notes live in `patch.experience_notes` in the journal, so recovery rebuilds
the same input without trusting mutable files. Without file-reading tools, a
bounded inline document preserves an entry for every prior round; the full final
document is available in `result.report.tuning_experience`.

Skill guidance follows reusable and composable capabilities, inspired by
[Voyager](https://voyager.minedojo.org/): make purpose and triggers discoverable;
specify preconditions, parameterized inputs, actual available tools and observable
postconditions; handle empty results, errors, clarification and safe recovery.
Reuse existing capabilities without inventing dependencies. Retain successful
decisions and their applicability, rather than copying an entire successful trace.
Check other disclosed training cases and preserve existing successful behavior.

### Built-in selection metrics

`BuiltinScoring()` defaults to `mode="quality"` and preserves existing acceptance.
Desktop's scorer picker and MCP's `rsi_start(builtin_scoring=...)` also default to
quality. SDK and Desktop API callers may explicitly select `quality_cost`,
`quality_latency`, or `quality_tokens`:

```python
from sagents.v2 import BuiltinScoring

result = await optimizer.optimize(
    target_package, context=request_context, goal="Improve reliable completion",
    builtin_scoring=BuiltinScoring(mode="quality_cost", efficiency_weight=0.2,
                                   cost_reference=1.0),
)
```

Quality still comes from eval or the configured authoritative scorer. Its
`grade.score`, diagnosis and `passed` remain unchanged. Resource-aware modes compute
a separate per-execution `objective_score`:

`quality * (1 - efficiency_weight + efficiency_weight / (1 + resource / reference))`.

The default weight is 0.2; references are 1 cost unit (the provider's reported cost
unit), 60 seconds or 10,000 input-plus-output tokens. References are fixed across
versions and included in recovery fingerprints. Zero quality cannot be rescued by
cheap execution. These opt-in modes permit quality/resource trade-offs; they do
not impose an additional no-quality-regression guarantee. Selection equally weights
training and validation objective means on the same common cases. Repeated trials
aggregate their objective scores with the requested mean/minimum policy; resource
metrics are averages per execution, not totals across repeats. Dialogue costs and
tokens include all target turns. Optimizer/evaluator overhead is separate.

`score_metrics` retains measured resources and quality. Reports preserve quality
scores and separate `objective_before/after`; stable task success still uses the
quality/pass criteria. Human-only test observations continue to measure quality.
Missing reported cost is an error for `quality_cost`, never free execution or a
silent fallback. `quality_tokens` likewise requires `usage_reported=True` on each
target observation; custom runners must attest complete provider usage.
These built-ins can be combined with an external quality scorer;
they do not give the target/tuner access to the scorer or hidden evaluation data.

The native runner reads durable usage events across the complete send boundary,
independently of trace-size limits. Each case/trial observation retains input,
output, cached-input and reasoning tokens, cost and `usage_reported`. A simulated
reply that continues the same suspended Run records only the new usage segment;
dialogue aggregation sums those segments into the entire case Session. Cached
input is a subset of canonical input tokens, so it is not added again. Missing
or partial provider usage stays marked incomplete; partial reported cost is not
presented as a complete bill. Raw counters and per-turn/trial records survive in
the audit/report, separately from internal tuning/evaluation consumption.

Malformed or out-of-scope patches consume one rejected round without executing a
candidate. Valid no-change patches retain the current version and reuse its evaluation. Without a stopping policy, rejected rounds do not stop the loop. There is no automatic retry of an execution. Non-completed internal Agent runs, malformed evaluator/designer
responses, authorization failures and other runner errors abort the operation.
Timeouts and cancellation propagate; the native runner closes its Application
and removes the temporary workspace. No normal result is returned on abort.
Opt-in `journal_path` preserves incremental records as described below.
Configure host model-call/token budgets in the builder factory in addition to
round/case counts and per-call/whole-operation deadlines. A caller can save the
successful result and report, then separately decide whether to publish/activate.

## Standalone test-set generation

Test design is also available without a tuner or running the target:

```python
from sagents.v2 import AgentPackageTestGenerator, OptimizationAgent

generator = AgentPackageTestGenerator(
    runner=runner,
    designer=OptimizationAgent(package=designer_package, agent_id="designer"),
)
suite = await generator.generate(target_package, context=request_context, max_cases=8)
# Include the designer's full request, response and configured package:
generation = await generator.generate_with_record(
    target_package, context=request_context, max_cases=8,
)
# Convenience API when an optimizer already exists:
suite = await optimizer.generate_test_suite(target_package, context=request_context)
```

Goals default to the target's resolved instructions. Generated rubrics are
reviewable model output, not proofs. The designer runs in its own Session; each
case is later judged by the evaluation Agent in a separate fresh Session. The
controller never substitutes code-based grading for the evaluation Agent.
Objective checks can be supplied as observation evidence and used to independently
audit evaluation quality for mechanically checkable tasks.

## Tool and Skill selection

Capability selection is opt-in. Existing tools/Skills can be removed, retained,
or replaced with explicitly host-provided candidates:

```python
constraints = OptimizationConstraints(
    allow_tool_changes=True,
    tool_candidates={"calculator": "Exact arithmetic; no external effects"},
    allow_skill_changes=True,
    skill_candidates={"units-v2": "Reusable unit-conversion procedure"},
    creatable_files=("skills/units-v2/SKILL.md",),
)
```

A patch's `tools`/`skills` replaces the target's full allowlist. `None` preserves
it and `[]` removes all entries. New names must be host candidates, unless the host explicitly enables the generated pure-tool contract below. Descriptions
inform the tuner; the host must bind working implementations and enforce grants
on every invocation. Candidate names alone do not register or authorize anything.
Creating bundled Skill files requires individually allowlisted paths; source
plugins still cannot be added or rewritten. Model routes, request sampling
parameters, credentials, policies and flow definitions remain protected. Budget
fields are editable only when individually allowlisted.

The internal tuner's System instructions include host-owned principles: diagnose
mechanisms, propose small generalizable changes, never copy test questions/IDs/
answers into instructions or Skills, avoid growing case exception lists, and
allow legitimate no-change rounds. This is a model behavior constraint, not a
semantic guarantee. Keep validation cases hidden and inspect the returned diffs.

### Generated pure tools

With both `allow_tool_changes=True` and `allow_tool_creation=True`, and `tools`
in the requested optimization scope, a tuner may return `tool_definitions`:

```json
{
  "rationale": "Make arithmetic reproducible",
  "tools": ["rsi_multiply"],
  "tool_definitions": {
    "rsi_multiply": {
      "description": "Multiply two numbers",
      "input_schema": {
        "type": "object",
        "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
        "required": ["a", "b"], "additionalProperties": false
      },
      "expression": {"op": "mul", "args": [{"var": "a"}, {"var": "b"}]}
    }
  }
}
```

Implementations are bundled at `tools/rsi/<name>.json`. Returning a definition
creates or revises that implementation; `tools` separately selects the enabled
names. Names use the ASCII `rsi_` namespace and cannot shadow native tools.
A package supports at most eight generated tools. Expressions have bounded depth,
node count and size, with JSON literals, objects, arrays, argument paths, lazy
conditionals, logic, comparisons, arithmetic, membership and concatenation.
`concat` joins strings only; use literal arrays and conditional branches to construct lists.
They cannot execute source code, access the host, resolve schema references or
change tool permissions. Editing these files through the generic `files` patch
is rejected. Definition creation/revision requires the explicit tool-creation grant.

The host must compose `generated_tool_provider(bundle.files)` into its isolated
runner and normal activated runtime; package metadata alone never executes a
new tool. Desktop provides both bindings. Serialized packages retain complete
implementations, so candidate comparison and rollback restore the actual tool
behavior. Inspect tool-call evidence along with output grades. These tools are
pure calculators/validators/rule processors; external actions still require
host-provided implementations and grants.

## Stopping and diversity

The adaptive workflow enables `OptimizationStoppingPolicy` by default: all
accumulated training and fixed validation cases must pass with score >= 0.95,
followed by a fresh complete evaluation (two independent passes total). Failed
fresh evidence replaces the measurement of that package; training details reach
later tuning, while validation results remain host-only. Reused results do not establish
stability. Every new round first adds training challenges; the training set grows
until the run stops. Three rounds without retained improvement stop for
stagnation; maximum rounds and host timeouts also apply.

`goal_verified` reflects stable training/validation success, with no final exam.
Failure to converge withdraws the recommendation. Reports, journals and historical
iterations preserve actual grades. Business-policy and permission checks remain;
question leakage and memorization checks are not part of adaptive RSI.

## Every iteration is returned

`result.iterations` includes iteration zero and every valid candidate, including
ones the controller did not recommend. Each entry includes the full Package,
patch, semantic review and selection reason. Evaluated entries retain per-case
inputs, outputs, evidence and grades. A semantically rejected version has
`evaluation=None`; it was not executed and its failure is not fabricated as a test grade.
`recommended` identifies the controller's preferred version; users choose which
version to use. `result.candidate_package` remains a convenience recommendation.
A no-change round includes the same Package and explicitly marks
`evaluation_reused=True`; tests are not falsely claimed to have run again.
Malformed/out-of-scope attempts are retained in `report.rounds` with their failure
reason and Agent response; they cannot produce a valid runnable Package.

`report.internal_agents` contains the designer/evaluator/tuner/reviewer configurations.
`report.agent_calls` contains each full request/response with its round and case
id. Reports distinguish the evaluation Agent's `model_grade` and the grade used
for selection. With `require_clean_generated_tools=True`, a failed generated tool
execution or incomplete trace fails the effective grade while preserving the raw
model grade and real completed runtime state. Repeated trials aggregate grades
conservatively and retain every raw trial.
The native runner additionally captures bounded tool/flow/artifact runtime
records, with an explicit truncation flag. Artifact URI references in ephemeral
workspaces may expire; a host runner must capture artifact content if a rubric
requires it after teardown.

## Quality ceilings and efficiency

In the legacy fixed-suite path (`validation_case_count=None`), a split already
scoring 1.0 need not improve beyond its ceiling. Other splits
must still improve by `min_improvement`, and individual score/pass regressions
are rejected. Equal-quality changes alone are not recommended by default.
For latency goals, opt in with `min_latency_improvement=0.20`; a candidate may
then be recommended if every case passes, it preserves every case's grade and reduces total target
execution time by at least 20%. This excludes evaluation/tuning overhead.
Latency is noisy; independently repeat fresh unseen cases before treating the
measurement as durable. Costs and tokens remain reported metrics rather than
selection gates.

## User-supplied questions and multi-turn dialogue

Pass an `OptimizationSuite` directly to `optimize(suite=...)` to skip generation.
The collection must include training and validation cases. Each case specifies
its original goal/input and fixed success rubric. Cases can be single-turn or
interactive:

```python
from sagents.v2 import OptimizationCase, OptimizationSuite
suite = OptimizationSuite(cases=(
    OptimizationCase(
        id="addition", split="training", mode="dialogue", max_turns=3,
        input="Ask me for two integers, one at a time, then add them.",
        user_context="The first integer is 17; the second is 25.",
        rubric="Ask in order, use the supplied numbers, then produce 42.",
    ),
    OptimizationCase(
        id="greeting", split="validation", mode="dialogue", max_turns=3,
        input="Ask my name, then greet me using that name.",
        user_context="My name is Lin.",
        rubric="Ask first, then greet Lin; do not guess the name.",
    ),
))
result = await optimizer.optimize(package, context=context, goal="Complete the original user goals", suite=suite, rounds=5)
```

For a dialogue case, the target uses ONE isolated Session across all turns.
Each turn is a new native Run against that Session, retaining previous messages.
Separate cases/candidates have separate Sessions. A test-dialogue Agent simulates
user replies from `user_context`, which is hidden from the target until disclosed
through replies. It never supplies rubrics or expected answers to the target.
Configure it with `test_driver=OptimizationAgent(...)`; otherwise the test
designer's model/package is reused with a dedicated host user-simulation System
instruction. Test design and user simulation are two modes of the test role.

After every target turn the evaluator runs in a NEW independent Session, sees
the original goal, fixed rubric and full conversation, and determines whether the
goal has been achieved. It cannot declare a mere clarifying question or partial
progress to be successful completion. Success stops the dialogue early.
`max_turns` counts target turns including the first response (default 5, 1..20).
If the evaluator has not marked success by the limit, `stop_reason="turn_limit"`
and `grade.passed=False`. Missing user facts yield `driver_blocked` rather than
fabricated answers. Failed/cancelled/suspended target runs are separately recorded.

Complete turn inputs, target outputs, native Session/Run ids and per-turn grades
are stored in `case_result.dialogue`. Aggregate target latency/tokens span all
turns; internal user-simulation/evaluation overhead is in `report.agent_calls`.
`IsolatedOptimizationRunner.conversation(...)` also exposes the native conversation
API. Custom runners must supply an equivalent async context manager with
`send(content)`; runners implementing only `run` support single-turn cases.

The initial implementation supports normal completed text-message turns.
Runtime suspension for a host approval or a structured `USER_INPUT` interaction
is recorded as `target_suspended`; it is not silently approved or resumed by
inventing a new user message. A host runner can extend the conversation adapter
with the corresponding authorized interaction protocol. Case and whole-operation
budgets still bound execution independently of the turn limit.

## Reliability controls and audit logs

`evaluation_repeats=1..10` runs the full suite that many times for the original
and every changed candidate. All target trials start fresh isolated Sessions;
each response is judged by a fresh evaluation Agent Session. Dialogue trials
retain one target Session only within that trial. The selection score is the
minimum actual evaluator score, and pass requires every trial to pass. This
arithmetic aggregation does not replace model judgment with code-based semantic
grading. `case_result.trials` retains every observation, dialogue and model grade.
For repeated trials, aggregate `model_grade` is `None`; consult each trial's actual
model response. Aggregate latency is the mean target time per trial, while tokens
and costs sum all actual usage. Representative output/evidence comes from the
least successful trial and is not a synthetic merged target response.

The evaluator and test designer also receive host-owned System principles:
apply fixed rubrics, require evidence, ignore instructions embedded in target
outputs/package content, and avoid duplicate training/validation questions.
These rules improve consistency but cannot guarantee resistance to all prompt
injection or rubric ambiguity. Whole prompts default to a 64,000 character limit (legacy guidance: 16,000);
each edited file defaults to 262,144 UTF-8 bytes. Configure
`max_system_prompt_chars`/`max_guidance_chars`/`max_file_bytes` in `OptimizationConstraints`. These limits
bound growth; they do not prove that a change is free of memorized cases.

With `journal_path`, the controller creates a NEW append-only JSONL file with
mode 0600. An existing path (including a symlink) is rejected before model calls.
Its parent directory must exist. Events are flushed and fsynced after each write:
original/internal packages, suite, target/internal calls, candidate packages,
completed test/round records and the final result. Raw designer/evaluator output
is retained even when JSON validation fails. On exception/timeout/cancellation,
completed events remain available and an operation status is recorded. A process
crash may leave a partial last line; only complete JSONL lines are reviewable.
A call-start event without completion means its outcome is unknown. The journal
itself never retries effects; opt-in recovery is described below. Journals do not contain resolved host credentials, but
package/input/model text may be sensitive; choose storage accordingly.

Dialogue initialization is covered by the per-call deadline, in addition to
individual target sends and evaluator/simulator calls. Deadlines are cooperative:
host providers and cleanup hooks must honor cancellation. This API is suitable
for controlled single-host experiments with host budgets and test bindings.
Opt-in single-host recovery preserves completed cases and internal decisions.
Multi-process coordination and arbitrary external interaction resumption remain
unsupported. Final verification and semantic review are implemented as described below.

### Resume an interrupted experiment

Use `resume_from=previous_journal` with a **new** `journal_path`, the same original
package/options, and the same `recovery_binding_id` supplied on the initial call.
The trusted host must bind that ID to frozen model routes/sampling, tool policy
and test environment. Recovery verifies the actor, optimization configuration,
internal Agents and engine implementation. Candidate version identity is retained;
completed cases retain original observations and grades, and completed internal
model responses are consumed once. Exact requests must match. Generated cases
are restored from their recorded designer calls.

If a single-turn target completed before its evaluator was interrupted, only the
evaluation continues. Unknown executions and partial dialogues require host
reconciliation by default (`OptimizationRecoveryRequired`). A trusted host with
explicitly disposable, isolated environments may set `restart_incomplete=True`;
this does not authorize retrying real external side effects. A new journal records
reused evidence explicitly and preserves its source logs. `journal_start_sequence`
can keep a host's event cursor monotonic across journal parts.

Native `model.provider_transient` failures raise `OptimizationTransientFailure`
instead of becoming scored zeroes. A host can wait and resume from the durable
journal after reconciling/discarding the interrupted environment. Desktop supplies
this bounded recovery policy and a Resume evolution action for interrupted runs.


## Independent business and permission review

Candidate validation defaults to fixed host rules, without a reviewer model call.
Scope, structural, binding, metadata and resource errors are returned to the tuner
for up to `max_edit_repairs` corrections in the same round. Exhaustion rejects the
proposal without executing it. Passing validation is not a semantic approval.
Desktop uses this mode. Dataset validation also defaults to fixed rules without a review model. An explicit
`suite_reviewer=OptimizationAgent(...)` remains a separate SDK opt-in mechanism;
there is no evaluator fallback. Generated JSON/schema, count and split errors are
returned to the designer with bounded `validation_repairs` (default 2; Desktop
uses `SuitePreflightPolicy.generated_repairs`), retaining each response before admission.
The candidate-validation mode is frozen in the recovery configuration; changing it
cannot silently resume an old experiment.

SDK hosts may explicitly supply `reviewer=OptimizationAgent(...)` to opt into an
additional independent semantic gate before execution. There is no evaluator
fallback for candidate review. This reviewer sees original/current/candidate packages, the authorized
goal, host constraints and training evidence. It does not see validation questions
or results. It checks goal drift, changed grading requirements and unauthorized
capabilities. It does not judge memorization or question leakage. The legacy
`memorization_detected` field remains readable in old records but is omitted from
the adaptive review request and is not a rejection condition.

Structural grants and generated-tool execution audits remain authoritative. A
rejected proposal consumes a round and retains the candidate/review for inspection.
No candidate is automatically applied or published.

## Choose which parts to optimize

`optimization_scope` intersects the existing host constraints with the requested
parts. For example, only edit allowed Skill content while preserving target
instructions, tools and budgets:

```python
result = await optimizer.optimize(
    package, context=context, goal="Improve task completion", rounds=5,
    optimization_scope=("skills",),
    constraints=OptimizationConstraints(
        editable_files=("skills/my-skill/SKILL.md",),
        # Optional if Skill enable/disable selection should also be editable:
        # allow_skill_changes=True, skill_candidates={"new-skill": "Host-bound Skill"},
    ),
)
```

Supported parts are `instructions` (complete candidate system prompt), `skills` (allowlisted
Skill files/resources and explicitly enabled Skill selection), `tools` (explicitly
enabled tool selection), `budgets` (allowlisted fields), and `resources` (other
allowlisted bundled files). Multiple parts can be combined. Omitting the scope
preserves the existing constraints-based API. An empty/invalid/duplicate scope is
rejected before model calls. Scope does not add file permissions, enable tool/Skill
selection grants or register capabilities: the corresponding constraints still
apply. Requests outside the effective scope are rejected as whole patches, never
silently applied in part. Effective constraints and scope are sent to the tuner
and reviewer and retained in the report/journal.

Skill resources are recognized under a `skills` path component or the directory
of a bundled/explicitly creatable `SKILL.md`, including supporting scripts and
references. Other editable resources require `resources`. Original instructions,
protected manifest fields and source plugins remain protected across all scopes.

optimize(..., on_event=callback) accepts a synchronous progress observer. It runs after each journal event is durably flushed when a journal path is supplied, and also works without a journal. Observers should perform only bounded work; an exception aborts the operation without activating a candidate. IsolatedOptimizationRunner(..., run_metadata=factory) lets the host inject frozen per-package Run metadata, including runtime variables; internal agent packages can receive separate metadata. Desktop uses these hooks for background progress and configuration/Skill version history.

## Historical fixed-suite domain benchmarks

`examples/v2/optimizer_domains.py` starts three independent specializations
from the same general-purpose package: subscription support triage, purchase-order
normalization, and production incident triage. Domain policies are supplied as
host-authorized optimization goals. The original package does not yet contain those
policies, so this measures acquisition and generalization of domain procedures,
not a general intelligence gain. The default `--mode instructions` rewrites the candidate system prompt. Procurement also
supports `--mode skills`, `--mode tools`, and `--mode joint`. Skill modes load a
bundled procedure through the native Skill provider with host-granted load scope.
Tool mode can replace an intentionally limited draft tool with a host-bound exact
decimal normalizer. It tests capability selection, not tool source-code synthesis.
Joint mode permits both system-prompt and Skill edits; the tuner may choose either.

These historical benchmark entry points explicitly use `validation_case_count=None` to preserve their original protocol; they are not the adaptive Desktop workflow.

Revision 1 has three training cases, two validation cases, and three final cases
fixed before execution; revised procurement adds coverage as described below.
Final cases are untouched only if they have not been disclosed in earlier studies. Support includes bounded multi-turn intake.
The default is four proposal rounds and two fresh trials per case, with real
model evaluators, tuners, reviewers, and dialogue drivers in separate Sessions.
No scripted patches, cached baseline answers, or code-based semantic grades are
used. A no-change round or rejected proposal is retained as a real outcome.

The command reads an explicitly supplied JSON model catalog (`--catalog`) in memory
and requires an `openai-responses` provider. Select a provider by `--provider` name
or mark it `is_default` in the catalog. See [catalog format](../../../examples/v2/README.md#model-catalog-for-live-experiments). It makes billable model calls. Credentials
are not copied to packages or reports. Output directories must not already exist,
and no production Agent configuration is registered or activated.

```sh
.venv/bin/python -m examples.v2.optimizer_domains \
  --catalog /path/to/models.json --domain support --rounds 4 --repeats 2 \
  --output artifacts/optimizer/domain-run/support
# Repeat with --domain procurement or --domain incident and a new output path.
```

Outputs include the sealed suites, authorized goal, complete original and iteration
packages, per-iteration observations and model judgments, semantic reviews,
call/session evidence, append-only journal, and comparison summary. Inspect failed
cases and rubric ambiguity before interpreting the aggregate score. Validation
participates in selection; only the sealed final suite is an untouched check.

For the clarified procurement contract, add `--revision 2`. Revision 1's negative
quantity final rubric asks for an invalid-field indication that its goal does not
explicitly specify. Revision 2 defines invalid-field reporting and null amounts
in the authorized policy, adds a training case for that behavior, and uses a fresh
final suite. Keep revision 1's failure record; do not relabel it as a pass or reuse
its disclosed final questions as untouched tests.


For procurement capability experiments, use `--revision 3 --mode skills` (or
`tools` / `joint`) with a new output directory. Revision 3 explicitly defines
calculation precision and rounding stages and supplies mixed-validity, multiline
and missing-supplier final cases. Reusing a revision's previously evaluated final
fixtures is a workflow regression check, not a fresh independent benchmark.
Add `--preflight-probe` to deliberately introduce a contradictory final rubric;
for an explicitly supplied fixed suite, the opinion is retained and the original
questions are still evaluated. The probe writes `preflight-diagnostics.json`;
it does not relabel a model refusal as an invalid dataset or alter the rubric.

In the 2026-10-12 real-model experiments, Skill-only tuning changed only SKILL.md,
and tool-only tuning removed draft_order and enabled normalize_order. Both reached
3/3 final cases; the joint-scope run also reached 3/3 but chose only a Skill edit.
Each used four proposal rounds and two trials per evaluated case. Only round 1
made a change; rounds 2–4 returned no changes. The Skill/tool final fixtures had
been used in an earlier study, while the clarified joint run used newly sealed
final cases. These small results validate the exercised workflow, not general
reliability or simultaneous instruction-and-Skill tuning. Large raw experiment
artifacts remain local and are not distributed with the repository.


## Adaptive Desktop framework experiments

`examples.v2.optimizer_adaptive_validation` exercises the current Desktop-owned
adaptive workflow through the real stdio MCP server. Start Desktop, then run:

```sh
.venv/bin/python -m examples.v2.optimizer_adaptive_validation --live \
  --output /absolute/path/experiment \
  --target-provider <configured-primary-id> \
  --alternate-provider <configured-alternate-id> \
  --internal-provider <configured-optimizer-id> \
  --rounds 4 --validation-count 6
```

The scenarios cover default-agent specialization with generated tools, a baseline
with a complete shipping policy, and expense normalization with a different target
model. Each uses a separate persisted Agent and independently generated questions.
An objective Python oracle checks outputs against the declared business rules,
including actual generated-tool execution where required. It also checks fixed
validation, host-only validation measurements, same-question parent/candidate
comparisons and unchanged live Agent configurations. No candidate is applied.

Saved request/run identities allow the command to inspect existing runs without
starting them again; changing scenario options requires a new output directory.
Reports preserve failed or non-converged experiments alongside successful ones.
These small rule-based tasks do not certify arbitrary-domain generalization.


### Human-only observation sink

`HumanTestObserver` accepts an `OptimizationTestSuite` and an isolated host evaluator. Pass its synchronous `observe` method as an event sink, await `finish()` after optimization, and call `cancel()` during host cleanup. It measures the baseline and every retained round; no return value or result is supplied to the optimizer. Test evidence must stay outside tuning requests, training generation, history, selection and termination. `IsolatedTestEvaluator` supplies fresh scoring/user sessions; `SharedCallLimitRunner` can share one call ceiling across both workloads without locking an entire dialogue. Test infrastructure errors remain missing measurements, and exact split overlap invalidates observation rather than steering optimization.

## Shared scheduling and round completion

All independent `(case, trial)` jobs in an evaluation share the configured
concurrency ceiling. A slow first repetition does not block later repetitions.
The Desktop host additionally shares one `SharedCallPool` across target calls,
internal agent calls, Python scorer model requests, and human-only test calls.
The observatory's active counter reads that pool, including human test work.
Queueing time is excluded from dialogue execution latency; setup and actual
execution remain included.

Human baseline tests are admitted as soon as `suite_fixed` freezes the development
suite. They run alongside baseline train/dev jobs, without waiting for their
summary. Desktop supplies `checkpoint_barrier=observer.wait_for_checkpoint`:
baseline and each retained round finish their declared human measurements before
the next round starts. This callback returns completion only, never scores or
hidden test evidence. Errors are recorded as measurement errors and close the
checkpoint; they are not converted to zero grades. Candidate selection continues
to depend solely on train/dev. Retained-round tests begin once selection fixes the
retained package. SDK hosts can opt into the same barrier; without it, observer
measurements retain the asynchronous API behavior.

## Frozen Python scorer dependencies

Scorer admission binds both entry source and local dependencies to a version.
Validation records imported local Python sources and data read by the contract
tests. Bundled `evaluation_datasets.<benchmark>` packages are pinned in full,
including resource membership, so adding a file also changes the binding. Custom
scorers must declare resources used only by other cases through
`SCORER_DEPENDENCIES = ["relative/file.json", "/absolute/resource/directory"]`.
Relative declarations resolve against the scorer entry file. Python and installed
package versions are also bound. Runtime state under `.runtime` and bytecode are
excluded. This checks integrity of trusted code; it is not a Python sandbox.

Bindings are verified before and after each subprocess execution. A modified or
new undeclared dependency raises an execution error rather than producing a grade.
Re-import after an intentional dependency update to obtain a new version. Public
validation metadata exposes the binding and file count, not private host paths.
Imported scorer and evaluation-plan IDs are scoped to the owning user and agent.
Plans retain their original dataset environment and reject conflicting overrides.
A second Desktop host does not mark a live host's run interrupted; recovery checks
both process ID and creation time before reclaiming abandoned work.

## Simulated user configuration

User simulation is independent of question design and scoring. Desktop uses the
built-in `DefaultUserSimulator`, or an independently uploaded Python implementation
selected via `user_simulator_id`. Both use the internal ModelProvider, shared call
pool and standard continue/stop contract. Python import tests use recorded model
responses; admission does not call live models or start RSI.

See [User simulator protocol, upload, ModelProvider and stopping](USER_SIMULATORS.md)
for the full contract and a complete uploadable example. Tau's adapter lives in
`evaluation_datasets/tau_bench/user_simulator.py`; benchmark logic stays with the dataset.

SDK hosts can pass `user_simulator=...` to the optimizer and independent test
evaluator. Existing `test_driver=OptimizationAgent(...)` hosts retain native driver
compatibility. Single-turn cases bypass simulation. Multi-turn cases should set
`dialogue_completion=user` when the user owns completion; stopping and scoring are
separate. Actual termination reasons are supplied to the scorer and saved in the
final conversation turn. Recovery retains frozen simulator bindings and isolates
state across cases, repeats and checkpoints.

## Mechanism-first evaluation and tuning

Evaluation now decides **what to verify next**. Execution diagnoses separate
agent decisions, environment, user simulation, scoring and infrastructure, and
record outcome/policy/quality priority, counterevidence, protected behavior and a
next verification. Training synthesis returns `next_action`:
`test_hypothesis`, `measure`, `measurement_issue`, or `no_change`. Without an
intervention supported by the synthesis, the default optimizer records a request
for further verification and retains the package instead of forcing an edit.
The score remains authoritative and unchanged. Validation/test trajectories and
questions remain unavailable to the tuner.

A changed candidate must include an `OptimizationExperiment` **before candidate
execution**: retained `parent_hash`, one primary `mechanism`, applicability,
change locations, existing-rule gap, expected observation, support/falsification/
inconclusive conditions, measured training IDs, protection cases, protected
behaviors and risks. Host checks bind the parent and reject any unmeasured or
hidden case reference. File editors return `experiment` with `rationale` and
`experience_notes`; files remain the sole production edit source. Invalid cards
use the existing bounded proposal repair path. No-change proposals need no card.
The host archives the declaration, actual changed coordinates, exact candidate,
measurements and selection separately. Acceptance is not proof of the mechanism.
`require_experiment=False` is an explicit compatibility option for legacy SDK
hosts; Desktop and new optimizers require the card by default.

New training cases are measured on the **retained package first**, with all
configured repeats and an independent `training_challenge` phase. Their recorded
failures, successes and diagnoses join existing training evidence **before** the
tuner is invoked. Existing trials are preserved. Only then may the candidate be
edited and measured on the expanded suite. Recovery distinguishes retained
discovery receipts from candidate receipts, so discovery cannot masquerade as a
candidate execution. Successes remain regression safeguards.

These changes implement the diagnosis/experiment and retained-first discovery
parts of the proposal. They do not turn the existing selection policy into a
statistical causal test or establish independent generalization. Fresh incumbent
comparison remains the separate `refresh_incumbent` option; final independent
acceptance requires its own frozen evaluation plan.

Imported case environments may opt into `environment.terminal_on_done: true`.
Desktop then wraps the target's deterministic continuation policy: only a complete,
successful result from the bound case MCP, carrying JSON `done=true`, can mark the
environment boundary. The host adds the receipt; assistant/user text and remote
MCP metadata cannot forge it. The next target model request is skipped, and the
normal scorer determines success independently. Existing bindings omit the new
flag and retain their prior wire representation and fingerprints. SDK hosts using
`McpCaseEnvironment` directly must install `CaseEnvironmentContinuationPolicy`
alongside the case tool provider to use this opt-in behavior.

A bounded local file evaluator may validate a completed assessment after the exact
`model.empty_semantic_response` terminal error. This requires the host's local-file
grant, full evidence read coverage, a readable assessment file, and the ordinary
schema and evidence validation. Native suspended state remains in the evidence;
other transport failures and invalid/missing assessments remain failures.
Incomplete or missing file assessments after that terminal error receive bounded
validation-repair feedback (including missing read ranges), rather than restarting
the entire analysis as a transport failure. They remain unusable until validation
passes; exhausted repairs still fail without manufacturing a diagnosis or grade.

Single-turn native loop-guard episodes can be graded from complete bound tool
receipts while retaining their genuine suspended Run state. See
[native episode boundaries](NATIVE_EPISODES.md) for evidence checks, selection,
independent tests, and atomic private-evidence recovery.
