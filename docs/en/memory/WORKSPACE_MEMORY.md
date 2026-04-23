---
layout: default
title: Workspace Memory
parent: Memory
nav_order: 3
description: "Agent workspace, MEMORY.md, workspace retrieval, and search_memory"
lang: en
ref: memory-workspace
---

{% include lang_switcher.html %}

# Workspace Memory

Agent workspace is also part of memory. The reason is simple: the Agent can read it, write it, summarize it, and retrieve it later.

## Scope

- Unit: current Agent workspace
- Contents: `AGENT.md`, `MEMORY.md`, `IDENTITY.md`, `USER.md`, task files, output files, notes
- Lifecycle: persists with the workspace and can be exported independently

## How It Works

- `AgentBase` reads `AGENT.md`, `MEMORY.md`, `USER.md`, and `IDENTITY.md` from the workspace
- `workspace_files` injects the current file tree into context
- `MemoryRecallAgent` searches workspace files through `search_memory`
- the agent `file_workspace` APIs can list, download, and delete workspace contents

## Why It Is Memory

Workspace files are not just attachments. They are externalized memory created by the Agent and read back later. They carry task traces, experience, working notes, and reusable decision artifacts.

## Relationship to `search_memory`

`search_memory` is not only for user memory. It also performs workspace-level file retrieval. From the Agent's perspective, searchable workspace content is memory.

