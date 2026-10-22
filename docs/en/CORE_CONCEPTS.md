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

## RSI responsibilities

| Role | Responsibility |
| --- | --- |
| Designer | Design fixed dev and training suites; extend training challenges against the current version. |
| Runner | Execute a target version in fresh Sessions and retain actual output and tool evidence. |
| Evaluator | Independently grade each case against its rubric in a separate Session; assemble training feedback after required evaluations finish. |
| Tuner | Use training evidence and anonymous dev scores to propose an authorized Package patch. |
| Reviewer | Audit suite alignment and candidate goal/permission boundaries separately; reviews do not replace execution-based evaluation. |

The baseline covers the initial suite. Later rounds normally evaluate new train cases and retain existing evidence for the corresponding version; candidates are compared on the same accumulated train and fixed dev. Names identify responsibilities. Evaluation and tuning use separate Sessions; reusing a default model or Package does not imply shared conversation context.

RSI does not train model weights or automatically activate candidates. See the [workflow and support boundaries](applications/RSI.md).

## Execution

`StartRun → context assembly → model → authorized tools → further steps → completion or suspension`.

For example, asking an Agent to read a file and then sending another request to edit it normally creates two Runs in the same Session. If the second Run needs approval, it pauses for the user’s decision. The approval request and execution progress are stored in the Session.

Events report state changes that have happened. Disconnecting an event stream stops notifications, not the task. Resuming, cancelling, or answering an approval requires the corresponding command. A paused task is not complete.

Session history remains authoritative when summaries, memory, or diagnostics fail. Tool side effects whose outcome cannot be established must be reconciled, not blindly repeated.

[Python API](api/API_REFERENCE.md) · [Architecture](architecture/README.md)
