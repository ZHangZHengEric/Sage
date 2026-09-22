---
layout: default
title: Getting Started
nav_order: 1
lang: en
ref: v2-applications-GETTING_STARTED
parent: Applications
---

{% include lang_switcher.html %}

# Getting Started

## Install

Use Python 3.12+. In a macOS/Linux shell:

```bash
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

On Windows use `py -3.12 -m venv .venv`, then `.venv\Scripts\Activate.ps1` in PowerShell.

## Run from one Python file

**No `sage.yaml` file is required.** `SageManifestLoader.loads()` parses a YAML string into a manifest, which `SAgentBuilder.build()` accepts directly.

Save as `quickstart.py` and replace `your-model` with a model available to your account:

```python
"""Set MODEL_API_KEY and replace your-model below; no sage.yaml file is needed."""

import asyncio
from uuid import uuid4

from sagents.v2 import ActorRef, RequestContext, SAgentBuilder, StartRun
from sagents.v2.contracts.commands import InputItem
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import PrincipalType
from sagents.v2.package.manifest import SageManifestLoader

AGENT_YAML = """
schema_version: sage/v2
kind: application
metadata: {id: example.assistant, version: 1.0.0, name: Assistant}
credentials:
  api-key: {source: env, key: MODEL_API_KEY}
models:
  primary:
    provider: openai-responses
    base_url: https://api.openai.com/v1
    credential: api-key
    model: your-model
agents:
  main:
    name: Assistant
    instructions: {inline: "Be helpful and concise."}
    models: {primary: primary}
entrypoint: {agent: main}
"""


async def main():
    manifest = SageManifestLoader().loads(AGENT_YAML)
    app = await SAgentBuilder().with_defaults(session_root="runtime").build(manifest)
    try:
        context = RequestContext(actor=ActorRef(
            principal_id="user-1", principal_type=PrincipalType.USER,
        ))
        stream = await app.entrypoint().run_stream(StartRun(
            agent_id="main",
            input=(InputItem(role="user", content=(TextBlock(text="Say hello!"),)),),
            resolved_spec_hash=app.composition_hash,
            idempotency_key=str(uuid4()),
        ), context)
        async for event in stream.events:
            print(event.model_dump_json())
        print((await stream.wait()).state)
    finally:
        await app.close()


if __name__ == "__main__":
    asyncio.run(main())
```

```bash
export MODEL_API_KEY="your-api-key"
python quickstart.py
```

This prints runtime events and the final Run state. It makes a real model request and writes Session data under `runtime/`. The example enables no file or shell tools. In PowerShell, set the key with `$env:MODEL_API_KEY="your-api-key"`.

The checked-in [executable example](https://github.com/ZHangZHengEric/Sage/blob/main/examples/sagents_v2_quickstart.py) can also be run from the repository root as `python -m examples.sagents_v2_quickstart`.

## Choose a configuration input

| Input | Usage |
| --- | --- |
| YAML string | `build(SageManifestLoader().loads(yaml_text))` |
| Python dictionary | `build(SageManifest.model_validate(config))` |
| Package file | `build("path/to/sage.yaml")` |
| Resolved package | `build(resolved_manifest)` |

Import both manifest types from `sagents.v2.package.manifest`. A raw string passed directly to `build()` is a **path**, not YAML content. String manifests should use inline instructions. File loading resolves instruction files relative to the package directory and checks that they remain inside it.

Next: [configuration](../CONFIGURATION.md), [tools](../MCP_SERVERS.md), and [runtime API](../api/API_REFERENCE.md).
