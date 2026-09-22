---
layout: default
title: Core Concepts
nav_order: 3
lang: en
ref: v2-CORE_CONCEPTS
---

{% include lang_switcher.html %}

# Core Concepts

| Concept | Meaning |
| --- | --- |
| Agent package | A validated manifest selecting agents, models, tools, Skills, and runtime plugins. It can come from YAML text, a Python object, or a file. |
| Application | `SAgentApplication` owns resolved components, runtime services, and their lifetimes. Always close it. |
| Session | The authority for conversation history, Runs, checkpoints, and interactions. |
| Run | An execution attempt within a Session; it may complete, fail, cancel, or suspend for continuation. |
| Context | A model-request projection assembled from history, instructions, tools, and derived memory. |
| Interaction | A durable request for approval or user input. |
| Host | Desktop, Server, or your application; owns identity, credentials, UI, and conversation indexing. |

## Execution

`StartRun → context assembly → model → authorized tools → further steps → completion or suspension`.

Events describe accepted runtime facts. Closing an observer detaches it; it does not cancel the Run. Resume, cancel, and interaction replies use explicit commands. A suspended Run is not a completed Run.

Session history remains authoritative when summaries, memory, or diagnostics fail. Tool side effects whose outcome cannot be established must be reconciled, not blindly repeated.

[Python API](api/API_REFERENCE.md) · [Architecture](architecture/README.md)
