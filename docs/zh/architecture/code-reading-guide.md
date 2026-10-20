---
layout: default
title: 代码阅读指南
parent: 架构
nav_order: 12
lang: zh
ref: v2-detail-code-reading-guide
---

{% include lang_switcher.html %}

# Sage code map

The public path is `SAgentBuilder.register` → `build(runtime=..., models=...)` →
`load_agent` → `entrypoint().run_stream(..., agent=agent)` → `close`.

- [SDK composition map](../../../sagents/v2/composition/README.md): bootstrap, immutable revisions, dependency scopes and Run binding.
- [Host guide](sagents-host-development.md): capability registration, configuration and recovery.
- Desktop: `app/v2/desktop/backend/composition.py`, `sdk_plugins.py`, `run_service.py`.
- Server: `app/v2/server/bootstrap.py`, `runtime/sdk_plugins.py`, `runtime/loop.py`.
- Managed packages: `app/v2/server/packages/builder.py` returns `ApplicationConfiguration`.
- Native isolation: `sagents/v2/runtime/execution/plugins/local_binding/__init__.py` and `sandbox/plugins/local/support/interpreter.py`.
- [Runnable standard host](../../../examples/v2/standard_host/README.md): actual media, MCP, Skill and nested Team validation.

Host capability plugins implement their protocols; the SDK owns Agent loops,
official tools, child execution, sandbox leases and recovery. Product identity
and authorization come from the real Run context and frozen inputs.
