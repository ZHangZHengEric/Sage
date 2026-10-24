# Independent simulated users

Question design, user simulation and scoring are separate responsibilities:

| Component | Prepares / sees | Produces |
| --- | --- | --- |
| Designer or dataset importer | Goal, authorized capabilities and scenario | `input`, `user_context`, `mode`, `max_turns`, `dialogue_completion`, rubric/reference, environment |
| User simulator | User background and ordered **visible** user/assistant messages | One next user message or a stop decision |
| Scorer | Rubric/reference and complete execution evidence | Score, pass/fail and rationale |

The target initially receives only `input`; `user_context` is for the simulated
user. Tool results, grading references and rubrics are not part of the simulator
request. Uploaded Python is trusted host code, like an uploaded scorer; the input
allowlist is a data contract, not an OS security sandbox.

## Built-in and dataset-specific implementations

Desktop uses `DefaultUserSimulator` from `default_user_simulator.py` when no
Python module is selected. It calls the selected internal model through Sage's
ModelProvider, with the built-in scenario user policy. Optional
`user_simulator_instructions` extend this policy. No Python upload is needed for
the default. A Python selection and custom default instructions are mutually exclusive.

For tau retail, upload `evaluation_datasets/tau_bench/user_simulator.py` separately
from `evaluation_datasets/tau_bench/scorer.py`. Its README explains the pinned
official prompt/role-conversion behavior and the remaining harness differences.
The generic framework does not infer a simulator from dataset names.

## Upload and select

1. Open the Agent's RSI settings, select **Import simulated user**, and choose a `.py` file.
2. Import runs the file's offline contract tests. It does not start RSI or call the chosen live model.
3. Select the admitted module in the **Simulated user** picker. Select **RSI built-in user** to reset.
4. The selected ID is frozen with the experiment and shared across train/dev/test, repeats and checkpoints.

The authenticated API is `POST /api/v2/agents/{agent_id}/rsi/user-simulators`:

```json
{"name": "my_user.py", "source": "...Python source..."}
```

It returns `id`, descriptor, source hash, validation and creation time. Pass
`user_simulator_id` to the ordinary RSI start API or CLI MCP `rsi_start`.
`GET /api/v2/agents/{agent_id}/rsi` lists `user_simulators`.
Imports are scoped to the owning user and Agent. Source plus captured dependencies
form an immutable binding. Changes require re-import; recovery rejects a different
binding. Same-name versions remain independently selectable. Public metadata does
not include source, private dependency paths or credentials.

## Python file contract

Export **either** `reply(request)` (sync or async, plain dict input/output), **or**
`USER_SIMULATOR = YourUserSimulator()` whose class implements
`UserSimulator.reply(UserSimulationRequest) -> UserSimulationReply`.
Both use `sage.rsi.user-simulator/v1`.

Request fields:

```json
{
  "protocol": "sage.rsi.user-simulator/v1",
  "case": {"id": "case-1", "split": "training", "input": "Please help with my return.", "user_context": "Order #123; refund to the original payment method."},
  "conversation": [{"role": "user", "content": "Please help with my return."}, {"role": "assistant", "content": "Which refund method would you like?"}],
  "turns_remaining": 4,
  "trial": 1,
  "state": {}
}
```

Continue:

```json
{"can_continue": true, "message": "Refund to the original payment method.", "rationale": "The user knows this preference.", "state": {"preference_supplied": true}}
```

Stop:

```json
{"can_continue": false, "message": "", "stop_reason": "completed", "rationale": "No further user requests."}
```

`can_continue` must be a boolean, `message` and nonblank `rationale` are required.
Continuation requires nonblank text and no stop reason. Stopping requires an empty
message and `stop_reason` equal to `completed`, `transferred` or `out_of_scope`.
Unknown fields are rejected. Optional `state` is JSON up to 64 KiB, defaults to `{}`,
and is passed back only within this case/trial/checkpoint. A fresh trial starts
with `{}`. Workers are new processes per invocation: persist dialogue state in
`state`, not Python globals or files.

Include `USER_SIMULATOR_TEST_CASES` with **2–10** entries, collectively exercising
both continuation and stopping. Each entry contains `request` and `expected_reply`.
For example, this complete file is uploadable without a model:

```python
CONTINUE = {"can_continue": True, "message": "Original payment method, please.",
            "rationale": "Known preference", "state": {"answered": True}}
STOP = {"can_continue": False, "message": "", "stop_reason": "completed",
        "rationale": "The scenario is finished"}

def reply(request):
    return STOP if request["state"].get("answered") else CONTINUE

REQUEST = {"case": {"id": "contract", "split": "training", "input": "Help with a return.",
                   "user_context": "Refund to original payment method."},
           "conversation": [], "turns_remaining": 3}
USER_SIMULATOR_TEST_CASES = [
    {"request": REQUEST, "expected_reply": CONTINUE},
    {"request": {**REQUEST, "state": {"answered": True}}, "expected_reply": STOP},
]
USER_SIMULATOR_CONTRACT = "Only disclose supplied preferences; then end the scenario."
```

Lazy local resources must be declared in `USER_SIMULATOR_DEPENDENCIES`, with the
same relative/absolute path rules as scorer dependencies. Imported repository
benchmark packages are captured in full. Import tests must cover the code paths
needed at runtime; dependencies first discovered during execution are rejected.

## ModelProvider access

Inside uploaded code:

```python
from sagents.v2.optimization.user_simulator_runtime import get_model_provider
from sagents.v2.optimization.default_user_simulator import generate_user_text
from sagents.v2.model.contracts import ModelMessage
from sagents.v2.contracts.items import TextBlock

async def reply(request):
    model = get_model_provider()
    text = await generate_user_text(model, (
        ModelMessage(role="system", content=(TextBlock(text="Your simulator policy"),)),
        ModelMessage(role="user", content=(TextBlock(text="Your scenario/history prompt"),)),
    ))
    # Your code interprets text and returns a valid decision.
    return {"can_continue": True, "message": text, "rationale": "Scenario continuation"}
```

You may use the full native `ModelRequest` / `model.stream()` interface instead.
Prompts, sampling controls, parsing and stop logic belong to the implementation.
`generate_user_text` merely collects one completed text response and rejects tool
calls, empty text and truncated responses. Tau uses it without a JSON instruction.

For model-backed import tests, supply `model_responses` in each test entry: a list
of recorded `ModelResponse` dictionaries (`response_id`, `text`, `finish_reason`,
optional usage). Every recording must be consumed. A provider is unavailable at
import when no recordings are supplied. The tau file is a complete example.

At runtime the proxy uses the experiment's selected internal provider, shared
concurrency slots and global model budget. It receives a short-lived per-call
capability, never the remote provider's credentials. Capabilities expire on return,
error and cancellation. Calls are limited to 16 per reply. Usage is recorded as
`dialogue`; model audit logs contain metadata/usage, not prompts or responses.

## When to score

- `mode=single_turn`: run one user request to completion, then score; no simulated
  user invocation. Internal agent/tool steps may still be numerous.
- `mode=dialogue, dialogue_completion=user`: continue from each target response
  until the simulator stops or `max_turns` is reached, then score the full history.
- Legacy `dialogue_completion=score` retains intermediate scoring and early pass
  behavior. Use `user` when the simulator owns dialogue completion.

A stop decision does **not** grant a passing grade. The scorer receives
`user_finished`, `user_transferred`, `user_out_of_scope`, or `turn_limit` as the
actual termination reason. Protocol errors, code failures, missing facts in code
and infrastructure failures do not become a stop or a fabricated score.

SDK hosts can pass `user_simulator=...` to `AgentPackageOptimizer` and to
`IsolatedTestEvaluator`; use the same instance/configuration for both sides.
`DefaultUserSimulator(provider_factory)` accepts an async context manager yielding
an already budgeted ModelProvider for that request. Existing SDK hosts using
`test_driver=OptimizationAgent(...)` retain their native Agent driver compatibility.
