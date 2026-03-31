---
layout: default
title: Core Concepts
nav_order: 3
description: "The runtime model behind Sage"
lang: en
ref: core-concepts
---

{% include lang_switcher.html %}

# Core Concepts

## `SAgent` Is the Runtime Entry

`sagents/sagents.py` exposes the `SAgent` class. Its `run_stream(...)` method is the central runtime API used to execute a session with:

- input messages
- model client and model configuration
- tool and skill managers
- sandbox configuration
- agent mode and flow selection

## Sessions Hold State

Sage treats the session as the unit of execution. A session carries:

- message history
- task progress
- runtime locks
- tool and skill access
- memory and context budget settings

The runtime creates or reuses sessions through the global session manager in `sagents/session_runtime.py`.

## Agent Modes

The runtime supports multiple execution styles:

- `simple`: direct single-agent interaction
- `multi`: multi-step orchestration through planning and execution agents
- `fibre`: advanced multi-agent orchestration with delegation support

Mode selection influences the default flow assembled inside `SAgent._build_default_flow(...)`.

## Flows Control Execution

`sagents/flow/` defines the declarative flow primitives used by the runtime, including sequence, parallel, condition, switch, and loop nodes. The runtime can:

- build the default flow automatically
- accept a custom flow
- combine flow control with agent mode and session state

## Tools and Skills Are Separate Extension Systems

### Tools

Tools are operational capabilities exposed to the model, implemented under `sagents/tool/`. This includes local built-in tools and MCP-backed tools.

### Skills

Skills are host-side instruction bundles and helper assets loaded by the skill system. The runtime exposes them through `SkillManager`.

## Sandboxing Is a First-Class Concern

Sandboxing lives under `sagents/utils/sandbox/`. The runtime supports:

- `local`
- `remote`
- `passthrough`

The effective sandbox mode is controlled by runtime arguments and `SAGE_SANDBOX_MODE`.

## Observability Is Built In

Sage includes OpenTelemetry-oriented observability components under `sagents/observability/`. Tracing is intended to be part of normal runtime operation, not a separate afterthought.
