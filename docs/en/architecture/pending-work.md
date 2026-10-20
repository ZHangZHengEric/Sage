---
layout: default
title: Pending Work and Validation
parent: Architecture
nav_order: 22
lang: en
ref: v2-detail-pending-work
---

{% include lang_switcher.html %}

# Pending work and validation

## Pending implementation

| Area | Remaining work | Design and current boundaries |
| --- | --- | --- |
| Desktop Agent customization | Complete package, Flow, version and run management UI; existing Agent settings are not a complete package manager | [Agent package management](SAGENTS_V2_AGENT_MANAGEMENT.md) |
| Studio collaboration | Automatic Agent request/result dispatch, durable inboxes, dependency waits and recovery; group files, versioned artifacts, Project binding and project-write coordination across conversations | [Studio collaboration proposal](https://github.com/ZHangZHengEric/Sage/blob/main/docs/archive/zh/architecture/DESKTOP_V2_STUDIO_DESIGN.md) |
| Host resource budgets | Process-wide memory limits, fair scheduling and unified constraints for plugin-created threads/processes; shared model budgets, JobRuntime and safe idle reclamation already exist | [Resource management](SAGENTS_V2_RESOURCE_MANAGEMENT.md) |
| Distributed execution | Admission, scheduling, leases, subscriptions and durable JobRuntime for multiple processes/hosts; adding Server workers cannot replace these mechanisms | [Single-host boundaries](sagents-v2-single-host-concurrency.md) |
| Third-party cold reads | A generic offline terminal-result interface for arbitrary SessionStores; built-in filesystem cold reads and terminal archives already exist | [Terminal archives and reads](SAGENTS_V2_RESOURCE_MANAGEMENT.md) |
| Source plugins | Automatic dependency installation, isolated builds and untrusted-code sandboxes; current loading requires explicit host trust and runs in-process | [Plugins and Flow](SAGENTS_V2_AGENT_MANAGEMENT.md) |
| Server controls | Separate manual-pause and candidate Session publication/rejection HTTP endpoints; the SDK already provides these contracts | [Host controls](sagents-v2-host-controls.md) |
| Remote Skill import | Marketplaces, private repositories, a separate Git URL input, source update checks and team HTTP catalogs; online ZIP and Skills CLI import already exist | [Remote import proposal](skill-import-proposal.md) |
| Read-only Skill mounts | Mount ports in built-in local, ephemeral and Cube sandboxes; the public contract and workspace strategy already exist | [Skill workspace boundaries](sagents-skill-management-and-usage.md) |

The Studio proposal retains the full collaboration target. Its initial UI implementation and early validation records are historical context. Host result publication and reconciliation already exist in current source and are not pending work.

## Pending validation and rechecks

- Run sustained loads and fault injection with real models, target databases, multiple tenants and long Sessions. Measure completion, missed requirements, tail latency, memory, queues and resource release after cancellation. Offline regression and small model experiments do not establish endurance or capacity.
- Validate Linux frozen builds, Chromium in the candidate image and native Windows/Linux hosts in their target environments. Filesystem storage already has a Windows locking adapter; the old missing-lock item is obsolete.
- Recheck the Flutter Studio periodic Timer, synchronous log-queue timeout and Server `/studio` test dependence on local Web dist recorded during the old refactor validation. Old failure counts are not current results; rerun the relevant tests in isolated environments.

Other proposed product directions remain in their original designs: [AgentFlow productization](https://github.com/ZHangZHengEric/Sage/blob/main/docs/archive/zh/architecture/DESIGN_AGENT_FLOW_PRODUCTIZATION.md), [permissions and confirmation](https://github.com/ZHangZHengEric/Sage/blob/main/docs/archive/zh/architecture/DESIGN_PERMISSIONS_AND_CONFIRMATION.md), and [continuous learning and RSI](https://github.com/ZHangZHengEric/Sage/blob/main/docs/archive/zh/architecture/DESIGN_SAGE_RSI.md). These proposals are not current API references; consult the corresponding product documentation for implemented scope.
