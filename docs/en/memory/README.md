---
layout: default
title: Memory and Context
nav_order: 7
lang: en
ref: v2-memory-README
---

{% include lang_switcher.html %}

# Memory and Context

## Four different responsibilities

| Layer | Authority and purpose |
| --- | --- |
| SessionStore | Canonical Session history, Run state, and events. |
| Context | A temporary model-request projection of history and instructions. |
| Derived state | Summaries and other rebuildable data; never a second authoritative message ledger. |
| Memory providers | Long-term memory and retrieval over omitted Session history. |

Context reduction does not delete raw Session events. Fixed instructions and required current-turn content are protected by budgets; if they cannot fit, the runtime reports the problem instead of silently discarding constraints.

Skill loading has a separate active-context budget. Provider-reported usage can calibrate input estimates, but missing usage must not be invented or reported as measured tokens.

Desktop's summary state uses the selected SessionStore's derived namespace. Workspace identity and memory files belong to the workspace; they are not a substitute for Session storage. Neither local summary storage nor SQL persistence guarantees automatic replay of uncertain tool side effects.

[Context budgets (Chinese)](../../zh/architecture/sagents-v2-context-budget.md) · [Runtime reference](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/README.md)
