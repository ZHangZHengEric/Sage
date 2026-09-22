---
layout: default
title: Plugin Architecture
nav_order: 1
lang: en
ref: v2-architecture-PLUGINS
parent: Architecture
---

{% include lang_switcher.html %}

# Plugin Architecture

## What can be replaced

Models, Session storage, memory, tool catalogs and executors, Skill loading, context reduction, scheduling, jobs, sandbox providers, protocol adapters, and observability sinks have explicit extension boundaries.

An `ExtensionRegistration` supplies identity, capability/API version, configuration schema, dependencies, scope, and the factory for a working implementation. The extension kernel resolves dependencies, validates configuration, rolls back failed startup, and closes scopes in reverse dependency order.

## How hosts compose providers

1. Use `SAgentBuilder().with_defaults(...)` for standard providers.
2. Select plugin bindings in the manifest's `runtime.capabilities`.
3. Inject host-owned providers through Builder methods such as `with_model_provider`, `with_session_store`, or `with_tool_runtime`.
4. Build once, inspect `application.resolved_plan`, and close the application when the host shuts down.

Installed extensions can use the `sage.extensions` Python entry-point group. Source plugins require explicit host trust and authorization; they are executable host code, not an isolation mechanism.

## What plugins cannot redefine

Legal lifecycle transitions, canonical event ordering, and Session history authority are framework contracts. A plugin must advertise only guarantees it enforces. A database-backed store does not automatically provide cross-process subscriptions, distributed claims, or durable jobs.

[Manifest configuration](../CONFIGURATION.md) · [Extension contracts](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/ARCHITECTURE.md) · [Integration examples](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/使用手册.md)
