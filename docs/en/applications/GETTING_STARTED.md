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
agents:
  main:
    name: Assistant
    instructions: {inline: "Be helpful and concise."}
    models: {primary: primary}
entrypoint: {agent: main}
"""

MODELS_YAML = """
credentials:
  api-key: {source: env, key: MODEL_API_KEY}
models:
  primary:
    provider: openai-responses
    base_url: https://api.openai.com/v1
    credential: api-key
    model: your-model
"""


async def main(*, runtime=None, registrations=()):
    from sagents.v2.composition.defaults import default_runtime
    manifest = SageManifestLoader().loads(AGENT_YAML)
    builder = SAgentBuilder()
    for registration in registrations:
        builder.register(registration)
    app = await builder.build(runtime=runtime or default_runtime("runtime"), models_config_text=MODELS_YAML)
    try:
        agent = await app.load_agent(manifest)
        context = RequestContext(actor=ActorRef(
            principal_id="user-1", principal_type=PrincipalType.USER,
        ))
        stream = await app.entrypoint().run_stream(StartRun(
            agent_id=agent.id,
            input=(InputItem(role="user", content=(TextBlock(text="Say hello!"),)),),
            resolved_spec_hash=agent.composition_hash,
            idempotency_key=str(uuid4()),
        ), context, agent=agent)
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

The checked-in [executable example](https://github.com/ZHangZHengEric/Sage/blob/main/examples/v2/quickstart.py) can also be run from the repository root as `python -m examples.v2.quickstart`.

## Choose a configuration input

| Input | Usage |
| --- | --- |
| YAML string | `await app.load_agent(SageManifestLoader().loads(yaml_text))` |
| Python dictionary | `await app.load_agent(SageManifest.model_validate(config))` |
| Package file | `await app.load_agent("path/to/sage.yaml")` |
| Resolved package | `await app.load_agent(resolved_manifest)` |

Import both manifest types from `sagents.v2.package.manifest`. A raw string passed directly to `app.load_agent()` is a **path**, not YAML content. String manifests should use inline instructions. File loading resolves instruction files relative to the package directory and checks that they remain inside it.

Next: [configuration](../CONFIGURATION.md), [tools](../MCP_SERVERS.md), and [runtime API](../api/API_REFERENCE.md).
