---
layout: default
title: Support Boundaries
nav_order: 22
lang: en
ref: v2-detail-support-boundaries
parent: Architecture
---

{% include lang_switcher.html %}

# Support Boundaries

## Execution and deployment

Desktop is a local single-user host. Server provides multi-user APIs and currently supports one worker. Built-in schedulers, Session stores, and background jobs do not form a distributed runtime; SQL persistence does not provide cross-host job takeover.

## Isolation and resources

Separate Sessions and temporary directories separate context and files; they do not replace an OS sandbox. Hosts and selected providers enforce tool permissions, credentials, resource bindings, and budgets. Local process execution does not establish container isolation or a unified memory limit for the entire process.

## RSI and recovery

Desktop RSI currently targets simple types and native tools. Python callers provide executable evaluation bindings, isolation, and authorization. Candidate generation, recommendation, and application are separate steps; users or callers explicitly control application. Persistent progress does not imply automatic checkpoint resume or retries of uncertain side effects.

## Validation and capacity

Offline regressions and small experiments validate their exercised behavior. Production databases, multi-tenant long conversations, platform releases, and failure recovery require measurements in the corresponding environment. Retain tested revisions, workloads, failures, and cost evidence.

[Single-host concurrency](sagents-v2-single-host-concurrency.md) · [Local sandbox constraints](sagents-v2-local-sandbox-security.md) · [Resource management](SAGENTS_V2_RESOURCE_MANAGEMENT.md) · [RSI workflow](../applications/RSI.md)
