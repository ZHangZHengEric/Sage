# AgentPackageOptimizer

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
and bounded training results and adds 1..6 new challenges. There is no configurable
training-total quota. Accumulated training questions remain in the suite. Imported
`OptimizationSuite` supplies initial training and fixed validation; the configured
validation count must match its validation split. Case IDs must be unique.

The validation designer sees the original package and previously generated
validation questions only. The training designer sees current capabilities and
training evidence, never validation questions or feedback. Separate fresh Sessions
keep design requests independent. Host checks and an independent suite reviewer
check policy/rubric consistency, authorization and executable fixtures. They do
not judge cross-split leakage or question memorization.

New training questions first run against the incumbent package. The incumbent and
proposal are then compared on exactly the same cumulative questions; adding hard
questions cannot itself be misreported as a proposal regression. Overall quality
is `0.5 * training_mean + 0.5 * validation_mean`, so growing training sets do not
overwhelm the fixed validation signal. A candidate is retained when that overall
score improves by at least `min_improvement`. Individual regressions are allowed,
recorded per round, and carried forward for repair from the stronger package.
Execution completion, enabled generated-tool integrity audits, and independent
goal/permission reviews still gate acceptance.

Tuning receives complete bounded training evidence, previous attempts, validation
mean/pass count, and per-question scores under stable anonymous indexes. No
validation question text, original IDs, rubrics, answers or grading rationale is
included. Validation score history uses the same indexes within a run. The host
report and Desktop question library retain the full evidence for user inspection.
The tuner additionally receives bounded unresolved training regressions with
their prior scores and current training evidence. Validation regressions remain
anonymous scores only. Round records include overall scores before/after and all
observed per-case regressions for host inspection.
These repeated validation scores guide selection and tuning; they are not an
untouched final exam or an independent quality certification.

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

Original target instructions are preserved verbatim. Optional optimization
guidance is appended as a separate section and replaced on later updates. Other
Agents' instructions are unchanged. Structural preservation does not prove that
new guidance/Skill content semantically respects the original requirements;
include responsibility and permission behavior in the fixed test rubrics.

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
provider cost remains `None`. These metrics are reported; the default selection
gate uses quality; latency improvement is separately opt-in, and cost is not a gate. Reports and intermediate candidate files
may contain sensitive task evidence; storage/redaction is the caller's concern.

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
fresh evidence replaces the measurement of that package; training details and
anonymous validation scores reach later tuning. Reused results do not establish
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
injection or rubric ambiguity. Guidance defaults to a 16,000 character limit;
each edited file defaults to 262,144 UTF-8 bytes. Configure
`max_guidance_chars`/`max_file_bytes` in `OptimizationConstraints`. These limits
bound growth; they do not prove that a change is free of memorized cases.

With `journal_path`, the controller creates a NEW append-only JSONL file with
mode 0600. An existing path (including a symlink) is rejected before model calls.
Its parent directory must exist. Events are flushed and fsynced after each write:
original/internal packages, suite, target/internal calls, candidate packages,
completed test/round records and the final result. Raw designer/evaluator output
is retained even when JSON validation fails. On exception/timeout/cancellation,
completed events remain available and an operation status is recorded. A process
crash may leave a partial last line; only complete JSONL lines are reviewable.
A call-start event without completion means its outcome is unknown. No automatic
replay or resume occurs. Journals do not contain resolved host credentials, but
package/input/model text may be sensitive; choose storage accordingly.

Dialogue initialization is covered by the per-call deadline, in addition to
individual target sends and evaluator/simulator calls. Deadlines are cooperative:
host providers and cleanup hooks must honor cancellation. This API is suitable
for controlled single-host experiments with host budgets and test bindings.
Durable job resumption, multi-process coordination and structured interaction
resumption are not implemented here. Final verification and semantic review are
implemented as described below.


## Independent business and permission review

Every changed, structurally valid proposal is independently reviewed before target
execution. The reviewer sees original/current/candidate packages, the authorized
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

Supported parts are `instructions` (the guidance overlay), `skills` (allowlisted
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
not a general intelligence gain. The default `--mode instructions` edits instruction guidance. Procurement also
supports `--mode skills`, `--mode tools`, and `--mode joint`. Skill modes load a
bundled procedure through the native Skill provider with host-granted load scope.
Tool mode can replace an intentionally limited draft tool with a host-bound exact
decimal normalizer. It tests capability selection, not tool source-code synthesis.
Joint mode permits both guidance and Skill edits; the tuner may choose either.

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
the expected outcome is a retained `preflight-rejected.json` and zero target calls.

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
validation, anonymous per-item score disclosure, same-question parent/candidate
comparisons and unchanged live Agent configurations. No candidate is applied.

Saved request/run identities allow the command to inspect existing runs without
starting them again; changing scenario options requires a new output directory.
Reports preserve failed or non-converged experiments alongside successful ones.
These small rule-based tasks do not certify arbitrary-domain generalization.


### Human-only observation sink

`HumanTestObserver` accepts an `OptimizationTestSuite` and an isolated host evaluator. Pass its synchronous `observe` method as an event sink, await `finish()` after optimization, and call `cancel()` during host cleanup. It measures the baseline and every retained round; no return value or result is supplied to the optimizer. Test evidence must stay outside tuning requests, training generation, history, selection and termination. `IsolatedTestEvaluator` supplies fresh scoring/user sessions; `SharedCallLimitRunner` can share one call ceiling across both workloads without locking an entire dialogue. Test infrastructure errors remain missing measurements, and exact split overlap invalidates observation rather than steering optimization.
