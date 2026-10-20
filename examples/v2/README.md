# Sage v2 Examples

These examples use the current `sagents.v2` SDK. Run commands from the repository
root with Python 3.12+ after `python -m pip install -e .`.
Version ownership comes from `examples/v2/`; filenames describe the capability.

## Start here

```bash
python -m examples.v2.host --offline
python -m examples.v2.host --offline --inspect
python -m examples.v2.tool_catalog --agent-mode all
python -m examples.v2.multi_project
python -m examples.v2.package_optimizer
```

The offline examples use scripted model responses to demonstrate orchestration,
not model quality. `host` writes state to `.runtime/host-starter` by default;
use `--runtime-root` to choose another directory. The agent-management,
source-plugin, multi-project and package-optimizer examples use temporary state.

## Examples

| Entry | Demonstrates | Requirements |
| --- | --- | --- |
| [quickstart.py](quickstart.py) | Minimal SDK application from inline YAML | `MODEL_API_KEY` and replacing `your-model` in the example; real model calls |
| [host/](host/) | Manifest, model configuration, plugin registration, application bootstrap, events and inspection | Offline with `--offline`; otherwise configure `host/models.yaml` and `MODEL_API_KEY` |
| [standard_host/](standard_host/README.md) | Standard file/Shell tools, FFmpeg, Skill, stdio MCP, nested Team and reopening state | Scripted model; real subprocesses, FFmpeg, Pillow, native macOS Seatbelt or Linux bubblewrap |
| [tool_catalog.py](tool_catalog.py) | Built-in tool metadata by agent mode and language | Offline; no App or Run is started |
| [parallel_search.py](PARALLEL_SEARCH.md) | MCP discovery, search/fetch and cleanup | Network access to the external Parallel MCP service; no LLM; service availability and limits are external prerequisites |
| [agent_management.py](agent_management.py) | Agent creates and runs another Agent package; package listing and run status | Offline |
| [source_plugin.py](source_plugin.py) | Host-authorized Python source extension | Offline; executes the example's fixed trusted Python bundle |
| [multi_project.py](MULTI_PROJECT.md) | Concurrent Sessions and per-Run project routing through MCP | Offline, in-process MCP transport |
| [package_optimizer.py](package_optimizer.py) | Multi-round package optimization and evaluation | Offline |
| [optimizer_live.py](optimizer_live.py) | Real-model optimization of the built-in assistant | Advanced experiment; explicit JSON model catalog (`--catalog`), usable model credentials and a new `--output` directory; billable model calls |
| [optimizer_domains.py](optimizer_domains.py) | Domain specialization in instructions, Skills and tools | Advanced experiment; explicit JSON model catalog (`--catalog`, Responses protocol), `--domain` and a new `--output` directory; billable model calls |

## Model catalog for live experiments

Both live experiments require an explicit `--catalog /path/to/models.json`.
The JSON uses the Desktop catalog's `model_providers` format and can be supplied
independently of any application. Select a record with `--provider NAME`, or mark
one record `is_default: true`:

```json
{
  "model_providers": [
    {
      "name": "primary",
      "protocol": "openai-responses",
      "model": "your-model",
      "base_url": "https://api.openai.com/v1",
      "api_key": "YOUR_API_KEY",
      "is_default": true,
      "max_model_len": 64000
    }
  ]
}
```

Keep the credential file outside version control. Credentials are read in memory
and are not copied into generated packages or reports. `optimizer_domains`
requires the Responses protocol; `optimizer_live` supports Responses and OpenAI
Chat Completions. The configured model must support the experiment's tools and
structured output. Neither script discovers settings in application directories.

```sh
python -m examples.v2.optimizer_live --catalog /path/to/models.json \
  --provider primary --output /tmp/sage-optimizer-live
python -m examples.v2.optimizer_domains --catalog /path/to/models.json \
  --provider primary --domain support --output /tmp/sage-optimizer-support
```

Run the remaining offline examples with:

```bash
python -m examples.v2.agent_management
python -m examples.v2.source_plugin
```

The live optimizer scripts require the explicit model catalog above. Inspect
`python -m examples.v2.optimizer_live --help` or
`python -m examples.v2.optimizer_domains --help` before configuring a run.
They are experiment harnesses rather than the starting point for embedding Sage.

[Child-run model bindings](CHILD_RUN_BINDINGS.md) is a configuration guide backed
by regression tests, rather than a separate executable example.

## Verification

```bash
python -m pytest -q tests/sagents/v2/test_quickstart_example.py \
  tests/sagents/v2/test_host_starter_example.py \
  tests/sagents/v2/test_parallel_search_example.py \
  tests/sagents/v2/test_multi_project_example.py
```

These tests use offline model/MCP substitutes. Native media acceptance is opt-in;
see [standard host](standard_host/README.md). Live optimizers and external MCP
availability require separate runs in a configured environment.
