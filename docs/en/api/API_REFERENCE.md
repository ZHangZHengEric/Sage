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
app = await SAgentBuilder().with_defaults(session_root="runtime").build(manifest)
```

`build()` also accepts a `ResolvedSageManifest` or a path to a file named `sage.yaml`. Raw strings are paths. `loads()` does not resolve relative instruction files; use inline instructions or the file loader.

## Execution and ownership

1. Obtain `app.entrypoint()`.
2. Create a `RequestContext` with the authenticated `ActorRef` supplied by your host.
3. Submit `StartRun` through `run_stream(command, context)`.
4. Consume `stream.events`; `await stream.wait()` returns a `RunSnapshot` with `.state`.
5. Close `app` in a `finally` block.

Use a new idempotency key for each logical request, and reuse it only when retrying that same request. Production adapters must not trust a client-supplied user ID. Access Sessions through `app.service("session.access")` with context; the raw SessionStore is a trusted internal port.

Cancellation, steering, resumption, and interaction replies are explicit commands; disconnecting an event stream only detaches that observer. A snapshot may be suspended rather than terminal.

[Complete runnable example](../applications/GETTING_STARTED.md) · [Facade](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/sagent.py) · [Commands](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/contracts/commands.py) · [Builder](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/builder.py)
