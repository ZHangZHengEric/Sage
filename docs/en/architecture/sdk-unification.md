---
layout: default
title: SDK Integration Validation
parent: Architecture
nav_order: 23
lang: en
ref: v2-detail-sdk-unification
---

{% include lang_switcher.html %}

# Standard SDK integration validation

See the complete API and registration examples in the [SDK host development guide](sagents-host-development.md).

## Desktop standard execution

Desktop models, MCP/Studio tools, Skills, context, self-configuration and continuation are registered capabilities selected by runtime configuration. Agent `preload_skills` passes `sage-openui` to the standard loader, respecting authorization, budgets and activation recovery. Hosts do not inject Skill source directly.

Studio calls validate accepted Agent, Session and user identities. A Studio Session missing its Studio identity fails preflight without a replacement Run. Workspace initialization uses the currently selected registered capability.

`sage.execution.binding.ephemeral` provides an independent in-memory filesystem, without host Python, FFmpeg or network. It uses `workspace_root` and independent child workspaces. Paused content survives only within the same App; restart reports `execution.configuration_incompatible`. Long tasks and media use `sage.execution.binding.local-workspace`. Diagnostics expose `recovery: same_process`, isolation and actual capabilities.

Tests include `tests/app/v2/desktop`, `test_standard_execution_configuration.py`, `test_standard_capability_scopes.py`, `test_builder_nested_teams.py`, `test_ephemeral_execution_binding.py` and the development/frozen media reference `test_standard_host_reference.py`.

## Server standard execution

Server uses the same App, Agent loading and execution entrypoints. Capabilities obtain identity, tool authorization and resources from `execution.environment` and accepted product configuration. Product catalog and execution identities are checked separately. Child tool scope follows declarations and cannot expand through dependency packages.

Scheduler registrations declare model-pool dependencies and retain concurrency/queue settings. App stops execution and scheduling before closing dependencies. Runtime configuration selects public protocols such as `ag-ui` and `a2a`. `tests/app/v2/server` covers both entrypoints, recovery, concurrency, authorization, media and cleanup.

## Local validation on 2026-10-19

macOS / Python 3.13 validation included custom factories, standard Runs, frozen configuration, recovery, nested Teams, leases and lifecycle. Repeatable model/MCP implementations were used; media tests actually ran Python/Pillow and FFmpeg.

| Scope | Result |
| --- | --- |
| `tests/sagents/v2` | 3265 passed, 55 skipped |
| Desktop, Server and CLI v2 entrypoints | 958 passed, 1 skipped |
| All `tests/app/clients/cli` | 225 passed |
| Host assembly, plugins and lifecycle after shared-store fixes | 56 passed |
| Development and freshly rebuilt frozen reference media host | 4 passed |
| Ruff and `git diff --check` | Passed |

Host and CLI suites overlap and must not be added. Server skipped unconfigured external MySQL. SDK skips include optional services, platforms and opt-in acceptance; the four media reference cases ran explicitly. This record does not establish Linux frozen-build acceptance or multi-day endurance. The reference is `examples/v2/standard_host`.

## Direct recovery of nested paused children

A child can resume while ancestors remain paused. Sage restores ancestor leases before loop assembly and selects the original graph's child Agent without running ancestor models, replacing tasks or applying current settings. Missing dependencies and unrecoverable configuration have distinct outcomes.

See [nested Run recovery](sagents-v2-run-tree-recovery.md) for calls, ownership, release order and validation scope.

## Host control interface audit

See the [standard host control audit](sagents-v2-host-controls.md) for approvals, publication, cancellation, pause, recovery and unavailable Server endpoints. Counts above belong to their recorded validation rounds; newer control checks are recorded separately.
