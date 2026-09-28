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
| Session | Holds a conversation’s history and the state, checkpoints, and pending interactions of its tasks. |
| Run | An execution attempt within a Session; it may complete, fail, cancel, or suspend for continuation. |
| Context | The content sent to the model for one request: instructions, selected history, tool descriptions, and relevant memory. |
| Interaction | A durable request for approval or user input. |
| Host | Desktop, Server, or your application; owns identity, credentials, UI, and conversation indexing. |

## Execution

`StartRun → context assembly → model → authorized tools → further steps → completion or suspension`.

For example, asking an Agent to read a file and then sending another request to edit it normally creates two Runs in the same Session. If the second Run needs approval, it pauses for the user’s decision. The approval request and execution progress are stored in the Session.

Events report state changes that have happened. Disconnecting an event stream stops notifications, not the task. Resuming, cancelling, or answering an approval requires the corresponding command. A paused task is not complete.

Session history remains authoritative when summaries, memory, or diagnostics fail. Tool side effects whose outcome cannot be established must be reconciled, not blindly repeated.

[Python API](api/API_REFERENCE.md) · [Architecture](architecture/README.md)
