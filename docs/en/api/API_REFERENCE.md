---
layout: default
title: Python Runtime API
nav_order: 1
lang: en
ref: v2-api-API_REFERENCE
parent: API
---

{% include lang_switcher.html %}

# Python Runtime API

## Configuration inputs

```python
from sagents.v2 import SAgentBuilder
from sagents.v2.package.manifest import SageManifest, SageManifestLoader

# YAML text; no file is created.
manifest = SageManifestLoader().loads(yaml_text)
# Or validate a Python dictionary:
# manifest = SageManifest.model_validate(config_dict)
app = await SAgentBuilder().build(runtime=manifest.runtime, models=model_config)
agent = await app.load_agent(manifest)
```

`load_agent()` accepts a manifest, a `ResolvedSageManifest`, or a path to `sage.yaml`; `build()` accepts runtime and model configuration. Raw strings are paths. `loads()` does not resolve relative instruction files; use inline instructions or the file loader.

## Execution and ownership

1. Obtain `app.entrypoint()`.
2. Create a `RequestContext` with the authenticated `ActorRef` supplied by your host.
3. Submit `StartRun` through `run_stream(command, context, agent=agent)`.
4. Consume `stream.events`; `await stream.wait()` returns a `RunSnapshot` with `.state`.
5. Close `app` in a `finally` block.

Use a new idempotency key for each logical request, and reuse it only when retrying that same request. Production adapters must not trust a client-supplied user ID. Access Sessions through `app.service("session.access")` with context; the raw SessionStore is a trusted internal port.

Cancellation, steering, resumption, and interaction replies are explicit commands; disconnecting an event stream only detaches that observer. A snapshot may be suspended rather than terminal.

`SteerRun` appends input to the active Turn of an existing Run without creating a Run or resetting progress or budgets. Supply `run_id`, `expected_turn_id`, `input`, and a stable `idempotency_key`. The legacy `expected_revision` field is accepted but excluded from admission and idempotency checks. Enqueue advances the Session revision and event sequences, leaving the execution Run revision unchanged. At the next safe model boundary, the driver atomically consumes input and persists its messages, retaining execution revision checks. Localized English/Chinese runtime guidance tells the model to apply updated requirements while preserving task progress; this guidance is not stored in user message history.

`steer.accepted` confirms durable enqueue; `steer.applied` confirms incorporation into model context at a safe boundary. Input left pending when its Turn or Run ends is atomically marked `rejected` with a reason and a `steer.rejected` event; it is never forwarded to another Turn. Pausing retains pending input. HTTP retries use the same `messageId` and return the current durable status and rejection reason.

[Complete runnable example](../applications/GETTING_STARTED.md) · [Facade](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/sagent.py) · [Commands](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/contracts/commands.py) · [Builder](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/builder.py)
