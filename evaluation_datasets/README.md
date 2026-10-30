# RSI datasets and scorers

Each dataset directory contains its data, environment adapter, scorer, dependencies,
MCP configuration, and source records. Import and configure these parts separately.
RSI does not select an adapter from a dataset name.

## Available datasets

| Dataset | Default import | Train / dev / test | Environment | Setup |
| --- | --- | --- | --- | --- |
| tau2 retail | `tau_bench/rsi.dataset.json` | 62 / 12 / 40 | Official retail tools and reward | [README](tau_bench/README.md) |
| BFCL V4 base | `bfcl/rsi.dataset.json` | 160 / 20 / 20 | Official simulated tools and checkers | [README](bfcl/README.md) |
| BFCL V4 supported categories | `bfcl/rsi.all.dataset.json` | 480 / 60 / 60 | Base, miss_param, long_context | [README](bfcl/README.md) |
| ToolSandbox offline base | `toolsandbox/rsi.dataset.json` | 79 / 10 / 6 | Official tools and milestone/minefield scoring | [README](toolsandbox/README.md) |
| ALFWorld text | `alfworld/rsi.dataset.json` | 120 / 24 / 24 | TextWorld PDDL; C/C++ build tools | [README](alfworld/README.md) |
| ScienceWorld verified subset | `scienceworld/rsi.dataset.json` | 75 / 27 / 23 | Java 17 and py4j | [README](scienceworld/README.md) |
| Web Design: Beauty and Art | `web_design/rsi.dataset.json` | 20 / 10 / 10 | Native Sage file tools and Chromium; paired visual Eval Agent | [README](web_design/README.md) |
| AgentBench DB | `agentbench_db/rsi.dataset.json` | 234 / 32 / 34 | Docker and MySQL 8.0 | [README](agentbench_db/README.md) |

These are Sage RSI configurations, not full official leaderboard reproductions.
See each README for its source commit, split rules, supported tasks, and limits.

## Run a dataset

1. Install the dependencies and pass the dataset's environment preflight.
2. Add its `mcp.example.json` connection. Replace all placeholder paths.
3. Use the exact MCP name declared by the dataset and set
   `SAGE_RSI_CASE_PROTOCOL=sage.rsi.case/v1`.
4. Configure an Agent with the dataset policy and environment tools.
5. In the Agent's RSI page, import the dataset JSON, then import and select `scorer.py`.
6. Start small: 6 training cases, 0 new cases per round, 1 round, and 1 repeat.

Keep the training pool fixed for benchmarks that accept only official task IDs.
Generated cases without supported references cannot receive official scores.

## Python environments

Each dataset uses `evaluation_datasets/<dataset>/.venv` for both MCP and scoring.
Create it with the Python version in that dataset's README and install Sage plus
its `requirements.txt` there. Dependencies stay separate from Desktop's root `.venv`
and from other datasets. Java 17 (ScienceWorld), Docker/MySQL (AgentBench DB), and
C/C++ build tools (ALFWorld) must also be installed as documented.

Every dataset includes `scorer.runtime.json`. Keep it beside `scorer.py` when
importing in Desktop. The tau retail user simulator has its own matching
`user_simulator.runtime.json`. Both files use this format:

```json
{
  "format_version": "sage.rsi.scorer-runtime/v1",
  "python": ".venv/bin/python",
  "python_windows": ".venv/Scripts/python.exe"
}
```

Paths are relative to the scorer source directory. Configure MCP to use the same
prepared environment, using its absolute executable path. Restart Desktop after
updating Sage to enable these runtime files. Existing MCP connections must be
updated manually; new templates do not change saved settings.

Windows uses `.venv/Scripts/python.exe` instead of `.venv/bin/python` in setup
commands and MCP. This path mapping does not guarantee each upstream simulator
supports Windows; check its native dependencies.

Import records the interpreter, Python/package versions, and dependency hashes.
Reimport after changing code or dependencies. Existing experiments retain their
original bindings. A declared missing Python is an error; there is no host fallback.
Scorer and user-simulator import APIs accept an absolute `python_executable` path.
Custom Python modules without runtime metadata still use the Desktop backend Python.

## Run settings

| Setting | Default | Range |
| --- | --- | --- |
| Initial training cases | 6 | 1–100 |
| New training cases per round | 6 | 0–100; 0 fixes the pool |
| System prompt characters | 64,000 | Configurable |
| Characters per `SKILL.md` | 32,000 | Configurable |
| Skill count | 16 | Includes packaged and enabled Agent skills |
| Candidate repair attempts | 3 | 0–10 attempts after the first proposal |

Training cases are consumed in import order. Later rounds retain previous cases
and add the next batch. When the pool is exhausted, case generation may fill the
batch. Set new cases to 0 to avoid unsupported benchmark cases. New cases do not
retroactively evaluate historical versions.

Candidates must pass size/count checks before review and execution. A rejected
candidate is repaired in the same round. Exhausting repairs preserves the failure
record and the previous best version.

## Dataset format

The dataset importer accepts `sage.rsi.dataset/v1`:

```json
{
  "format_version": "sage.rsi.dataset/v1",
  "name": "Arithmetic",
  "cases": [
    {"id": "train-1", "input": "6*7?", "rubric": "Answer 42", "reference_answer": "42", "split": "training"},
    {"id": "dev-1", "input": "40+2?", "rubric": "Answer 42", "reference_answer": "42", "split": "validation"},
    {"id": "test-1", "input": "21*2?", "rubric": "Answer 42", "reference_answer": "42", "split": "test"}
  ]
}
```

IDs must be unique. Training and validation are required; test is optional.
Reference answers are available to scoring/evaluation, not the target Agent.
The tuner receives training diagnostics and anonymous dev scores. Keep test cases,
transcripts, scores, and diagnostics out of tuning and candidate selection.

## Python scorers

The default is Agent scoring. Import a Python scorer separately to use its grades.
Export a synchronous or asynchronous `score(request: dict) -> dict`. Requests
contain the protocol version, goal, case, observation, and conversation.

Return a grade directly, or wrap it as follows:

```python
{"grade": {"score": 0.8, "passed": True, "rationale": "Matched reference"}, "details": {}}
```

`score` must be finite and between 0 and 1, `passed` must be a boolean, and
`rationale` must be nonempty. Evaluation diagnoses execution but does not replace
the selected scorer's numeric result. Exceptions, timeouts, invalid results, and
`not_applicable_reason` are measurement failures, not zero scores or fallback grades.

Include `SCORER_TEST_CASES` with 1–10 entries. Each numeric test needs a complete
`request`, `expected_score`, and `expected_passed`. A non-applicable test uses
`expected_applicable: False`, omits numeric expectations, and must return a reason.
At least one numeric test is required. See [exact_answer.py](examples/exact_answer.py).

Import checks syntax, the function signature, return values, and all self-tests in
a separate process, with a 10-second timeout. Runtime scoring defaults to 120 seconds.
Passing tests validates the supplied examples, not arbitrary scoring accuracy.
Imported code is frozen under `rsi-scorers/` by user/Agent. A subprocess is not an
OS security sandbox; import only trusted local code.

An optional `SCORER_CONTRACT` string, up to 16,000 characters, describes input
requirements, success criteria, partial credit, and aggregation. Dataset review
uses it to understand the scorer; it cannot override invalid data or permissions.

### Model access

A scorer can use the experiment's ModelProvider without receiving provider keys:

```python
import json
from sagents.v2.optimization.scorer_runtime import get_model_provider
from sagents.v2.model.contracts import ModelRequest, ModelMessage, ModelEventKind
from sagents.v2.contracts.items import TextBlock

async def score(request):
    model = get_model_provider()
    prompt = build_your_scoring_prompt(request)  # Define this function locally.
    async for event in model.stream(ModelRequest(
        request_id="score-request", run_id="scorer", model_binding=model.model_binding,
        messages=(ModelMessage(role="user", content=(TextBlock(text=prompt),)),),
    )):
        if event.kind == ModelEventKind.COMPLETED:
            return {"grade": json.loads(event.response.text)}  # Validate your schema.
    raise RuntimeError("Model returned no completed response")
```

The proxy uses standard Sage request/response types and the shared concurrency
budget. It aggregates a response into a COMPLETED event; it does not promise token
streaming. The scorer owns prompts, parsing, scoring, and retries. Provider keys
stay in the backend. Per-call credentials expire after scoring.

`scorer-model-calls.jsonl` records call counts, timing, and token use, without prompts
or responses. These records do not enter tuning evidence. Temporary model failures
remain retryable failures. `get_model_api()` is also available for existing scorers
that need a local OpenAI-compatible endpoint to the same ModelProvider.

Import self-tests have no live model access. Each test can provide 1–16 standard
`model_responses` dictionaries with `response_id`, `text`, and `finish_reason`.
Extra/missing calls or wrong grades fail validation. Live runs do not use these fixtures.

## Comparison plugins

New plugins should use [capability-declared evaluation](../sagents/v2/optimization/EVALUATION_PLUGINS.md).
Declare preparation, evaluation, analysis and optional training-summary capabilities.
The configured Eval Agent fills missing stages, with the optimization goal supplied
throughout. A plugin can also replace all evaluation stages. Web Design only prepares
screenshots; its Eval Agent performs the visual comparison and analysis.

For relative preferences, import a dataset-owned Python plugin exporting
`prepare(request)` and `compare(request)`, with `COMPARISON_CONTRACT` and
`COMPARISON_TEST_CASES`. Selecting it enables pairwise evaluation. Keep its runtime
metadata beside the source. Existing absolute `score(request)` files are unchanged.
Sage pairs repeated executions against the retained incumbent for training/dev.
Independent tests compare with the original baseline. Both aggregate win/tie/loss results. Dataset plugins own artifact capture, rendering and judges.
See [Paired preference evaluation](../sagents/v2/optimization/PAIRWISE_EVALUATION.md)
for versioned wire schemas, artifact manifests, self-tests and failure semantics.

## User simulators

User simulators are selected separately from datasets and scorers. Single-turn
cases skip them. Multi-turn cases use the user context and visible conversation.
Sage provides a default simulator and supports imported Python implementations.

For tau retail, import [user_simulator.py](tau_bench/user_simulator.py) separately
and keep [scorer.py](tau_bench/scorer.py) selected. See
[User simulators](../sagents/v2/optimization/USER_SIMULATORS.md) for the protocol.
